"""
affinity_client.py
Affinity CRM API helper functions for the Pitch Intake Form.

This is an ORGANIZATION list:
  - The Organization is the entity on the list entry
  - Contact info (email, phone) are text fields on the list entry
  - Dropdown fields (Priority Sector, Venture Stage) require numeric option IDs

API Reference: https://api-docs.affinity.co/
Authentication: Basic auth with empty username and API key as password.
"""

import logging
import os
import time
import requests

from typing import Any

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("AFFINITY_BASE_URL") or "https://api.affinity.co"

MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 2


# ── Auth & HTTP ───────────────────────────────────────────────────────────


def _auth(api_key: str) -> tuple[str, str]:
    """Affinity Basic Auth: empty username, API key as password."""
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
    Does NOT retry on 4xx errors (except 429 rate limit).
    """
    last_exception = None

    for attempt in range(retries + 1):
        try:
            response = requests.request(
                method, url, auth=_auth(api_key), timeout=30, **kwargs
            )
            response.raise_for_status()
            return response

        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else 0

            if 400 <= status_code < 500 and status_code != 429:
                logger.error(
                    f"Affinity API {status_code}: {method} {url} — "
                    f"{e.response.text[:500] if e.response else 'N/A'}"
                )
                raise

            last_exception = e
            if attempt < retries:
                wait = RETRY_BACKOFF_SECONDS * (2 ** attempt)
                logger.warning(
                    f"Affinity API error (attempt {attempt + 1}/{retries + 1}): "
                    f"{status_code}. Retrying in {wait}s..."
                )
                time.sleep(wait)

        except requests.RequestException as e:
            last_exception = e
            if attempt < retries:
                wait = RETRY_BACKOFF_SECONDS * (2 ** attempt)
                logger.warning(
                    f"Affinity request error (attempt {attempt + 1}/{retries + 1}): "
                    f"{e}. Retrying in {wait}s..."
                )
                time.sleep(wait)

    raise last_exception  # type: ignore[misc]


# ── Persons ───────────────────────────────────────────────────────────────


def resolve_or_create_person(
    api_key: str,
    first_name: str,
    last_name: str,
    email: str,
) -> int:
    """
    Find an existing Person by email, or create a new one.
    Returns the person ID.

    Note: The Person is NOT the entity on the list entry (that's the Org).
    The Person is created so it exists in Affinity's global person database
    and can be linked manually or via future automation.
    """
    resp = _request_with_retry(
        "GET", f"{BASE_URL}/persons", api_key, params={"term": email}
    )
    data = resp.json()
    person_list = data.get("persons", data) if isinstance(data, dict) else data

    for person in person_list:
        person_emails = [e.lower() for e in person.get("emails", [])]
        if email.lower().strip() in person_emails:
            person_id = person["id"]
            logger.info(f"Found existing person: {person_id} ({email})")
            return person_id

    # Not found — create
    resp = _request_with_retry(
        "POST",
        f"{BASE_URL}/persons",
        api_key,
        json={
            "first_name": first_name,
            "last_name": last_name,
            "emails": [email],
        },
    )
    person_id = resp.json()["id"]
    logger.info(f"Created new person: {person_id} ({first_name} {last_name})")
    return person_id


# ── Organizations ─────────────────────────────────────────────────────────


def resolve_or_create_organization(
    api_key: str,
    name: str,
    domain: str = "",
) -> int:
    """
    Find an existing Organization by name, or create a new one.
    Returns the organization ID. This is the entity on the list entry.
    """
    resp = _request_with_retry(
        "GET", f"{BASE_URL}/organizations", api_key, params={"term": name}
    )
    data = resp.json()
    org_list = data.get("organizations", data) if isinstance(data, dict) else data

    for org in org_list:
        if org.get("name", "").lower().strip() == name.lower().strip():
            org_id = org["id"]
            logger.info(f"Found existing organization: {org_id} ({name})")
            return org_id

    # Not found — create
    payload: dict[str, Any] = {"name": name}
    if domain:
        payload["domain"] = domain

    resp = _request_with_retry(
        "POST", f"{BASE_URL}/organizations", api_key, json=payload
    )
    org_id = resp.json()["id"]
    logger.info(f"Created new organization: {org_id} ({name})")
    return org_id


# ── List Entry & Field Values ─────────────────────────────────────────────


def create_list_entry(api_key: str, list_id: int, entity_id: int) -> int:
    """
    Add an Organization to the list. Returns the list entry ID.
    """
    resp = _request_with_retry(
        "POST",
        f"{BASE_URL}/lists/{list_id}/list-entries",
        api_key,
        json={"entity_id": entity_id},
    )
    entry_id = resp.json()["id"]
    logger.info(f"Created list entry: {entry_id} in list {list_id}")
    return entry_id


def set_field_value(
    api_key: str,
    entity_id: int,
    list_entry_id: int,
    field_id: str | int,
    value: Any,
) -> None:
    """
    Set a field value on a LIST-SPECIFIC field.
    Includes list_entry_id in the payload.
    """
    if value is None or value == "":
        return

    payload = {
        "field_id": int(field_id),
        "entity_id": entity_id,
        "list_entry_id": list_entry_id,
        "value": value,
    }

    print(f"[DEBUG SET_FIELD] LIST-SPECIFIC: {payload}")

    response = _request_with_retry(
        "POST",
        f"{BASE_URL}/field-values",
        api_key,
        json=payload,
    )

    print(f"[DEBUG SET_FIELD] Response: {response.status_code} - {response.text[:200]}")
    logger.info(
        f"Set list field {field_id} = '{str(value)[:80]}' on entry {list_entry_id}"
    )


def set_global_field_value(
    api_key: str,
    entity_id: int,
    field_id: str | int,
    value: Any,
) -> None:
    """
    Set a field value on a GLOBAL field.
    Does NOT include list_entry_id — global fields live on the entity itself.
    """
    if value is None or value == "":
        return

    payload = {
        "field_id": int(field_id),
        "entity_id": entity_id,
        "value": value,
    }

    print(f"[DEBUG SET_FIELD] GLOBAL: {payload}")

    response = _request_with_retry(
        "POST",
        f"{BASE_URL}/field-values",
        api_key,
        json=payload,
    )

    print(f"[DEBUG SET_FIELD] Response: {response.status_code} - {response.text[:200]}")
    logger.info(
        f"Set global field {field_id} = '{str(value)[:80]}' on entity {entity_id}"
    )


def populate_list_entry(
    api_key: str,
    org_id: int,
    list_entry_id: int,
    person_id: int,
    form_data: dict[str, Any],
) -> None:
    """
    Set all field values on the Pitch Intake list entry.

    GLOBAL fields (no list_entry_id):
      - Contact                      -> person       (5763309) value = person_id (int)
      - Contact (Email)              -> text         (5763310)
      - Contact (Phone Number)       -> text         (5753116)
      - Priority Sector              -> dropdown     (5450487) value = text label
      - Venture Stage                -> dropdown     (5763423) value = text label
      - Date of Incorporation        -> date         (5753155) value = "YYYY-MM-DD"
      - Discovery                    -> text         (5763444)

    LIST-SPECIFIC fields (includes list_entry_id):
      - Investment Round Size        -> number       (5753169)
      - Potential Investment Amount   -> number       (5763414)
    """

    # Mapping from short form values to exact Affinity dropdown labels
    VENTURE_STAGE_MAP = {
        "Series A": "Early customer traction to Multiple customers with revenue & strong adoption - Series A",
        "Research or Lab Stage": "Idea to Proof of Concept - Research or Lab Stage",
        "Seed": "MVP to Early customer traction (Pilots or early revenue) - Seed",
        "Accelerator Stage": "Proof of Concept to Prototype - Accelerator Stage",
        "Pre-seed": "Prototype to MVP (Minimum Viable Product) - Pre-seed",
    }

    def _set_global(env_key: str, value: Any) -> None:
        """Set a GLOBAL field value (no list_entry_id)."""
        field_id = os.environ.get(env_key)
        print(f"[DEBUG FIELD] GLOBAL {env_key} -> field_id={field_id}, value={str(value)[:80]}")
        if not field_id:
            print(f"[DEBUG FIELD] >> SKIPPED - env var {env_key} not found!")
            return
        try:
            set_global_field_value(api_key, org_id, field_id, value)
            print(f"[DEBUG FIELD] >> OK (global)")
        except Exception as e:
            print(f"[DEBUG FIELD] >> FAIL (global) - {env_key}: {type(e).__name__}: {e}")

    def _set_list(env_key: str, value: Any) -> None:
        """Set a LIST-SPECIFIC field value (includes list_entry_id)."""
        field_id = os.environ.get(env_key)
        print(f"[DEBUG FIELD] LIST {env_key} -> field_id={field_id}, value={str(value)[:80]}")
        if not field_id:
            print(f"[DEBUG FIELD] >> SKIPPED - env var {env_key} not found!")
            return
        try:
            set_field_value(api_key, org_id, list_entry_id, field_id, value)
            print(f"[DEBUG FIELD] >> OK (list)")
        except Exception as e:
            print(f"[DEBUG FIELD] >> FAIL (list) - {env_key}: {type(e).__name__}: {e}")

    print(f"[DEBUG] === POPULATING FIELDS FOR ENTRY {list_entry_id} ===")
    print(f"[DEBUG] org_id={org_id}, person_id={person_id}")

    # ==================================================================
    # GLOBAL FIELDS (no list_entry_id)
    # ==================================================================

    # -- Contact (Person) - global, value is person_id as INTEGER
    _set_global("AFFINITY_FIELD_ID_CONTACT", person_id)

    # -- Contact (Email) - global text
    _set_global("AFFINITY_FIELD_ID_CONTACT_EMAIL", form_data.get("email", ""))

    # -- Contact (Phone Number) - global text
    _set_global("AFFINITY_FIELD_ID_CONTACT_PHONE_NUMBER", form_data.get("phone", ""))

    # -- Priority Sector - global dropdown (send text label directly)
    sector = form_data.get("sector", "")
    if sector:
        print(f"[DEBUG DROPDOWN] sector='{sector}' (sending text directly)")
        _set_global("AFFINITY_FIELD_ID_PRIORITY_SECTOR", sector)

    # -- Venture Stage - global dropdown (map short label to full Affinity label)
    venture_stage = form_data.get("venture_stage", "")
    if venture_stage:
        affinity_label = VENTURE_STAGE_MAP.get(venture_stage, venture_stage)
        print(f"[DEBUG DROPDOWN] venture_stage='{venture_stage}' -> affinity_label='{affinity_label}'")
        _set_global("AFFINITY_FIELD_ID_VENTURE_STAGE", affinity_label)

    # -- Date of Incorporation - GLOBAL date
    date_val = form_data.get("date_of_incorporation", "")
    if date_val:
        _set_global("AFFINITY_FIELD_ID_DATE_OF_INCORPORATION", date_val)
    else:
        print(f"[DEBUG FIELD] >> date_of_incorporation is empty, skipping")

    # -- Discovery - global text ("How did you hear about NBIF?")
    discovery = form_data.get("discovery", "")
    if discovery:
        _set_global("AFFINITY_FIELD_ID_DISCOVERY", discovery)

    # ==================================================================
    # LIST-SPECIFIC FIELDS (includes list_entry_id)
    # ==================================================================

    # -- Investment Round Size - list number
    round_size = form_data.get("investment_round_size")
    if round_size is not None:
        _set_list("AFFINITY_FIELD_ID_INVESTMENT_ROUND_SIZE", round_size)

    # -- Potential Investment Amount - list number
    potential_amount = form_data.get("potential_investment_amount")
    if potential_amount is not None:
        _set_list("AFFINITY_FIELD_ID_POTENTIAL_INVESTMENT_AMOUNT", potential_amount)

    # ==================================================================
    # SKIPPED FOR MVP
    # ==================================================================

    # -- Accelerator - Organization multi-value (skipped)
    accelerator = form_data.get("accelerator", "")
    if accelerator:
        print(f"[DEBUG FIELD] Accelerator text (not mapped): '{accelerator[:100]}'")

    print(f"[DEBUG] === FIELD POPULATION COMPLETE ===")
    logger.info(f"All field values populated on entry {list_entry_id}")

def _resolve_dropdown_option_id(form_value: str, env_prefix: str) -> str | None:
    """
    Map a form text value to its Affinity dropdown option ID.
    Returns the option ID as a STRING (Affinity requires string type for dropdowns).
    """
    normalized = (
        form_value.upper()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("&", "AND")
        .replace("/", "_")
    )
    while "__" in normalized:
        normalized = normalized.replace("__", "_")

    # Direct lookup
    env_key = f"{env_prefix}{normalized}"
    option_id = os.environ.get(env_key)
    if option_id:
        return str(option_id)

    # Fallback: scan all env vars with the prefix for a fuzzy match
    for key, value in os.environ.items():
        if key.startswith(env_prefix):
            env_suffix = key[len(env_prefix):]
            if env_suffix == normalized or env_suffix.strip("_") == normalized.strip("_"):
                return str(value)

    logger.warning(
        f"No dropdown option ID found for '{form_value}'. "
        f"Looked for env var: {env_key}"
    )
    return None