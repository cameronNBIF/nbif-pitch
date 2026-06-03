import requests
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("AFFINITY_API_KEY")

BASE_URL = "https://api.affinity.co"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

def get_all_lists():
    url = f"{BASE_URL}/lists"

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    lists = response.json()

    print("\nAvailable Lists:")
    print("-" * 50)

    for lst in lists:
        print(f"ID: {lst.get('id')}")
        print(f"Name: {lst.get('name')}")
        print("-" * 50)

if __name__ == "__main__":
    get_all_lists()