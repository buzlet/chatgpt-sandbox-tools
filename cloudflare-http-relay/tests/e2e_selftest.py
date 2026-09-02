# e2e_selftest.py
import http.cookiejar
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import rpc_sandbox as rpc

WORKER = os.environ["WORKER_URL"].rstrip("/")
TOKEN = os.environ["RELAY_TOKEN"]
RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")
AGENT = f"selftest:{RUN_ID[-16:]}"
OUT = Path(os.environ.get("SELFTEST_DIR", ".selftest/cloudflare"))
OUT.mkdir(parents=True, exist_ok=True)


def read_url(url, opener=None):
    op = opener or urllib.request.build_opener()
    try:
        with op.open(url, timeout=30) as r:
            return r.status, r.geturl(), dict(r.headers.items()), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.geturl(), dict(e.headers.items()), e.read()


def read_json(url, opener=None, attempts=10):
    """Read JSON, retrying only transient temporary-Worker propagation failures."""
    last = None
    for attempt in range(attempts):
        status, final_url, headers, raw = read_url(url, opener)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            last = (status, raw[:200], error)
            if url.startswith(WORKER) and attempt + 1 < attempts:
                time.sleep(min(1 + attempt, 3))
                continue
            raise RuntimeError(f"non-JSON response: HTTP {status}, body={raw[:200]!r}") from error

        # A temporary workers.dev hostname may briefly resolve to an edge that has
        # not received the deployment yet. Application-level 4xx responses such as
        # our intentional 403 must NOT be retried.
        if url.startswith(WORKER) and status in {404, 502, 503, 504} and attempt + 1 < attempts:
            last = (status, value, None)
            time.sleep(min(1 + attempt, 3))
            continue
        return status, final_url, headers, value

    raise RuntimeError(f"Worker did not stabilize: {last!r}")


def relay(method, target, rid, headers=None, body=b"", token=TOKEN, redirects=0):
    q, returned_rid = rpc.encode_frame(
        method, target, token, AGENT, headers or [], body,
        timeout_ms=15000, redirects=redirects, rid=rid,
    )
    assert returned_rid == rid
    url = rpc.build_relay_url(WORKER + "/v1/rpc", q)
    assert len(url) < 15000
    return read_json(url)


report = {"ok": False, "suite": "cloudflare-http-relay-selftest-v1", "agent": AGENT, "checks": {}}

# Worker and Durable Object deployment are alive on the endpoint used by this client.
status, _, _, health = read_json(WORKER + "/health")
assert status == 200
assert health["ok"] is True and health["protocol"] == 2
assert health["storage"] == "durable-object" and health["logCapacity"] == 1000
report["checks"]["health"] = health

# Text POST body survives sandbox codec -> HTTPS -> Worker -> target -> Worker.
text_body = {"probe": "cloudflare-relay", "unicode": "тест", "n": 42}
rid_post = "aa0000000001"
status, _, _, response = relay(
    "POST",
    "https://httpbun.com/payload",
    rid_post,
    [["Content-Type", "application/json"]],
    json.dumps(text_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
)
assert status == 200 and response["ok"] is True and response["status"] == 200
assert response["rid"] == rid_post and response["bodyEncoding"] == "utf8"
assert json.loads(response["body"]) == text_body
report["checks"]["post_json_roundtrip"] = "ok"

# A target that rejects requests unless the custom Authorization header reaches it.
rid_auth = "aa0000000002"
status, _, _, response = relay(
    "GET",
    "https://httpbun.com/bearer/cloudflare-relay-selftest",
    rid_auth,
    [["Authorization", "Bearer cloudflare-relay-selftest"]],
)
assert status == 200 and response["status"] == 200 and response["rid"] == rid_auth
report["checks"]["authorization_header"] = "ok"

# Method preservation through the relay.
rid_put = "aa0000000003"
status, _, _, response = relay(
    "PUT",
    "https://httpbun.com/put",
    rid_put,
    [["Content-Type", "text/plain"], ["X-Relay-Selftest", "yes"]],
    b"put-body",
)
assert status == 200 and response["status"] == 200
put_echo = json.loads(response["body"])
assert put_echo.get("method") == "PUT"
report["checks"]["put_method"] = "ok"

# Arbitrary binary request bytes must survive without nested Base64 in the request frame.
binary = bytes(range(256)) * 4
rid_binary = "aa0000000004"
status, _, _, response = relay(
    "POST",
    "https://httpbun.com/payload",
    rid_binary,
    [["Content-Type", "application/octet-stream"]],
    binary,
)
assert status == 200 and response["status"] == 200
assert response["bodyEncoding"] == "base64url"
assert rpc.b64u_decode(response["body"]) == binary
report["checks"]["binary_roundtrip"] = {"bytes": len(binary)}

# Logs must contain all authenticated requests, allow agent filtering, and never expose relay token.
log_url = (
    WORKER + "/log?k=" + urllib.parse.quote(TOKEN, safe="-._~")
    + "&format=json&type=all&limit=20&agent=" + urllib.parse.quote(AGENT, safe="-._~:")
)
status, _, _, logs = read_json(log_url)
assert status == 200 and logs["ok"] is True
rids = {row["rid"] for row in logs["rows"]}
expected_rids = {rid_post, rid_auth, rid_put, rid_binary}
assert expected_rids.issubset(rids)
assert all(row["agent"] == AGENT for row in logs["rows"])
assert TOKEN not in json.dumps(logs, ensure_ascii=False)
count_before_invalid = logs["count"]
report["checks"]["log_json"] = {"count": logs["count"], "rids": sorted(expected_rids)}

# Bad relay token is rejected and must not consume a ring-buffer slot.
rid_bad = "aa0000000005"
status, _, _, bad = relay("GET", "https://httpbun.com/get", rid_bad, token="wrong-token")
assert status == 403 and bad["ok"] is False
status, _, _, logs_after = read_json(log_url)
assert status == 200 and logs_after["count"] == count_before_invalid
assert rid_bad not in {row["rid"] for row in logs_after["rows"]}
report["checks"]["invalid_token_not_logged"] = "ok"

# Accumulated statistics must include the authenticated requests.
stats_url = WORKER + "/log?k=" + urllib.parse.quote(TOKEN, safe="-._~") + "&format=json&type=stats&period=total&limit=1"
status, _, _, stats = read_json(stats_url)
assert status == 200 and stats["count"] == 1
assert stats["rows"][0]["requests"] >= 4 and stats["rows"][0]["success"] >= 4
report["checks"]["total_stats"] = stats["rows"][0]

# Human log view: token is moved from URL to Secure HttpOnly cookie and HTML renders.
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
human_url = WORKER + "/log?k=" + urllib.parse.quote(TOKEN, safe="-._~") + "&limit=2"
status, final_url, headers, html = read_url(human_url, opener)
assert status == 200 and "k=" not in final_url
assert b"HTTP Relay" in html
cookies = list(jar)
assert any(c.name == "relay_access" and c.secure for c in cookies)
report["checks"]["human_log_view"] = "ok"

report["ok"] = True
(OUT / "selftest-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
