# parse_deploy.py
import json
import os
from pathlib import Path
import re
import sys

log_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
text = log_path.read_text(encoding="utf-8", errors="replace")

worker_urls = re.findall(r"https://[A-Za-z0-9.-]+\.workers\.dev(?:/[^\s]*)?", text)
claim_urls = re.findall(r"https://dash\.cloudflare\.com/claim-preview\?[^\s]+", text)

if not worker_urls:
    raise SystemExit("Worker URL not found in Wrangler output")

result = {
    "worker_url": worker_urls[-1].rstrip(".,"),
    "claim_url": claim_urls[-1].rstrip(".,") if claim_urls else None,
    "relay_token": os.environ["RELAY_TOKEN"],
    "expires_minutes": 60,
}

out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(result["worker_url"])
