"""
affinity_client.py
Affinity CRM API helper functions.
Handles person/organization resolution, list entry creation,
field value population, and entity file uploads.

API Reference: https://api-docs.affinity.co/
Authentication: Basic auth with empty username and API key as password.
"""

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.affinity.co"

# Retry configuration for transient failures
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 2


# ── HTTP Helpers ──────────────────────────────────────────────────────────


def _auth(api_key: str) -> tuple[str, str]:
    """Return Basic auth tuple for Affinity API (empty username, key as password)."""
    return ("", api_key)


def _request_with_retry(
    method: str,
    url: str,
    api_key: str,
    retries: int = MAX_RETRIES,
    **kwargs,
) -> requests.Response:
    """
    Make an HTTP request with retry logic and exponential backoff.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE).
        url: Full URL.
        api_key: Affinity API key.
        retries: Number of retries on failure.
        **kwargs: Additional arguments passed to requests.request().

    Returns:
        requests.Response object.

    Raises:
        requests.HTTPError: If the request fails after all retries.
    """
    last_exception = None

    for attempt in range(retries + 1):
        try:
            response = requests.request(
                method,
                url,
                auth=_auth(api_key),
                timeout=30,
                **kwargs,
            )
            response.raise_for_status()
            return response

        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else 0

            # Don't retry on client errors (4xx) except 429 (rate limit)
            if 400 <= status_code < 500 and status_code != 429:
                logger.error(
                    f"Affinity API client error: {status_code} {method} {url} — "
                    f"Response: {e.response.text[:500] if e.response else 'N/A'}"
                )
                raise

            last_exception = e
            if attempt < retries:
                wait = RETRY_BACKOFF_SECONDS * (2 ** attempt)
                logger.warning(
                    f"Affinity API error (attempt {attempt + 1}/{retries + 1}): "
                    f"{status_code} {method} {url}. Retrying in {wait}s..."
                )
                time.sleep(wait)
            else:
                logger.error(
                    f"Affinity API failed after {retries + 1} attempts: "
                    f"{status_code} {method} {url}"
                )

        except requests.RequestException as e:
            last_exception = e
            if attempt < retries:
                wait = RETRY_BACKOFF_SECONDS * (2 ** attempt)
                logger.warning(
                    f"Affinity API request error (attempt {attempt + 1}/{retries + 1}): "
                    f"{e}. Retrying in {wait}s..."
                )
                time.sleep(wait)
            else:
                logger.error(
                    f"Affinity API request failed after {retries + 1} attempts: {e}"
                )

    raise last_exception  # type: ignore[misc]


# ── Persons ───────────────────────────────────────────────────────────────


def search_person_by_email(api_key: str, email: str) -> int | None:
    """
    Search for a person in Affinity by email address.

    Args:
        api_key: Affinity API key.
        email: Email address to search for.

    Returns:
        The person ID if found, None otherwise.
    """
    response = _request_with_retry(
        "GET",
        f"{BASE_URL}/persons",
        api_key,
        params={"term": email},
    )
    persons = response.json()

    if not isinstance(persons, dict):
        logger.warning(f"Unexpected response format from /persons: {type(persons)}")
        return None

    # The v1 API returns {"persons": [...]} 
    person_list = persons.get("persons", [])

    # Find exact email match (search may return partial matches)
    for person in person_list:
        person_emails = [e.lower() for e in person.get("emails", [])]
        if email.lower() in person_emails:
            person_id = person["id"]
            logger.info(f"Found existing person: {person_id} for email {email}")
            return person_id

    logger.info(f"No existing person found for email: {email}")
    return None


def create_person(
    api_key: str,
    first_name: str,
    last_name: str,
    email: str,
    phone: str = "",
) -> int:
    """
    Create a new person in Affinity.

    Args:
        api_key: Affinity API key.
        first_name: Person's first name.
        last_name: Person's last name.
        email: Person's email address.
        phone: Person's phone number (optional).

    Returns:
        The newly created person's ID.
    """
    payload: dict[str, Any] = {
        "first_name": first_name,
        "last_name": last_name,
        "emails": [email],
    }
    if phone:
        payload["phone_numbers"] = [phone]

    response = _request_with_retry(
        "POST",
        f"{BASE_URL}/persons",
        api_key,
        json=payload,
    )

    person = response.json()
    person_id = person["id"]
    logger.info(f"Created new person: {person_id} ({first_name} {last_name})")
    return person_id


def resolve_or_create_person(
    api_key: str,
    first_name: str,
    last_name: str,
    email: str,
    phone: str = "",
) -> int:
    """
    Find an existing person by email, or create a new one.

    Returns:
        The person ID (existing or newly created).
    """
    person_id = search_person_by_email(api_key, email)
    if person_id:
        return person_id
    return create_person(api_key, first_name, last_name, email, phone)


# ── Organizations ─────────────────────────────────────────────────────────


def search_organization_by_name(api_key: str, name: str) -> int | None:
    """
    Search for an organization in Affinity by name.

    Args:
        api_key: Affinity API key.
        name: Organization name to search for.

    Returns:
        The organization ID if found, None otherwise.
    """
    response = _request_with_retry(
        "GET",
        f"{BASE_URL}/organizations",
        api_key,
        params={"term": name},
    )
    result = response.json()

    if not isinstance(result, dict):
        logger.warning(
            f"Unexpected response format from /organizations: {type(result)}"
        )
        return None

    org_list = result.get("organizations", [])

    # Find exact name match (case-insensitive)
    for org in org_list:
        if org.get("name", "").lower().strip() == name.lower().strip():
            org_id = org["id"]
            logger.info(f"Found existing organization: {org_id} ({name})")
            return org_id

    logger.info(f"No existing organization found for: {name}")
    return None


def create_organization(
    api_key: str,
    name: str,
    domain: str = "",
) -> int:
    """
    Create a new organization in Affinity.

    Args:
        api_key: Affinity API key.
        name: Organization name.
        domain: Website domain (e.g., "acmerobotics.com"). Optional.

    Returns:
        The newly created organization's ID.
    """
    payload: dict[str, Any] = {"name": name}
    if domain:
        payload["domain"] = domain

    response = _request_with_retry(
        "POST",
        f"{BASE_URL}/organizations",
        api_key,
        json=payload,
    )

    org = response.json()
    org_id = org["id"]
    logger.info(f"Created new organization: {org_id} ({name})")
    return org_id


def resolve_or_create_organization(
    api_key: str,
    name: str,
    domain: str = "",
) -> int:
    """
    Find an existing organization by name, or create a new one.

    Returns:
        The organization ID (existing or newly created).
    """
    org_id = search_organization_by_name(api_key, name)
    if org_id:
        return org_id
    return create_organization(api_key, name, domain)


# ── List Entries & Field Values ───────────────────────────────────────────


def create_list_entry(
    api_key: str,
    list_id: int,
    entity_id: int,
) -> int:
    """
    Create a new list entry in the specified Affinity list.

    Args:
        api_key: Affinity API key.
        list_id: The numeric ID of the Affinity list.
        entity_id: The ID of the entity (organization) to add.

    Returns:
        The newly created list entry ID.
    """
    payload = {
        "entity_id": entity_id,
    }

    response = _request_with_retry(
        "POST",
        f"{BASE_URL}/lists/{list_id}/list-entries",
        api_key,
        json=payload,
    )

    entry = response.json()
    entry_id = entry["id"]
    logger.info(f"Created list entry: {entry_id} in list {list_id}")
    return entry_id


def set_field_value(
    api_key: str,
    field_id: int,
    entity_id: int,
    list_entry_id: int,
    value: Any,
) -> None:
    """
    Set a single field value on a list entry.

    Args:
        api_key: Affinity API key.
        field_id: The numeric ID of the field.
        entity_id: The ID of the entity (organization) the entry belongs to.
        list_entry_id: The ID of the list entry.
        value: The value to set. Type depends on the field
               (string, number, date string, dropdown value, etc.).
    """
    if value is None or value == "":
        return  # Skip empty values

    payload = {
        "field_id": field_id,
        "entity_id": entity_id,
        "list_entry_id": list_entry_id,
        "value": value,
    }

    _request_with_retry(
        "POST",
        f"{BASE_URL}/field-values",
        api_key,
        json=payload,
    )

    logger.info(f"Set field {field_id} = '{str(value)[:50]}...' on entry {list_entry_id}")


def set_all_field_values(
    api_key: str,
    list_entry_id: int,
    entity_id: int,
    form_data: dict[str, Any],
    sas_url: str,
    field_ids: dict[str, int],
) -> None:
    """
    Set all field values on a list entry from the validated form data.

    Args:
        api_key: Affinity API key.
        list_entry_id: The list entry ID.
        entity_id: The organization entity ID.
        form_data: Validated form data dictionary.
        sas_url: The SAS URL for the uploaded pitch deck.
        field_ids: Dictionary mapping field setting names to numeric IDs.
                   e.g., {"STATUS": 123, "SOURCE_OF_DEAL": 456, ...}
    """
    from datetime import datetime, timezone

    # Build the field-value mapping
    # Each tuple: (field_ids key suffix, value)
    field_mappings: list[tuple[str, Any]] = [
        ("STATUS", "New"),
        ("SOURCE_OF_DEAL", "Website Pitch Intake Form"),
        ("PRIORITY_SECTOR", form_data.get("sector")),
        ("EXECUTIVE_SUMMARY", form_data.get("executive_summary")),
        ("CORPORATE_ENTITY_STATUS", form_data.get("corporate_entity")),
        ("DATE_OF_INCORPORATION", form_data.get("date_of_incorporation")),
        ("CURRENTLY_RAISING_CAPITAL", form_data.get("raising_capital")),
        ("FINANCING_AMOUNT", form_data.get("financing_amount")),
        ("CURRENT_INVESTORS", form_data.get("current_investors")),
        ("IP_DEPENDENCY", form_data.get("ip_reliance")),
        ("IP_OWNERSHIP_DETAILS", form_data.get("ip_ownership_details")),
        ("PITCH_DECK_URL", sas_url),
        ("SUBMISSION_DATE", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
    ]

    for field_key, value in field_mappings:
        field_id_str = field_ids.get(field_key)
        if not field_id_str:
            logger.warning(f"No field ID configured for {field_key}. Skipping.")
            continue

        try:
            field_id = int(field_id_str)
        except (ValueError, TypeError):
            logger.warning(
                f"Invalid field ID for {field_key}: '{field_id_str}'. Skipping."
            )
            continue

        try:
            set_field_value(api_key, field_id, entity_id, list_entry_id, value)
        except Exception as e:
            logger.error(
                f"Failed to set field {field_key} (ID: {field_id}): {e}. Continuing..."
            )
            # Continue setting other fields — don't fail the entire submission
            # over a single field value error


# ── Entity File Upload ────────────────────────────────────────────────────


def upload_entity_file(
    api_key: str,
    organization_id: int,
    file_content: bytes,
    filename: str,
) -> bool:
    """
    Upload a file to an organization entity in Affinity using the Entity Files API (v1).
    This makes the file visible on the organization's profile in the Affinity UI.

    Args:
        api_key: Affinity API key.
        organization_id: The Affinity organization ID to attach the file to.
        file_content: Raw bytes of the file.
        filename: The filename to use for the upload.

    Returns:
        True if upload succeeded, False otherwise.
    """
    try:
        response = _request_with_retry(
            "POST",
            f"{BASE_URL}/entity-files",
            api_key,
            files={"file": (filename, file_content)},
            data={"organization_id": organization_id},
        )

        result = response.json()
        if result.get("success"):
            logger.info(
                f"Entity file uploaded to organization {organization_id}: {filename}"
            )
            return True
        else:
            logger.warning(
                f"Entity file upload returned unexpected result: {result}"
            )
            return False

    except Exception as e:
        logger.error(
            f"Entity file upload failed for organization {organization_id}: {e}. "
            f"Non-critical — pitch deck is still accessible via Blob Storage SAS URL."
        )
        return False