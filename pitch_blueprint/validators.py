"""
validators.py
Server-side validation for Pitch Intake Form submissions.
Validates required fields, conditional logic, file type, and file size.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB
ALLOWED_FILE_EXTENSIONS = {".pdf", ".pptx", ".ppt"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
    "application/vnd.ms-powerpoint",  # .ppt
}
MAX_EXECUTIVE_SUMMARY_WORDS = 150

VALID_CORPORATE_ENTITY_VALUES = {
    "No",
    "Yes — Federally",
    "Yes — In New Brunswick",
    "Yes — Other Province/Territory",
}
VALID_YES_NO = {"Yes", "No"}

# Email regex — simple but effective for form validation
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


# ── Validation Functions ──────────────────────────────────────────────────


def validate_submission(
    form_data: dict[str, str],
    file_info: dict[str, Any] | None,
    valid_sectors: list[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Validate all form fields and the uploaded file.

    Args:
        form_data: Dictionary of form field name → value (from req.form).
        file_info: Dictionary with keys 'filename', 'content_type', 'size_bytes',
                   or None if no file was uploaded.
        valid_sectors: Optional list of valid Priority Sector values.
                       If None, sector validation is skipped (any non-empty value accepted).

    Returns:
        Tuple of (validated_data, errors).
        - validated_data: Cleaned/normalized form data (only populated if no errors).
        - errors: List of human-readable error messages. Empty list = valid.
    """
    errors = []
    validated = {}

    # ── Required text fields ──────────────────────────────────────────

    required_text_fields = [
        ("first_name", "First Name"),
        ("last_name", "Last Name"),
        ("business_name", "Business Name"),
        ("email", "Email"),
        ("phone", "Phone Number"),
        ("city", "City"),
    ]

    for field_key, field_label in required_text_fields:
        value = (form_data.get(field_key) or "").strip()
        if not value:
            errors.append(f"{field_label} is required.")
        else:
            validated[field_key] = value

    # ── Email format ──────────────────────────────────────────────────

    email = validated.get("email", "")
    if email and not EMAIL_REGEX.match(email):
        errors.append("Email address is not valid.")

    # ── Website (optional) ────────────────────────────────────────────

    website = (form_data.get("website") or "").strip()
    validated["website"] = website  # Can be empty

    # ── Sector (required, must match Affinity dropdown) ───────────────

    sector = (form_data.get("sector") or "").strip()
    if not sector:
        errors.append("Sector is required.")
    elif valid_sectors and sector not in valid_sectors:
        errors.append(
            f"Invalid sector: '{sector}'. Must be one of: {', '.join(valid_sectors)}."
        )
    validated["sector"] = sector

    # ── Executive Summary (required, max 150 words) ───────────────────

    executive_summary = (form_data.get("executive_summary") or "").strip()
    if not executive_summary:
        errors.append("Executive Summary is required.")
    else:
        word_count = len(executive_summary.split())
        if word_count > MAX_EXECUTIVE_SUMMARY_WORDS:
            errors.append(
                f"Executive Summary exceeds {MAX_EXECUTIVE_SUMMARY_WORDS} words "
                f"(currently {word_count} words)."
            )
    validated["executive_summary"] = executive_summary

    # ── Corporate Entity (required dropdown) ──────────────────────────

    corporate_entity = (form_data.get("corporate_entity") or "").strip()
    if not corporate_entity:
        errors.append("Corporate entity status is required.")
    elif corporate_entity not in VALID_CORPORATE_ENTITY_VALUES:
        errors.append(
            f"Invalid corporate entity value: '{corporate_entity}'."
        )
    validated["corporate_entity"] = corporate_entity

    # ── Date of Incorporation (conditional — required if corp entity = Yes) ─

    is_incorporated = corporate_entity.startswith("Yes")
    date_of_incorporation = (form_data.get("date_of_incorporation") or "").strip()
    if is_incorporated and not date_of_incorporation:
        errors.append(
            "Date of Incorporation is required when a corporate entity has been established."
        )
    validated["date_of_incorporation"] = date_of_incorporation if is_incorporated else ""

    # ── Currently Raising Capital (required) ──────────────────────────

    raising_capital = (form_data.get("raising_capital") or "").strip()
    if not raising_capital:
        errors.append("'Are you currently raising capital?' is required.")
    elif raising_capital not in VALID_YES_NO:
        errors.append(f"Invalid value for raising capital: '{raising_capital}'.")
    validated["raising_capital"] = raising_capital

    # ── Financing Amount (conditional — required if raising capital = Yes) ─

    is_raising = raising_capital == "Yes"
    financing_amount = (form_data.get("financing_amount") or "").strip()
    if is_raising and not financing_amount:
        errors.append(
            "Amount of financing is required when currently raising capital."
        )
    elif is_raising and financing_amount:
        try:
            # Remove commas, dollar signs, spaces
            cleaned = financing_amount.replace(",", "").replace("$", "").replace(" ", "")
            validated["financing_amount"] = float(cleaned)
        except ValueError:
            errors.append(
                f"Invalid financing amount: '{financing_amount}'. Must be a number."
            )
    else:
        validated["financing_amount"] = None

    # ── Current Investors (optional) ──────────────────────────────────

    validated["current_investors"] = (form_data.get("current_investors") or "").strip()

    # ── IP Reliance (required) ────────────────────────────────────────

    ip_reliance = (form_data.get("ip_reliance") or "").strip()
    if not ip_reliance:
        errors.append("'Will the venture rely on IP?' is required.")
    elif ip_reliance not in VALID_YES_NO:
        errors.append(f"Invalid value for IP reliance: '{ip_reliance}'.")
    validated["ip_reliance"] = ip_reliance

    # ── IP Ownership Details (conditional — required if IP = Yes) ─────

    has_ip = ip_reliance == "Yes"
    ip_ownership_details = (form_data.get("ip_ownership_details") or "").strip()
    if has_ip and not ip_ownership_details:
        errors.append(
            "IP ownership details are required when the venture relies on IP."
        )
    validated["ip_ownership_details"] = ip_ownership_details if has_ip else ""

    # ── Pitch Deck File ───────────────────────────────────────────────

    if file_info is None:
        errors.append("Pitch Deck file is required.")
    else:
        filename = file_info.get("filename", "")
        content_type = file_info.get("content_type", "")
        size_bytes = file_info.get("size_bytes", 0)

        # Check file extension
        ext = ""
        if "." in filename:
            ext = "." + filename.rsplit(".", 1)[-1].lower()

        if ext not in ALLOWED_FILE_EXTENSIONS:
            errors.append(
                f"Invalid file type: '{ext}'. Accepted types: "
                f"{', '.join(sorted(ALLOWED_FILE_EXTENSIONS))}."
            )

        # Check MIME type
        if content_type and content_type not in ALLOWED_MIME_TYPES:
            logger.warning(
                f"Unexpected MIME type: '{content_type}' for file '{filename}'. "
                f"Extension: '{ext}'. Proceeding with extension-based validation."
            )

        # Check file size
        if size_bytes > MAX_FILE_SIZE_BYTES:
            size_mb = round(size_bytes / (1024 * 1024), 1)
            errors.append(
                f"Pitch Deck file is too large ({size_mb} MB). "
                f"Maximum size is {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB."
            )

    if errors:
        logger.info(f"Validation failed with {len(errors)} error(s): {errors}")

    return validated, errors