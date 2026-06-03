# tools/cleanup_subscriptions.py
import os, requests
from azure.identity import ClientSecretCredential
from dotenv import load_dotenv

load_dotenv(".env.register")

credential = ClientSecretCredential(
    tenant_id=os.environ["AZURE_TENANT_ID"],
    client_id=os.environ["AZURE_CLIENT_ID"],
    client_secret=os.environ["AZURE_CLIENT_SECRET"],
)
token = credential.get_token("https://graph.microsoft.com/.default").token
headers = {"Authorization": f"Bearer {token}"}

# List all subscriptions
resp = requests.get("https://graph.microsoft.com/v1.0/subscriptions", headers=headers)
subs = resp.json().get("value", [])
print(f"Found {len(subs)} subscription(s):")
for s in subs:
    print(f"  {s['id']} | resource: {s['resource']} | expiry: {s['expirationDateTime']}")

# Delete all of them — register_subscription.py will create a clean one after
for s in subs:
    requests.delete(f"https://graph.microsoft.com/v1.0/subscriptions/{s['id']}", headers=headers)
    print(f"  Deleted {s['id']}")