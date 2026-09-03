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
from .slack_client import send_slack_notification
from .cloudflare_turnstile import verify_turnstile_token
from .utils import extract_domain
from .validators import validate_submission

logger = logging.getLogger(__name__)


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
        "SLACK_BOT_USER_OAUTH_TOKEN": os.environ.get("SLACK_BOT_USER_OAUTH_TOKEN", ""),
        "SLACK_INTAKE_CHANNEL_ID": os.environ.get("SLACK_INTAKE_CHANNEL_ID", ""),
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
    except (KeyError, RuntimeError) as e:
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
            "company_name": form.get("company_name", ""),
            "email": form.get("email", ""),
            "phone": form.get("phone", ""),
            "website": form.get("website", ""),
            "sector": form.get("sector", ""),
            "venture_stage": form.get("venture_stage", ""),
            "date_of_incorporation": form.get("date_of_incorporation", ""),
            "company_problem": form.get("company_problem", ""),
            "company_solution": form.get("company_solution", ""),
            "company_progress": form.get("company_progress", ""),
            "discovery": form.get("discovery", ""),
            "accelerators": form.get("accelerators", ""),
        }

        captcha_token = form.get("cf-turnstile-response", "")

        logger.info(
            f"[{submission_id}] Form data extracted. "
            f"Company: {form_data_raw.get('company_name')}, "
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
        validated_data["company_name"],
    ):
        logger.warning(f"[{submission_id}] Duplicate submission detected.")
        return func.HttpResponse(
            json.dumps(
                {
                    "error": "A submission with this email and company name was "
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
        validated_data["company_name"],
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
        domain = extract_domain(validated_data.get("website", ""))
        org_id = resolve_or_create_organization(
            api_key,
            validated_data["company_name"],
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
    slack_bot_user_oauth_token = config.get("SLACK_BOT_USER_OAUTH_TOKEN", "")
    slack_intake_channel_id = config.get("SLACK_INTAKE_CHANNEL_ID", "")
    if slack_bot_user_oauth_token and slack_intake_channel_id and affinity_success:
        send_slack_notification(
            slack_bot_user_oauth_token, slack_intake_channel_id, validated_data
        )

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
