"""
storage_client.py
Azure Storage helper functions for Blob, Table, and Queue operations.
Handles submission archiving, duplicate detection, and dead-letter queue.
"""

import hashlib
import json
import logging

from datetime import datetime, timedelta, timezone
from typing import Any
from azure.data.tables import TableClient
from azure.storage.blob import BlobServiceClient
from azure.storage.queue import QueueClient
from slugify import slugify

logger = logging.getLogger(__name__)


# ── Blob Storage (Submission Archive) ─────────────────────────────────────


def archive_submission(
    connection_string: str,
    container_name: str,
    submission_id: str,
    form_data: dict[str, Any],
) -> str:
    """
    Archive the complete raw form submission as a JSON file in Blob Storage.
    This happens FIRST, before any CRM operations, to ensure no data is ever lost.

    Args:
        connection_string: Azure Storage connection string.
        container_name: Name of the submissions container (e.g., "submissions").
        submission_id: Unique ID for this submission (UUID).
        form_data: Validated form data dictionary.

    Returns:
        The blob path of the archived JSON file.
    """
    now = datetime.now(timezone.utc)
    date_folder = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    business_slug = slugify(form_data.get("business_name", "unknown"))

    blob_path = f"{date_folder}/{timestamp}_{business_slug}.json"

    archive_data = {
        "submission_id": submission_id,
        "submitted_at": now.isoformat(),
        "form_data": form_data,
        "processing_status": "pending",
        "affinity_ids": {
            "person_id": None,
            "organization_id": None,
            "list_entry_id": None,
        },
    }

    blob_service = BlobServiceClient.from_connection_string(connection_string)
    blob_client = blob_service.get_blob_client(
        container=container_name, blob=blob_path
    )
    blob_client.upload_blob(
        json.dumps(archive_data, indent=2, default=str),
        content_type="application/json",
        overwrite=True,
    )

    logger.info(f"Submission archived: {container_name}/{blob_path}")
    return blob_path


def update_archive(
    connection_string: str,
    container_name: str,
    blob_path: str,
    updates: dict[str, Any],
) -> None:
    """
    Update the archived submission JSON with processing results.

    Args:
        connection_string: Azure Storage connection string.
        container_name: Name of the submissions container.
        blob_path: Path to the existing archive blob.
        updates: Dictionary of fields to merge into the archive JSON.
    """
    try:
        blob_service = BlobServiceClient.from_connection_string(connection_string)
        blob_client = blob_service.get_blob_client(
            container=container_name, blob=blob_path
        )

        existing = json.loads(blob_client.download_blob().readall())

        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(existing.get(key), dict):
                existing[key].update(value)
            else:
                existing[key] = value

        blob_client.upload_blob(
            json.dumps(existing, indent=2, default=str),
            content_type="application/json",
            overwrite=True,
        )
        logger.info(f"Submission archive updated: {blob_path}")

    except Exception as e:
        logger.error(f"Failed to update archive {blob_path}: {e}")


# ── Table Storage (Dedup) ─────────────────────────────────────────────────


def check_duplicate(
    connection_string: str,
    table_name: str,
    email: str,
    business_name: str,
    window_seconds: int = 60,
) -> bool:
    """
    Check if a duplicate submission exists within the time window.
    Uses a hash of (email + business_name) as the fingerprint.

    Returns:
        True if a duplicate exists (submission should be rejected), False otherwise.
    """
    fingerprint = hashlib.sha256(
        f"{email.lower().strip()}|{business_name.lower().strip()}".encode()
    ).hexdigest()[:32]

    table_client = TableClient.from_connection_string(
        connection_string, table_name=table_name
    )

    partition_key = fingerprint
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)

    try:
        entities = table_client.query_entities(
            query_filter=f"PartitionKey eq '{partition_key}'",
            select=["PartitionKey", "RowKey", "Timestamp"],
        )

        for entity in entities:
            entity_time = entity.get("Timestamp")
            if entity_time and entity_time >= cutoff:
                logger.warning(
                    f"Duplicate submission detected for fingerprint {fingerprint[:8]}..."
                )
                return True

    except Exception as e:
        logger.error(f"Dedup check failed: {e}. Allowing submission to proceed.")
        return False

    return False


def record_submission_fingerprint(
    connection_string: str,
    table_name: str,
    email: str,
    business_name: str,
    submission_id: str,
) -> None:
    """
    Record a submission fingerprint in Table Storage for future dedup checks.
    """
    fingerprint = hashlib.sha256(
        f"{email.lower().strip()}|{business_name.lower().strip()}".encode()
    ).hexdigest()[:32]

    timestamp_key = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    table_client = TableClient.from_connection_string(
        connection_string, table_name=table_name
    )

    entity = {
        "PartitionKey": fingerprint,
        "RowKey": timestamp_key,
        "SubmissionId": submission_id,
        "Email": email,
        "BusinessName": business_name,
    }

    try:
        table_client.create_entity(entity)
        logger.info(f"Dedup fingerprint recorded: {fingerprint[:8]}...")
    except Exception as e:
        logger.error(f"Failed to record dedup fingerprint: {e}")


# ── Queue Storage (Dead-Letter) ───────────────────────────────────────────


def send_to_deadletter(
    connection_string: str,
    queue_name: str,
    submission_id: str,
    archive_blob_path: str,
    error_message: str,
    failed_step: str,
) -> None:
    """
    Send a failed submission to the dead-letter queue for manual retry.
    """
    message = {
        "submission_id": submission_id,
        "archive_blob_path": archive_blob_path,
        "error_message": str(error_message),
        "failed_step": failed_step,
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        queue_client = QueueClient.from_connection_string(
            connection_string, queue_name=queue_name
        )
        queue_client.send_message(json.dumps(message))
        logger.info(
            f"Submission {submission_id} sent to dead-letter queue. "
            f"Failed step: {failed_step}"
        )
    except Exception as e:
        logger.critical(
            f"CRITICAL: Failed to send to dead-letter queue: {e}. "
            f"Submission {submission_id} may be lost. "
            f"Archive blob: {archive_blob_path}"
        )