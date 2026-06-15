"""
validators.py
Server-side validation for Pitch Intake Form submissions.
Validates required fields and data formats.

Aligned with production Affinity list fields (June 2026).
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

MAX_COMPANY_PROFILE_WORDS = 150

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

# Valid dropdown values — must match the form <option> values exactly
VALID_SECTORS = {
    "Advanced Manufacturing",
    "Agritech",
    "Cybersecurity",
    "Digital Health",
    "Energy",
    "Forestry",
    "ICT",
    "Other",
}

VALID_VENTURE_STAGES = {
    "Series A",
    "Research or Lab Stage",
    "Seed",
    "Accelerator Stage",
    "Pre-seed",
}


# ── Validation ────────────────────────────────────────────────────────────


def validate_submission(
    form_data: dict[str, str],
) -> tuple[dict[str, Any], list[str]]:
    """
    Validate all form fields.

    Args:
        form_data: Dictionary of form field name → value.

    Returns:
        Tuple of (validated_data, errors).
        - validated_data: Cleaned/normalized form data.
        - errors: List of human-readable error messages. Empty = valid.
    """
    errors = []
    validated: dict[str, Any] = {}

    # ── Required text fields ──────────────────────────────────────────

    required_text_fields = [
        ("first_name", "First Name"),
        ("last_name", "Last Name"),
        ("business_name", "Business Name"),
        ("email", "Email"),
        ("phone", "Phone Number"),
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

    validated["website"] = (form_data.get("website") or "").strip()

    # ── Priority Sector (required, dropdown) ──────────────────────────

    sector = (form_data.get("sector") or "").strip()
    if not sector:
        errors.append("Priority Sector is required.")
    elif sector not in VALID_SECTORS:
        errors.append(
            f"Invalid sector: '{sector}'. "
            f"Must be one of: {', '.join(sorted(VALID_SECTORS))}."
        )
    validated["sector"] = sector

    # ── Venture Stage (required, dropdown) ────────────────────────────

    venture_stage = (form_data.get("venture_stage") or "").strip()
    if not venture_stage:
        errors.append("Venture Stage is required.")
    elif venture_stage not in VALID_VENTURE_STAGES:
        errors.append(
            f"Invalid venture stage: '{venture_stage}'. "
            f"Must be one of: {', '.join(sorted(VALID_VENTURE_STAGES))}."
        )
    validated["venture_stage"] = venture_stage

    # ── Date of Incorporation (optional) ──────────────────────────────

    validated["date_of_incorporation"] = (
        form_data.get("date_of_incorporation") or ""
    ).strip()

    # ── Company Profile (optional, text) ──────────────────────────────

    company_profile = (form_data.get("company_profile") or "").strip()
    if company_profile:
        word_count = len(company_profile.split())
        if word_count > MAX_COMPANY_PROFILE_WORDS:
            errors.append(
                f"Company Profile exceeds {MAX_COMPANY_PROFILE_WORDS} words "
                f"(currently {word_count} words)."
            )
    validated["company_profile"] = company_profile

    # ── Investment Round Size (optional, number) ──────────────────────

    round_size_raw = (form_data.get("investment_round_size") or "").strip()
    if round_size_raw:
        try:
            cleaned = round_size_raw.replace(",", "").replace("$", "").replace(" ", "")
            validated["investment_round_size"] = float(cleaned)
        except ValueError:
            errors.append(
                f"Invalid Investment Round Size: '{round_size_raw}'. Must be a number."
            )
    else:
        validated["investment_round_size"] = None

    # ── Potential Investment Amount (optional, number) ─────────────────

    potential_raw = (form_data.get("potential_investment_amount") or "").strip()
    if potential_raw:
        try:
            cleaned = potential_raw.replace(",", "").replace("$", "").replace(" ", "")
            validated["potential_investment_amount"] = float(cleaned)
        except ValueError:
            errors.append(
                f"Invalid Potential Investment Amount: '{potential_raw}'. "
                f"Must be a number."
            )
    else:
        validated["potential_investment_amount"] = None

    # ── Discovery (optional, text) ────────────────────────────────────
    # Form label: "How did you hear about NBIF?"

    validated["discovery"] = (form_data.get("discovery") or "").strip()

    # ── Accelerator (optional, text) ────
    # Form label: "Have you participated in any accelerator program, if so, please list them"
    validated["accelerators"] = (form_data.get("accelerators") or "").strip()

    if errors:
        logger.info(f"Validation failed with {len(errors)} error(s): {errors}")

    return validated, errors
