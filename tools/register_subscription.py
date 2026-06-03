"""
One-time script to register the Microsoft Graph webhook subscription
for the info@nbif.ca inbox and store the subscription ID in Table Storage.

Run this from your local machine with the virtual environment activated:
    python register_subscription.py

Re-run it if the subscription ever expires and needs to be re-created.
"""

import os
import json
import requests
from datetime import datetime, timezone, timedelta
from azure.identity import ClientSecretCredential
from azure.data.tables import TableClient
from dotenv import load_dotenv  # reads from local.settings.json equivalent

# ── Load config from environment ──────────────────────────────────────────────
# Populate these from your local.settings.json values before running.
# Never hardcode secrets in this file.

load_dotenv(".env.register")   # see note below on creating this file

AZURE_CLIENT_ID           = os.environ["AZURE_CLIENT_ID"]
AZURE_TENANT_ID           = os.environ["AZURE_TENANT_ID"]
AZURE_CLIENT_SECRET       = os.environ["AZURE_CLIENT_SECRET"]
GRAPH_USER_EMAIL          = os.environ["GRAPH_USER_EMAIL"]
GRAPH_WEBHOOK_SECRET      = os.environ["GRAPH_WEBHOOK_SECRET"]
STORAGE_CONNECTION_STRING = os.environ["STORAGE_CONNECTION_STRING"]
STORAGE_TABLE_NAME        = os.environ["STORAGE_TABLE_NAME"]
NOTIFICATION_URL          = os.environ["NOTIFICATION_URL"]   # full URL with ?code=

# ── Acquire Graph token ───────────────────────────────────────────────────────

credential = ClientSecretCredential(
    tenant_id=AZURE_TENANT_ID,
    client_id=AZURE_CLIENT_ID,
    client_secret=AZURE_CLIENT_SECRET,
)
token = credential.get_token("https://graph.microsoft.com/.default").token
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# ── Register the subscription ─────────────────────────────────────────────────

expiry = (datetime.now(timezone.utc) + timedelta(days=3)).strftime(
    "%Y-%m-%dT%H:%M:%S.000Z"
)

payload = {
    "changeType":          "created",
    "notificationUrl":     NOTIFICATION_URL,
    "resource":            f"users/{GRAPH_USER_EMAIL}/mailFolders/Inbox/messages",
    "expirationDateTime":  expiry,
    "clientState":         GRAPH_WEBHOOK_SECRET,
}

print("Registering subscription...")
resp = requests.post(
    "https://graph.microsoft.com/v1.0/subscriptions",
    json=payload,
    headers=headers,
)

if not resp.ok:
    print(f"Registration failed: {resp.status_code}")
    print(resp.text)
    exit(1)

subscription = resp.json()
subscription_id = subscription["id"]
print(f"Subscription registered successfully.")
print(f"  ID:      {subscription_id}")
print(f"  Expiry:  {subscription['expirationDateTime']}")

# ── Store the subscription ID in Table Storage ────────────────────────────────
# The renewSubscription Azure Function reads this row on every run.

table_client = TableClient.from_connection_string(
    conn_str=STORAGE_CONNECTION_STRING,
    table_name=STORAGE_TABLE_NAME,
)
table_client.upsert_entity({
    "PartitionKey": "nbif",
    "RowKey":       "graph_subscription_id",
    "Value":        subscription_id,
})

print(f"Subscription ID written to Table Storage.")