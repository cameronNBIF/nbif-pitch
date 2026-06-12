"""
handler.py
Main HTTP trigger function for the Pitch Intake Form.
Orchestrates the pipeline: validate → archive → Affinity → notify.

No file upload — pitch deck was removed from the form (June 2026).
"""

import json
import logging
import os
import uuid
import azure.functions as func
import requests

from . import bp
from .affinity_client import (
    create_list_entry,
    populate_list_entry,
    resolve_or_create_organization,
    resolve_or_create_person,
)
from .storage_client import (
    archive_submission,
    check_duplicate,
    record_submission_fingerprint,
    send_to_deadletter,
    update_archive,
)
from .cloudflare_turnstile import verify_turnstile_token
from .validators import validate_submission

logger = logging.getLogger(__name__)


# ── Helper: Extract domain from URL ───────────────────────────────────────


def _extract_domain(url: str) -> str:
    """Extract the root domain from a URL string."""
    if not url:
        return ""
    url = url.lower().strip()
    for prefix in ("https://", "http://", "www."):
        if url.startswith(prefix):
            url = url[len(prefix):]
    url = url.split("/")[0]
    return url


# ── Helper: Send Teams notification ───────────────────────────────────────


def _send_teams_notification(
    webhook_url: str,
    form_data: dict,
    affinity_org_id: int | None = None,
) -> None:
    """
    Send a notification to the VC team via Teams Incoming Webhook.
    Non-critical — failures are logged but don't affect the submission.
    """
    business_name = form_data.get("business_name", "Unknown")
    first_name = form_data.get("first_name", "")
    last_name = form_data.get("last_name", "")
    sector = form_data.get("sector", "N/A")
    venture_stage = form_data.get("venture_stage", "N/A")

    card_body = [
        {
            "type": "TextBlock",
            "size": "Large",
            "weight": "Bolder",
            "text": f"📩 New Pitch Submission: {business_name}",
        },
        {
            "type": "FactSet",
            "facts": [
                {"title": "Founder", "value": f"{first_name} {last_name}"},
                {"title": "Email", "value": form_data.get("email", "N/A")},
                {"title": "Sector", "value": sector},
                {"title": "Venture Stage", "value": venture_stage},
                {
                    "title": "Discovery",
                    "value": form_data.get("discovery", "N/A"),
                },
            ],
        },
    ]

    payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "body": card_body,
                },
            }
        ],
    }

    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Teams notification sent for: {business_name}")
    except Exception as e:
        logger.error(f"Teams notification failed: {e}. Non-critical — continuing.")


# ── Helper: Get config from environment ───────────────────────────────────


def _get_config() -> dict[str, str]:
    """Load all configuration from environment variables (app settings)."""

    required_keys = [
        "AFFINITY_API_KEY",
        "NBIF_PITCH_SA_CONNECTION_STRING",
        "CLOUDFLARE_TURNSTILE_SECRET_KEY",
        "AFFINITY_LIST_ID",
    ]
    missing = [k for k in required_keys if k not in os.environ]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    config = {
        "AFFINITY_API_KEY": os.environ["AFFINITY_API_KEY"],
        "STORAGE_CONN_STR": os.environ["NBIF_PITCH_SA_CONNECTION_STRING"],
        "TURNSTILE_SECRET": os.environ["CLOUDFLARE_TURNSTILE_SECRET_KEY"],
        "LIST_ID": os.environ["AFFINITY_LIST_ID"],
        "CONTAINER_SUBMISSIONS": os.environ.get(
            "AZURE_BLOB_CONTAINER_SUBMISSIONS", "submissions"
        ),
        "TABLE_DEDUP": os.environ.get("AZURE_TABLE_NAME_DEDUP", "dedup"),
        "QUEUE_DEADLETTER": os.environ.get(
            "AZURE_QUEUE_NAME_DEADLETTER", "pitchintakedeadletter"
        ),
        "TEAMS_WEBHOOK_URL": os.environ.get("TEAMS_WEBHOOK_URL", ""),
    }

    return config


# ── Main Function ─────────────────────────────────────────────────────────


@bp.route(
    route="pitch-intake",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.FUNCTION,
)
def pitch_intake(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger for Pitch Intake Form submissions.

    Receives form data from the custom form on nbif.ca,
    validates the submission, archives it to Blob Storage,
    creates records in Affinity CRM, and notifies the VC team.

    Pipeline:
      1. Extract form data
      2. Verify CAPTCHA token
      3. Validate form fields
      4. Check for duplicate submission
      5. Archive raw submission to Blob Storage
      6. Resolve/create Person in Affinity
      7. Resolve/create Organization in Affinity
      8. Create List Entry in Affinity
      9. Set field values on the list entry
     10. Update submission archive with results
     11. Send notification to VC team
     12. Return success response
    """
    submission_id = str(uuid.uuid4())
    logger.info(f"[{submission_id}] Pitch Intake submission received.")

    # ── Load configuration ────────────────────────────────────────────

    try:
        config = _get_config()
    except KeyError as e:
        logger.critical(f"[{submission_id}] Missing configuration: {e}")
        return func.HttpResponse(
            json.dumps({"error": "Server configuration error."}),
            status_code=500,
            mimetype="application/json",
        )

    # ── Phase 1: Extract & Validate (errors returned to user) ─────────

    # Step 1: Extract form data
    try:
        form = req.form

        form_data_raw = {
            "first_name": form.get("first_name", ""),
            "last_name": form.get("last_name", ""),
            "business_name": form.get("business_name", ""),
            "email": form.get("email", ""),
            "phone": form.get("phone", ""),
            "website": form.get("website", ""),
            "sector": form.get("sector", ""),
            "venture_stage": form.get("venture_stage", ""),
            "date_of_incorporation": form.get("date_of_incorporation", ""),
            "company_profile": form.get("company_profile", ""),
            "investment_round_size": form.get("investment_round_size", ""),
            "potential_investment_amount": form.get("potential_investment_amount", ""),
            "discovery": form.get("discovery", ""),
            "accelerators": form.get("accelerators", ""),
        }

        captcha_token = form.get("cf-turnstile-response", "")

        logger.info(
            f"[{submission_id}] Form data extracted. "
            f"Business: {form_data_raw.get('business_name')}, "
            f"Email: {form_data_raw.get('email')}"
        )

    except Exception as e:
        logger.error(f"[{submission_id}] Failed to extract form data: {e}")
        return func.HttpResponse(
            json.dumps({"error": "Failed to parse form submission."}),
            status_code=400,
            mimetype="application/json",
        )

    # Step 2: Verify CAPTCHA
    client_ip = req.headers.get("X-Forwarded-For", "").split(",")[0].strip()

    if not verify_turnstile_token(
        captcha_token, config["TURNSTILE_SECRET"], client_ip or None
    ):
        logger.warning(f"[{submission_id}] CAPTCHA verification failed.")
        return func.HttpResponse(
            json.dumps({"error": "CAPTCHA verification failed. Please try again."}),
            status_code=403,
            mimetype="application/json",
        )

    # Step 3: Validate form fields
    validated_data, errors = validate_submission(form_data_raw)

    if errors:
        logger.info(f"[{submission_id}] Validation failed: {errors}")
        return func.HttpResponse(
            json.dumps({"error": "Validation failed.", "details": errors}),
            status_code=400,
            mimetype="application/json",
        )

    # Step 4: Check for duplicate submission
    if check_duplicate(
        config["STORAGE_CONN_STR"],
        config["TABLE_DEDUP"],
        validated_data["email"],
        validated_data["business_name"],
    ):
        logger.warning(f"[{submission_id}] Duplicate submission detected.")
        return func.HttpResponse(
            json.dumps(
                {
                    "error": "A submission with this email and business name was "
                    "received very recently. Please wait a moment before "
                    "resubmitting."
                }
            ),
            status_code=409,
            mimetype="application/json",
        )

    # Record fingerprint for future dedup checks
    record_submission_fingerprint(
        config["STORAGE_CONN_STR"],
        config["TABLE_DEDUP"],
        validated_data["email"],
        validated_data["business_name"],
        submission_id,
    )

    # ── Phase 2: Archive to Blob Storage (errors returned to user) ────

    # Step 5: Archive raw submission
    try:
        archive_blob_path = archive_submission(
            config["STORAGE_CONN_STR"],
            config["CONTAINER_SUBMISSIONS"],
            submission_id,
            validated_data,
        )
    except Exception as e:
        logger.error(f"[{submission_id}] Failed to archive submission: {e}")
        return func.HttpResponse(
            json.dumps({"error": "Failed to process submission. Please try again."}),
            status_code=500,
            mimetype="application/json",
        )

    # ── Phase 3: Affinity CRM (dead-letter on failure) ────────────────
    # From this point on, the user gets a success response regardless.
    # If Affinity calls fail, the submission is dead-lettered for retry.

    person_id = None
    org_id = None
    entry_id = None
    affinity_success = False

    try:
        api_key = config["AFFINITY_API_KEY"]
        list_id = int(config["LIST_ID"])

        # Step 6: Resolve or create Person (founder)
        person_id = resolve_or_create_person(
            api_key,
            validated_data["first_name"],
            validated_data["last_name"],
            validated_data["email"],
        )
        logger.info(f"[{submission_id}] Person resolved/created: {person_id}")

        # Step 7: Resolve or create Organization
        domain = _extract_domain(validated_data.get("website", ""))
        org_id = resolve_or_create_organization(
            api_key,
            validated_data["business_name"],
            domain,
        )
        logger.info(f"[{submission_id}] Organization resolved/created: {org_id}")

        # Step 8: Create List Entry (entity = Organization)
        entry_id = create_list_entry(api_key, list_id, org_id)
        logger.info(f"[{submission_id}] List entry created: {entry_id}")

        # Step 9: Set all field values

        populate_list_entry(
            api_key,
            org_id,
            entry_id,
            person_id,
            validated_data,
        )
        logger.info(f"[{submission_id}] Field values populated on entry {entry_id}")

        affinity_success = True

    except Exception as e:
        logger.error(
            f"[{submission_id}] Affinity CRM operations failed: {e}. "
            f"Sending to dead-letter queue."
        )
        send_to_deadletter(
            config["STORAGE_CONN_STR"],
            config["QUEUE_DEADLETTER"],
            submission_id,
            archive_blob_path,
            str(e),
            failed_step="affinity_crm",
        )

    # ── Phase 4: Post-processing ──────────────────────────────────────

    # Step 10: Update archive with Affinity IDs
    update_archive(
        config["STORAGE_CONN_STR"],
        config["CONTAINER_SUBMISSIONS"],
        archive_blob_path,
        {
            "processing_status": "completed" if affinity_success else "failed",
            "affinity_ids": {
                "person_id": person_id,
                "organization_id": org_id,
                "list_entry_id": entry_id,
            },
        },
    )

    # Step 11: Send notification to VC team
    teams_webhook = config.get("TEAMS_WEBHOOK_URL", "")
    if teams_webhook and affinity_success:
        _send_teams_notification(teams_webhook, validated_data, org_id)

    # Step 12: Return success response
    logger.info(
        f"[{submission_id}] Pipeline complete. "
        f"Affinity success: {affinity_success}. "
        f"Person: {person_id}, Org: {org_id}, Entry: {entry_id}"
    )

    return func.HttpResponse(
        json.dumps(
            {
                "status": "success",
                "message": "Thank you for your submission. Our team will review "
                "your pitch and be in touch.",
                "submission_id": submission_id,
            }
        ),
        status_code=200,
        mimetype="application/json",
    )
