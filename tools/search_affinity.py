import os
import sys
import requests
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

API_KEY = os.getenv("AFFINITY_API_KEY")
LIST_ID = os.getenv("AFFINITY_LIST_ID")

# Affinity maps field types to integers. This dictionary translates them for readability.
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


def fetch_all_fields():
    """Fetches both global fields and fields associated with the specific Affinity List."""
    all_fields = []

    # 1. Fetch List-Specific Fields (if LIST_ID is available)
    if LIST_ID:
        list_url = f"https://api.affinity.co/fields?list_id={LIST_ID}"
        list_response = requests.get(list_url, auth=("", API_KEY))

        if list_response.status_code == 200:
            all_fields.extend(list_response.json())
        else:
            print(
                f"Error fetching list fields: {list_response.status_code}\n{list_response.text}"
            )

    # 2. Fetch Global Fields
    global_url = "https://api.affinity.co/fields"
    global_response = requests.get(global_url, auth=("", API_KEY))

    if global_response.status_code == 200:
        # Combine the lists, ensuring we don't duplicate any fields just in case
        existing_ids = {f.get("id") for f in all_fields}
        for field in global_response.json():
            if field.get("id") not in existing_ids:
                all_fields.append(field)
    else:
        print(
            f"Error fetching global fields: {global_response.status_code}\n{global_response.text}"
        )

    return all_fields


def main():
    if not API_KEY:
        print("Error: Missing AFFINITY_API_KEY in the .env file.")
        return

    # Accept the field name via command line argument or prompt the user
    if len(sys.argv) > 1:
        target_field_name = " ".join(sys.argv[1:])
    else:
        target_field_name = input("Enter the exact name of the field you are looking for: ")

    if not target_field_name.strip():
        print("No field name provided. Exiting.")
        return

    print(f"\nFetching metadata and searching for '{target_field_name}'...\n")
    all_fields = fetch_all_fields()

    if not all_fields:
        return

    # Search for the field (case-insensitive for better usability)
    found_fields = [
        f for f in all_fields 
        if f.get("name", "").strip().lower() == target_field_name.strip().lower()
    ]

    if not found_fields:
        print(f"Could not find a field named '{target_field_name}'.")
        return

    # Setup table formatting for the console output
    print(
        f"{'ID':<10} | {'Field Name':<25} | {'Type':<16} | {'Extra Context / Dropdown Options'}"
    )
    print("-" * 120)

    for field in found_fields:
        field_id = field.get("id")
        name = field.get("name", "Unknown")
        value_type_int = field.get("value_type")
        value_type_str = AFFINITY_TYPE_MAP.get(
            value_type_int, f"Unknown ({value_type_int})"
        )

        allows_multiple = field.get("allows_multiple", False)

        # Build up extra context (multiple values, dropdown configurations)
        context = []
        if allows_multiple:
            context.append("[Allows Multiple Values]")

        # If the field is a dropdown (type 2 or 8), extract its available options
        if value_type_int in [2, 8]:
            dropdown_options = field.get("dropdown_options", [])
            if dropdown_options:
                options_str = ", ".join(
                    [f"{opt['text']} ({opt['id']})" for opt in dropdown_options]
                )
                context.append(f"Options: {options_str}")

        context_output = " ".join(context) if context else "Standard Field"

        # Print the formatted row
        print(
            f"{field_id:<10} | {name[:25]:<25} | {value_type_str:<16} | {context_output}"
        )


if __name__ == "__main__":
    main()