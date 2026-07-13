"""
affinity_client.py
Affinity CRM API helper functions for the Pitch Intake Form.

This is an ORGANIZATION list:
  - The Organization is the entity on the list entry
  - Contact info (email, phone) are text fields on the list entry
  - Dropdown fields (Priority Sector, Venture Stage) require numeric option IDs

Write semantics:
  - Global + list-specific text/dropdown/number/date fields use POST /field-values.
    If Affinity already has a value on that (entity, field) pair, the POST returns
    422 with "already exists" - we treat that as a normal skip (Affinity is the
    source of truth; we never overwrite values the VC team may have edited).
  - Ranked dropdowns (Status) are auto-populated by Affinity the moment a list
    entry is created, so a POST always 422s. For Status we do GET → find the
    auto-populated field value → PUT its ID with the desired option ID.

Authentication: Basic auth with empty username and API key as password.
"""

import logging
import os
import functools
import requests

from typing import Any, Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("AFFINITY_BASE_URL") or "https://api.affinity.co"

# ── Auth & HTTP ───────────────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def get_affinity_session(api_key: str) -> requests.Session:
    """
    Creates and caches an HTTP session for Affinity API.
    Maintains a connection pool and automatically handles retries with exponential backoff.
    """
    session = requests.Session()
    session.auth = ("", api_key)

    # Retry on 429 (Rate Limit) and 5xx server errors
    retries = Retry(
        total=3,
        backoff_factor=2,  # Waits 2, 4, 8 seconds
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS", "POST", "PUT", "DELETE"],
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    logger.info("Initialized new Affinity HTTP Session with connection pooling.")
    return session


def _is_already_exists_error(response: requests.Response) -> bool:
    """
    True if Affinity returned a 422 because the field value already exists on
    that (entity, field) pair. Affinity phrases the error like:
        ["Field value on field 5763309 for 299500304 already exists."]
    """
    if response.status_code != 422:
        return False
    return "already exists" in response.text


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
    """
    session = get_affinity_session(api_key)

    resp = session.request(
        "GET", f"{BASE_URL}/persons", params={"term": email}, timeout=30
    )
    resp.raise_for_status()

    data = resp.json()
    person_list = data.get("persons", data) if isinstance(data, dict) else data

    for person in person_list:
        person_emails = [e.lower() for e in person.get("emails", [])]
        if email.lower().strip() in person_emails:
            person_id = person["id"]
            logger.info(f"Found existing person: {person_id} ({email})")
            return person_id

    # Not found — create
    resp = session.request(
        "POST",
        f"{BASE_URL}/persons",
        json={
            "first_name": first_name,
            "last_name": last_name,
            "emails": [email],
        },
        timeout=30,
    )
    resp.raise_for_status()

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
    session = get_affinity_session(api_key)

    resp = session.request(
        "GET", f"{BASE_URL}/organizations", params={"term": name}, timeout=30
    )
    resp.raise_for_status()

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

    resp = session.request(
        "POST", f"{BASE_URL}/organizations", json=payload, timeout=30
    )
    resp.raise_for_status()

    org_id = resp.json()["id"]
    logger.info(f"Created new organization: {org_id} ({name})")
    return org_id


# ── List Entry & Field Values ─────────────────────────────────────────────


def create_list_entry(api_key: str, list_id: int, entity_id: int) -> int:
    """
    Add an Organization to the list. Returns the list entry ID.
    """
    session = get_affinity_session(api_key)

    resp = session.request(
        "POST",
        f"{BASE_URL}/lists/{list_id}/list-entries",
        json={"entity_id": entity_id},
        timeout=30,
    )
    resp.raise_for_status()

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
    Set a field value on a LIST-SPECIFIC field via POST.
    If the value already exists on that (entity, field) pair, we skip — Affinity
    is treated as the source of truth so we never overwrite VC team edits.
    Not appropriate for ranked dropdowns like Status; use upsert_ranked_dropdown.
    """
    if value is None or value == "":
        return

    payload = {
        "field_id": int(field_id),
        "entity_id": entity_id,
        "list_entry_id": list_entry_id,
        "value": value,
    }

    logger.debug(f"Setting LIST-SPECIFIC field: {payload}")

    session = get_affinity_session(api_key)
    response = session.request(
        "POST", f"{BASE_URL}/field-values", json=payload, timeout=30
    )

    if _is_already_exists_error(response):
        logger.info(
            f"List field {field_id} on entry {list_entry_id} already has a "
            f"value — skipping (Affinity is source of truth)."
        )
        return

    if not response.ok:
        logger.error(
            f"Affinity field-values write failed: {response.status_code} "
            f"payload={payload} body={response.text}"
        )
        response.raise_for_status()

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
    Set a field value on a GLOBAL field via POST.
    Does NOT include list_entry_id — global fields live on the entity itself.
    Same skip-if-exists semantics as set_field_value.
    """
    if value is None or value == "":
        return

    payload = {
        "field_id": int(field_id),
        "entity_id": entity_id,
        "value": value,
    }

    logger.debug(f"Setting GLOBAL field: {payload}")

    session = get_affinity_session(api_key)
    response = session.request(
        "POST", f"{BASE_URL}/field-values", json=payload, timeout=30
    )

    if _is_already_exists_error(response):
        logger.info(
            f"Global field {field_id} on entity {entity_id} already has a "
            f"value — skipping (Affinity is source of truth)."
        )
        return

    if not response.ok:
        logger.error(
            f"Affinity field-values write failed: {response.status_code} "
            f"payload={payload} body={response.text}"
        )
        response.raise_for_status()

    logger.info(
        f"Set global field {field_id} = '{str(value)[:80]}' on entity {entity_id}"
    )


def upsert_ranked_dropdown(
    api_key: str,
    entity_id: int,
    list_entry_id: int,
    field_id: int,
    option_id: int,
) -> None:
    """
    Upsert a ranked-dropdown field value (like Status) on a list entry.

    Ranked dropdowns are auto-populated by Affinity when a list entry is
    created (Status defaults to its first-ranked option, e.g. "New"), so a
    plain POST always 422s with "already exists". This function does:
        1. GET /field-values?list_entry_id=... to find the auto-populated fv
        2. PUT /field-values/{fv_id} with the desired option ID
    If no existing field value is found (shouldn't happen for Status but is
    handled defensively), falls back to POST.
    """
    session = get_affinity_session(api_key)

    # 1. GET existing field values on this list entry
    get_resp = session.request(
        "GET",
        f"{BASE_URL}/field-values",
        params={"list_entry_id": list_entry_id},
        timeout=30,
    )
    if not get_resp.ok:
        logger.error(
            f"Affinity field-values GET failed: {get_resp.status_code} "
            f"list_entry_id={list_entry_id} body={get_resp.text}"
        )
        get_resp.raise_for_status()

    existing_fv: Optional[dict[str, Any]] = next(
        (fv for fv in get_resp.json() if fv.get("field_id") == field_id),
        None,
    )

    # 2. PUT if it exists, else POST
    if existing_fv:
        fv_id = existing_fv["id"]
        put_resp = session.request(
            "PUT",
            f"{BASE_URL}/field-values/{fv_id}",
            json={"value": option_id},
            timeout=30,
        )
        if not put_resp.ok:
            logger.error(
                f"Affinity ranked-dropdown PUT failed: {put_resp.status_code} "
                f"field_value_id={fv_id} option_id={option_id} "
                f"body={put_resp.text}"
            )
            put_resp.raise_for_status()
        logger.info(
            f"Updated ranked field {field_id} -> option {option_id} on entry "
            f"{list_entry_id} (field_value_id={fv_id})"
        )
        return

    # Defensive fallback: no existing value, create one
    payload = {
        "field_id": field_id,
        "entity_id": entity_id,
        "list_entry_id": list_entry_id,
        "value": option_id,
    }
    post_resp = session.request(
        "POST", f"{BASE_URL}/field-values", json=payload, timeout=30
    )
    if not post_resp.ok:
        logger.error(
            f"Affinity ranked-dropdown POST fallback failed: "
            f"{post_resp.status_code} payload={payload} body={post_resp.text}"
        )
        post_resp.raise_for_status()
    logger.info(
        f"Created ranked field {field_id} = option {option_id} on entry "
        f"{list_entry_id}"
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
    Skip-if-exists on everything except Status, which is always upserted to
    "Intake" so form-sourced entries land in the Intake view for VC triage.
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
        logger.debug(
            f"GLOBAL {env_key} -> field_id={field_id}, value={str(value)[:80]}"
        )
        if not field_id:
            logger.debug(f"SKIPPED - env var {env_key} not found")
            return
        try:
            set_global_field_value(api_key, org_id, field_id, value)
        except Exception as e:
            logger.error(f"FAIL (global) - {env_key}: {type(e).__name__}: {e}")

    def _set_list(env_key: str, value: Any) -> None:
        """Set a LIST-SPECIFIC field value (includes list_entry_id)."""
        field_id = os.environ.get(env_key)
        logger.debug(f"LIST {env_key} -> field_id={field_id}, value={str(value)[:80]}")
        if not field_id:
            logger.debug(f"SKIPPED - env var {env_key} not found")
            return
        try:
            set_field_value(api_key, org_id, list_entry_id, field_id, value)
        except Exception as e:
            logger.error(f"FAIL (list) - {env_key}: {type(e).__name__}: {e}")

    def _upsert_ranked(field_env_key: str, option_env_key: str) -> None:
        """Upsert a ranked-dropdown field (Status) on the list entry."""
        field_id = os.environ.get(field_env_key)
        option_id = os.environ.get(option_env_key)
        if not field_id or not option_id:
            logger.warning(
                f"{field_env_key} or {option_env_key} not set. Skipping ranked upsert."
            )
            return
        try:
            upsert_ranked_dropdown(
                api_key, org_id, list_entry_id, int(field_id), int(option_id)
            )
        except Exception as e:
            logger.error(
                f"FAIL (ranked) - {field_env_key}: {type(e).__name__}: {e}"
            )

    logger.debug(f"=== POPULATING FIELDS FOR ENTRY {list_entry_id} ===")
    logger.debug(f"org_id={org_id}, person_id={person_id}")

    # ==================================================================
    # LIST-SPECIFIC RANKED DROPDOWN (Status)
    # Always upserted so form submissions land in the Intake view.
    # ==================================================================

    _upsert_ranked("AFFINITY_FIELD_ID_STATUS", "AFFINITY_STATUS_INTAKE")

    # ==================================================================
    # GLOBAL FIELDS (no list_entry_id) — skip if already set
    # ==================================================================

    _set_global("AFFINITY_FIELD_ID_CONTACT", person_id)
    _set_global("AFFINITY_FIELD_ID_CONTACT_EMAIL", form_data.get("email", ""))
    _set_global("AFFINITY_FIELD_ID_CONTACT_PHONE_NUMBER", form_data.get("phone", ""))

    sector = form_data.get("sector", "")
    if sector:
        _set_global("AFFINITY_FIELD_ID_PRIORITY_SECTOR", sector)

    company_problem = form_data.get("company_problem", "")
    if company_problem:
        _set_global("AFFINITY_FIELD_ID_COMPANY_PROBLEM", company_problem)

    company_solution = form_data.get("company_solution", "")
    if company_solution:
        _set_global("AFFINITY_FIELD_ID_COMPANY_SOLUTION", company_solution)

    company_progress = form_data.get("company_progress", "")
    if company_progress:
        _set_global("AFFINITY_FIELD_ID_COMPANY_PROGRESS", company_progress)

    venture_stage = form_data.get("venture_stage", "")
    if venture_stage:
        affinity_label = VENTURE_STAGE_MAP.get(venture_stage, venture_stage)
        _set_global("AFFINITY_FIELD_ID_VENTURE_STAGE", affinity_label)

    date_val = form_data.get("date_of_incorporation", "")
    if date_val:
        _set_global("AFFINITY_FIELD_ID_DATE_OF_INCORPORATION", date_val)

    discovery = form_data.get("discovery", "")
    if discovery:
        _set_global("AFFINITY_FIELD_ID_DISCOVERY", discovery)

    accelerators = form_data.get("accelerators", "")
    if accelerators:
        _set_global("AFFINITY_FIELD_ID_ACCELERATORS", accelerators)

    # ==================================================================
    # LIST-SPECIFIC FIELDS (includes list_entry_id) — skip if already set
    # ==================================================================

    round_size = form_data.get("investment_round_size")
    if round_size is not None:
        _set_list("AFFINITY_FIELD_ID_INVESTMENT_ROUND_SIZE", round_size)

    potential_amount = form_data.get("potential_investment_amount")
    if potential_amount is not None:
        _set_list("AFFINITY_FIELD_ID_POTENTIAL_INVESTMENT_AMOUNT", potential_amount)

    logger.info(f"All field values populated on entry {list_entry_id}")