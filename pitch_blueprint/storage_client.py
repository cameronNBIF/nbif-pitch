"""
storage_client.py
Azure Storage helper functions for Blob, Table, and Queue operations.
Handles submission archiving, pitch deck upload, SAS URL generation,
duplicate detection, and dead-letter queue.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from azure.data.tables import TableClient, TableServiceClient
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    generate_blob_sas,
)
from azure.storage.queue import QueueClient
from slugify import slugify

logger = logging.getLogger(__name__)


# ── Blob Storage ──────────────────────────────────────────────────────────


def archive_submission(
    connection_string: str,
    container_name: str,
    submission_id: str,
    form_data: dict[str, Any],
    file_info: dict[str, Any],
) -> str:
    """
    Archive the complete raw form submission as a JSON file in Blob Storage.
    This happens FIRST, before any CRM operations, to ensure no data is ever lost.

    Args:
        connection_string: Azure Storage connection string.
        container_name: Name of the submissions container (e.g., "submissions").
        submission_id: Unique ID for this submission (UUID).
        form_data: Validated form data dictionary.
        file_info: File metadata (filename, size, content_type — not the file content).

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
        "pitch_deck": {
            "original_filename": file_info.get("filename", ""),
            "file_size_bytes": file_info.get("size_bytes", 0),
            "content_type": file_info.get("content_type", ""),
            "blob_path": "",  # Will be updated after upload
            "blob_url": "",
            "sas_url": "",
        },
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

        # Download current content
        existing = json.loads(blob_client.download_blob().readall())

        # Deep merge updates
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(existing.get(key), dict):
                existing[key].update(value)
            else:
                existing[key] = value

        # Re-upload
        blob_client.upload_blob(
            json.dumps(existing, indent=2, default=str),
            content_type="application/json",
            overwrite=True,
        )

        logger.info(f"Submission archive updated: {blob_path}")

    except Exception as e:
        logger.error(f"Failed to update archive {blob_path}: {e}")
        # Non-critical — don't raise


def upload_pitch_deck(
    connection_string: str,
    container_name: str,
    file_content: bytes,
    original_filename: str,
    business_name: str,
    content_type: str = "application/octet-stream",
) -> tuple[str, str]:
    """
    Upload the pitch deck file to Blob Storage.

    Args:
        connection_string: Azure Storage connection string.
        container_name: Name of the pitch-decks container.
        file_content: Raw bytes of the pitch deck file.
        original_filename: The original filename from the form upload.
        business_name: The business name (used to create the folder path).
        content_type: MIME type of the file.

    Returns:
        Tuple of (blob_path, blob_url) where blob_url is the direct URL
        (without SAS — use generate_sas_url() for access-controlled URLs).
    """
    business_slug = slugify(business_name)
    date_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Sanitize filename: keep only the extension, prepend with date
    ext = ""
    if "." in original_filename:
        ext = "." + original_filename.rsplit(".", 1)[-1].lower()
    safe_filename = f"{date_prefix}_{slugify(original_filename.rsplit('.', 1)[0])}{ext}"

    blob_path = f"{business_slug}/{safe_filename}"

    blob_service = BlobServiceClient.from_connection_string(connection_string)
    blob_client = blob_service.get_blob_client(
        container=container_name, blob=blob_path
    )
    blob_client.upload_blob(
        file_content,
        content_type=content_type,
        overwrite=True,
    )

    blob_url = blob_client.url

    logger.info(
        f"Pitch deck uploaded: {container_name}/{blob_path} "
        f"({len(file_content)} bytes)"
    )
    return blob_path, blob_url


def generate_sas_url(
    connection_string: str,
    container_name: str,
    blob_path: str,
    expiry_days: int = 365,
) -> str:
    """
    Generate a read-only SAS URL for a blob.

    Args:
        connection_string: Azure Storage connection string.
        container_name: Container name.
        blob_path: Path to the blob within the container.
        expiry_days: Number of days until the SAS URL expires (default: 1 year).

    Returns:
        Full SAS URL string that grants read-only access to the blob.
    """
    blob_service = BlobServiceClient.from_connection_string(connection_string)
    account_name = blob_service.account_name

    # Extract account key from connection string
    parts = dict(
        item.split("=", 1) for item in connection_string.split(";") if "=" in item
    )
    account_key = parts.get("AccountKey", "")

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container_name,
        blob_name=blob_path,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(days=expiry_days),
    )

    sas_url = f"https://{account_name}.blob.core.windows.net/{container_name}/{blob_path}?{sas_token}"

    logger.info(
        f"SAS URL generated for {container_name}/{blob_path} "
        f"(expires in {expiry_days} days)"
    )
    return sas_url


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

    Args:
        connection_string: Azure Storage connection string.
        table_name: Name of the dedup table.
        email: Submitter's email address.
        business_name: Business name from the form.
        window_seconds: Time window in seconds to consider duplicates.

    Returns:
        True if a duplicate exists (submission should be rejected), False otherwise.
    """
    fingerprint = hashlib.sha256(
        f"{email.lower().strip()}|{business_name.lower().strip()}".encode()
    ).hexdigest()[:32]

    table_client = TableClient.from_connection_string(
        connection_string, table_name=table_name
    )

    # Use the fingerprint as PartitionKey and a date prefix as RowKey
    # to allow efficient querying
    partition_key = fingerprint
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)

    try:
        # Query for recent entries with this fingerprint
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
        # If dedup check fails, allow the submission (fail-open)
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

    Args:
        connection_string: Azure Storage connection string.
        table_name: Name of the dedup table.
        email: Submitter's email address.
        business_name: Business name from the form.
        submission_id: Unique submission ID.
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
        # Non-critical — don't raise


# ── Queue Storage (Dead-Letter) ───────────────────────────────────────────


def send_to_deadletter(
    connection_string: str,
    queue_name: str,
    submission_id: str,
    archive_blob_path: str,
    deck_blob_path: str,
    error_message: str,
    failed_step: str,
) -> None:
    """
    Send a failed submission to the dead-letter queue for manual retry.

    Args:
        connection_string: Azure Storage connection string.
        queue_name: Name of the dead-letter queue.
        submission_id: Unique submission ID.
        archive_blob_path: Path to the archived JSON submission in Blob Storage.
        deck_blob_path: Path to the uploaded pitch deck in Blob Storage.
        error_message: Description of the error that occurred.
        failed_step: The pipeline step where the failure occurred.
    """
    message = {
        "submission_id": submission_id,
        "archive_blob_path": archive_blob_path,
        "deck_blob_path": deck_blob_path,
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