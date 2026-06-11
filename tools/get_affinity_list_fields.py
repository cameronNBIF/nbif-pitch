import os
import requests
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

API_KEY = os.getenv("AFFINITY_API_KEY")
LIST_ID = os.getenv("AFFINITY_LIST_ID")

# Gather the specific field IDs from your .env to filter the API response
ENV_FIELD_IDS = {
    os.getenv("AFFINITY_FIELD_ID_CONTACT"),
    os.getenv("AFFINITY_FIELD_ID_CONTACT_EMAIL"),
    os.getenv("AFFINITY_FIELD_ID_CONTACT_PHONE_NUMBER"),
    os.getenv("AFFINITY_FIELD_ID_DATE_OF_INCORPORATION"),
    os.getenv("AFFINITY_FIELD_ID_PRIORITY_SECTOR"),
    os.getenv("AFFINITY_FIELD_ID_INVESTMENT_ROUND_SIZE"),
    os.getenv("AFFINITY_FIELD_ID_POTENTIAL_INVESTMENT_AMOUNT"),
    os.getenv("AFFINITY_FIELD_ID_VENTURE_STAGE"),
    os.getenv("AFFINITY_FIELD_ID_DISCOVERY"),
    os.getenv("AFFINITY_FIELD_ID_ACCELERATORS"),
}

# Clean up empty values and convert to integers
TARGET_FIELD_IDS = {int(fid) for fid in ENV_FIELD_IDS if fid}

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


def fetch_list_fields():
    """Fetches both global fields and fields associated with the specific Affinity List."""
    all_fields = []

    # 1. Fetch List-Specific Fields
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
    if not API_KEY or not LIST_ID:
        print("Error: Missing AFFINITY_API_KEY or AFFINITY_LIST_ID in the .env file.")
        return

    print(f"Fetching metadata for List ID: {LIST_ID} and Global Workspace...\n")
    all_fields = fetch_list_fields()

    if not all_fields:
        return

    # Setup table formatting for the console output
    print(
        f"{'ID':<10} | {'Field Name':<25} | {'Type':<16} | {'Extra Context / Dropdown Options'}"
    )
    print("-" * 120)

    for field in all_fields:
        field_id = field.get("id")

        # Only process fields that exist in your .env file
        if field_id in TARGET_FIELD_IDS:
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
