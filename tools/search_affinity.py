import os
import sys
import json
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("AFFINITY_API_KEY")
LIST_ID = os.getenv("AFFINITY_LIST_ID")

AFFINITY_TYPE_MAP = {
    0: "Person",
    1: "Organization",
    2: "Dropdown",
    3: "Number",
    4: "Date",
    5: "Location",
    6: "Text",
    7: "Datetime",
    8: "Ranked Dropdown",
}


def get_list_fields():
    """Fetch all fields associated with AFFINITY_LIST_ID_MASTER."""
    if not LIST_ID:
        raise ValueError("AFFINITY_LIST_ID_MASTER not found in .env")

    url = f"https://api.affinity.co/fields?list_id={LIST_ID}"

    response = requests.get(url, auth=("", API_KEY))
    response.raise_for_status()

    return response.json()


def find_field(fields, field_name):
    """Find field(s) matching the provided name."""
    return [
        field
        for field in fields
        if field.get("name", "").strip().lower() == field_name.strip().lower()
    ]


def print_field_details(field):
    field_id = field.get("id")
    field_name = field.get("name")
    value_type = field.get("value_type")

    print("\n" + "=" * 80)
    print(f"Field Name : {field_name}")
    print(f"Field ID   : {field_id}")
    print(f"Field Type : {AFFINITY_TYPE_MAP.get(value_type, value_type)}")

    if field.get("allows_multiple"):
        print("Multiple   : Yes")

    if value_type in [2, 8]:
        print("\nDropdown Options:")
        for option in field.get("dropdown_options", []):
            print(f"  - {option['text']} ({option['id']})")

    print("\nFull Metadata:")
    print(json.dumps(field, indent=2))
    print("=" * 80)


def main():
    if not API_KEY:
        print("Error: AFFINITY_API_KEY missing from .env")
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage:")
        print('  python get_field.py "Field Name"')
        sys.exit(1)

    target_field = " ".join(sys.argv[1:])

    try:
        fields = get_list_fields()
    except Exception as e:
        print(f"Error fetching fields: {e}")
        sys.exit(1)

    matches = find_field(fields, target_field)

    if not matches:
        print(f"No field found named '{target_field}'")
        sys.exit(1)

    for field in matches:
        print_field_details(field)


if __name__ == "__main__":
    main()
