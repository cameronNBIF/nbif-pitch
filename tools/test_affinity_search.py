import os
import requests
import json
from dotenv import load_dotenv

# Load config from environment (adjust the filename if your local API key is elsewhere)
load_dotenv(".env.register")

AFFINITY_API_KEY = os.environ.get("AFFINITY_API_KEY")
AFFINITY_BASE = "https://api.affinity.co"


def test_affinity_search(email: str):
    print(f"Searching Affinity for: {email}...")

    resp = requests.get(
        f"{AFFINITY_BASE}/persons", params={"term": email}, auth=("", AFFINITY_API_KEY)
    )

    resp.raise_for_status()

    # 1. Print the raw JSON response so you can see the exact structure
    data = resp.json()
    print("\n=== RAW JSON RESPONSE ===")
    print(json.dumps(data, indent=2))
    print("=========================\n")

    # 2. Test our new extraction logic
    print("=== TESTING FIX LOGIC ===")
    if isinstance(data, dict) and "persons" in data:
        persons_list = data["persons"]
        print(f"Success: The response is a dictionary containing a 'persons' list.")
        print(f"Found {len(persons_list)} matching record(s).")

        if len(persons_list) > 0:
            print(f"Extracted Person ID: {persons_list[0]['id']}")
    else:
        print("Failure: The response shape is not what we expected.")


if __name__ == "__main__":
    if not AFFINITY_API_KEY:
        print("Error: AFFINITY_API_KEY not found in environment.")
    else:
        test_affinity_search("cameron.horwood@unb.ca")
