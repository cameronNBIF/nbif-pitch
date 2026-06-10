import os
import requests
import json
from dotenv import load_dotenv

# Load config from environment
load_dotenv(".env.register")

AFFINITY_API_KEY = os.environ.get("AFFINITY_API_KEY")
AFFINITY_LIST_ID = os.environ.get("AFFINITY_LIST_ID")
AFFINITY_BASE = "https://api.affinity.co"


def test_list_entry_creation():
    email = "cameron.horwood@unb.ca"
    person_id = 245650078  # We know this is the ID from your previous test

    print(
        f"Testing list entry creation for Person ID: {person_id} on List ID: {AFFINITY_LIST_ID}"
    )

    # We are using json= here to send proper application/json
    payload = {"entity_id": person_id}

    resp = requests.post(
        f"{AFFINITY_BASE}/lists/{AFFINITY_LIST_ID}/list-entries",
        json=payload,
        auth=("", AFFINITY_API_KEY),
    )

    print("\n=== RESPONSE STATUS ===")
    print(f"Status Code: {resp.status_code}")

    print("\n=== RAW JSON RESPONSE ===")
    try:
        data = resp.json()
        print(json.dumps(data, indent=2))
    except ValueError:
        print(resp.text)
    print("=========================\n")


if __name__ == "__main__":
    if not AFFINITY_API_KEY or not AFFINITY_LIST_ID:
        print("Error: AFFINITY_API_KEY or AFFINITY_LIST_ID not found in environment.")
    else:
        test_list_entry_creation()
