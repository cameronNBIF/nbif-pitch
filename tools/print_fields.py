import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("AFFINITY_API_KEY")

response = requests.get(
    "https://api.affinity.co/fields",
    auth=("", API_KEY)
)
response.raise_for_status()

fields = response.json()

for field in sorted(fields, key=lambda x: x["name"].lower()):
    print(f"{field['id']:>10}  {field['name']}")