import json
import httpx
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sample = (ROOT / "samples" / "vendor-a.txt").read_text(encoding="utf-8")
url = "http://127.0.0.1:8000/api/evaluate"
payload = {"rfq_id": "RFQ-001", "profile_text": sample}
resp = httpx.post(url, json=payload, timeout=30.0)
try:
    resp.raise_for_status()
except httpx.HTTPStatusError as e:
    print("Request failed:", e)
    print(resp.text[:2000])
    raise
print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
