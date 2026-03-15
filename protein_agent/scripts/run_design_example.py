"""Example script that calls the design API endpoint."""
from __future__ import annotations

import json
import os
import requests

BASE_URL = os.getenv("PROTEIN_AGENT_API_URL", "http://127.0.0.1:8002").rstrip("/")
payload = {"task": "Design an improved GFP and iteratively optimize it.", "max_iterations": 10}
resp = requests.post(f"{BASE_URL}/design_protein", json=payload, timeout=600)
resp.raise_for_status()
print(json.dumps(resp.json(), indent=2)[:5000])
