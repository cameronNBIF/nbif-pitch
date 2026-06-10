import os
import requests
import json
from dotenv import load_dotenv

# Load config from environment
load_dotenv(".env.register")

AFFINITY_API_KEY = os.environ.get("AFFINITY_API_KEY")
AFFINITY_BASE = "https://api.affinity.co"


def inspect_entry_fields():
    # This is the ID of the list entry you successfully created in your last test
    list_entry_id = 241994794

    print(f"Fetching assigned field values for List Entry ID: {list_entry_id}...\n")

    resp = requests.get(
        f"{AFFINITY_BASE}/field-values",
        params={"list_entry_id": list_entry_id},
        auth=("", AFFINITY_API_KEY),
    )

    resp.raise_for_status()
    values = resp.json()

    print("=== ASSIGNED FIELD VALUES ===")
    print(json.dumps(values, indent=2))
    print("=============================\n")


if __name__ == "__main__":
    if not AFFINITY_API_KEY:
        print("Error: Missing API key.")
    else:
        inspect_entry_fields()
