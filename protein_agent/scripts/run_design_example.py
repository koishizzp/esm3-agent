"""Example script that calls the design API endpoint."""
from __future__ import annotations

import json
import requests

payload = {"task": "Design an improved GFP and iteratively optimize it.", "max_iterations": 10}
resp = requests.post("http://127.0.0.1:8000/design_protein", json=payload, timeout=600)
resp.raise_for_status()
print(json.dumps(resp.json(), indent=2)[:5000])
