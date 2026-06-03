import os
import requests
import json
from dotenv import load_dotenv

# Load config from environment
load_dotenv()

AFFINITY_API_KEY = os.environ.get("AFFINITY_API_KEY")
AFFINITY_FIELD_ID_PRIORITY_SECTOR = os.environ.get("AFFINITY_FIELD_ID_PRIORITY_SECTOR")
AFFINITY_BASE = "https://api.affinity.co"

def test_get_dropdown_options():
    print(f"Fetching details for Field ID: {AFFINITY_FIELD_ID_PRIORITY_SECTOR}...")
    
    resp = requests.get(
        f"{AFFINITY_BASE}/fields",
        auth=("", AFFINITY_API_KEY)
    )
    
    resp.raise_for_status()
    fields = resp.json()
    
    # Search through all fields for the one matching your Status field
    for field in fields:
        if str(field.get("id")) == str(AFFINITY_FIELD_ID_PRIORITY_SECTOR):
            print(f"\n=== Found Field: {field.get('name')} ===")
            options = field.get("dropdown_options", [])
            
            if not options:
                print("No dropdown options found for this field.")
            else:
                for option in options:
                    print(f"Option Text: '{option.get('text')}'  --->  Integer ID: {option.get('id')}")
            print("===================================\n")
            return
            
    print("Error: Could not find a field with that ID.")

if __name__ == "__main__":
    if not AFFINITY_API_KEY or not AFFINITY_FIELD_ID_PRIORITY_SECTOR:
        print("Error: Missing API key or Priority Sector Field ID.")
    else:
        test_get_dropdown_options()