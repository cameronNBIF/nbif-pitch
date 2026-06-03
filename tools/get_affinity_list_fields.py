import requests
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("AFFINITY_API_KEY")
LIST_ID = os.getenv("AFFINITY_LIST_ID")

BASE_URL = "https://api.affinity.co"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

ENTITY_TYPES = {
    0: "Organization",
    1: "Person",
    2: "Opportunity"
}

def format_field(field, source):
    lines = [
        f"Field ID:     {field['id']}",
        f"Field Name:   {field['name']}",
        f"Field Type:   {field.get('value_type', 'Unknown')}",
        f"Source:       {source}",
        "-" * 80
    ]
    return "\n".join(lines)

def get_list_fields(list_id):
    seen_ids = set()
    all_fields = []

    # --- 1. List-specific fields (also reveals entity type) ---
    list_response = requests.get(f"{BASE_URL}/lists/{list_id}", headers=headers)
    list_response.raise_for_status()
    list_data = list_response.json()
    entity_type = list_data.get("type")

    for field in list_data.get("fields", []):
        if field["id"] not in seen_ids:
            seen_ids.add(field["id"])
            all_fields.append((field, "List-specific"))

    # --- 2. Global fields scoped to this list ---
    global_list_response = requests.get(
        f"{BASE_URL}/fields", headers=headers, params={"list_id": list_id}
    )
    global_list_response.raise_for_status()

    for field in global_list_response.json():
        if field["id"] not in seen_ids:
            seen_ids.add(field["id"])
            all_fields.append((field, "Global (list-scoped)"))

    # --- 3. Global fields by entity type ---
    if entity_type is not None:
        entity_label = ENTITY_TYPES.get(entity_type, f"Entity type {entity_type}")
        global_entity_response = requests.get(
            f"{BASE_URL}/fields", headers=headers, params={"entity_type": entity_type}
        )
        global_entity_response.raise_for_status()

        for field in global_entity_response.json():
            if field["id"] not in seen_ids:
                seen_ids.add(field["id"])
                all_fields.append((field, f"Global ({entity_label})"))

    # --- Build output ---
    entity_label = ENTITY_TYPES.get(entity_type, str(entity_type))
    header = f"All fields for List {list_id} [{entity_label}] ({len(all_fields)} total):\n" + "-" * 80
    body = "\n".join(format_field(field, source) for field, source in all_fields)
    output = f"{header}\n{body}"

    # --- Print to console ---
    print(output)

    # --- Write to .txt file ---
    output_path = f"list_{list_id}_fields.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nResults saved to {output_path}")

if __name__ == "__main__":
    get_list_fields(LIST_ID)