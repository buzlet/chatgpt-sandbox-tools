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

CLIENT_HEADERS = {
    "User-Agent": "ChatGPT-User/1.0",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
}

report = {
    "ok": False,
    "suite": "cloudflare-http-relay-selftest-v1",
    "agent": AGENT,
    "checks": {},
}


def save_report():
    (OUT / "selftest-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def passed(name, value="ok"):
    report["checks"][name] = value
    save_report()


def read_url(url, opener=None):
    op = opener or urllib.request.build_opener()
    request = urllib.request.Request(url, headers=CLIENT_HEADERS)
    try:
        with op.open(request, timeout=30) as r:
            return r.status, r.geturl(), dict(r.headers.items()), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.geturl(), dict(e.headers.items()), e.read()


def read_json(url, opener=None, attempts=10):
    """Read JSON, retrying only temporary workers.dev propagation failures."""
    last = None
    for attempt in range(attempts):
        status, final_url, headers, raw = read_url(url, opener)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            last = (status, raw[:200], error)
            if url.startswith(WORKER) and status in {404, 502, 503, 504} and attempt + 1 < attempts:
                time.sleep(min(1 + attempt, 3))
                continue
            raise RuntimeError(f"non-JSON response: HTTP {status}, body={raw[:200]!r}") from error

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


def response_headers(response):
    return {str(k).lower(): str(v) for k, v in response.get("headers", [])}


save_report()

# Temporary Worker and its state binding are alive.
status, _, _, health = read_json(WORKER + "/health")
assert status == 200
assert health["ok"] is True and health["protocol"] == 2
assert health["storage"] == "durable-object" and health["logCapacity"] == 1000
passed("health", health)

# External provider 1: prove real outbound Internet and UTF-8 JSON body handling.
text_body = {"probe": "cloudflare-relay", "unicode": "тест", "n": 42}
rid_post = "aa0000000001"
status, _, _, response = relay(
    "POST", "https://httpbun.com/payload", rid_post,
    [["Content-Type", "application/json"]],
    json.dumps(text_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
)
assert status == 200 and response["ok"] is True and response["status"] == 200
assert response["rid"] == rid_post and response["bodyEncoding"] == "utf8"
assert json.loads(response["body"]) == text_body
passed("external_post_json_roundtrip")

# External provider 2: prove that the Authorization header changes target behavior.
rid_auth_missing = "aa0000000002"
status, _, _, response = relay("GET", "https://httpbin.org/bearer", rid_auth_missing)
assert status == 200, f"relay transport HTTP={status}, body={response!r}"
assert response["status"] == 401, f"httpbin without bearer returned {response!r}"
passed("authorization_required", {"withoutHeaderStatus": 401})

rid_auth = "aa0000000003"
status, _, _, response = relay(
    "GET", "https://httpbin.org/bearer", rid_auth,
    [["Authorization", "Bearer cloudflare-relay-selftest"]],
)
assert status == 200, f"relay transport HTTP={status}, body={response!r}"
assert response["status"] == 200, f"httpbin with bearer returned {response!r}"
assert response["rid"] == rid_auth
passed("authorization_header", {"withHeaderStatus": 200})

# Deterministic exact semantics. The endpoint only exists on SELFTEST_MODE deployments.
self_echo = WORKER + "/__selftest/echo"
method_results = {}
expected_rids = {rid_post, rid_auth_missing, rid_auth}
for index, method in enumerate(("GET", "HEAD", "PUT", "PATCH", "DELETE", "OPTIONS"), start=4):
    rid = f"aa{index:010d}"
    marker = f"method-{method.lower()}"
    body = b"" if method in {"GET", "HEAD"} else (method + "-body").encode("ascii")
    headers = [["X-Relay-Selftest", marker]]
    if method not in {"GET", "HEAD"}:
        headers.append(["Content-Type", "application/octet-stream"])

    status, _, _, response = relay(method, self_echo, rid, headers, body)
    assert status == 200 and response["status"] == 200, f"{method}: {response!r}"
    echoed_headers = response_headers(response)
    assert echoed_headers.get("x-selftest-method") == method
    assert echoed_headers.get("x-selftest-header") == marker
    if body:
        assert response["bodyEncoding"] == "base64url"
        assert rpc.b64u_decode(response["body"]) == body
    expected_rids.add(rid)
    method_results[method] = "ok"
passed("method_matrix", method_results)

# Exact arbitrary bytes, including 0x00 and 0xff, without a second Base64 layer in the request frame.
binary = bytes(range(256)) * 4
rid_binary = "aa0000000010"
status, _, _, response = relay(
    "POST", self_echo, rid_binary,
    [["Content-Type", "application/octet-stream"], ["X-Relay-Selftest", "binary"]],
    binary,
)
assert status == 200 and response["status"] == 200
assert response["bodyEncoding"] == "base64url"
assert rpc.b64u_decode(response["body"]) == binary
expected_rids.add(rid_binary)
passed("binary_roundtrip", {"bytes": len(binary)})

# Every authenticated proxy call must be queryable by this agent and token must not be logged.
log_url = (
    WORKER + "/log?k=" + urllib.parse.quote(TOKEN, safe="-._~")
    + "&format=json&type=all&limit=50&agent=" + urllib.parse.quote(AGENT, safe="-._~:")
)
status, _, _, logs = read_json(log_url)
assert status == 200 and logs["ok"] is True
rids = {row["rid"] for row in logs["rows"]}
assert expected_rids.issubset(rids), f"missing rids: {sorted(expected_rids - rids)}"
assert all(row["agent"] == AGENT for row in logs["rows"])
assert TOKEN not in json.dumps(logs, ensure_ascii=False)
count_before_invalid = logs["count"]
passed("log_json", {"count": logs["count"], "rids": sorted(expected_rids)})

# Invalid relay token must be rejected before proxy execution and must not consume a ring slot.
rid_bad = "aa0000000011"
status, _, _, bad = relay("GET", "https://httpbin.org/get", rid_bad, token="wrong-token")
assert status == 403 and bad["ok"] is False
status, _, _, logs_after = read_json(log_url)
assert status == 200 and logs_after["count"] == count_before_invalid
assert rid_bad not in {row["rid"] for row in logs_after["rows"]}
passed("invalid_token_not_logged")

# All authenticated calls, including a target 401, count as successfully executed proxy operations.
stats_url = WORKER + "/log?k=" + urllib.parse.quote(TOKEN, safe="-._~") + "&format=json&type=stats&period=total&limit=1"
status, _, _, stats = read_json(stats_url)
assert status == 200 and stats["count"] == 1
assert stats["rows"][0]["requests"] >= len(expected_rids)
assert stats["rows"][0]["success"] >= len(expected_rids)
passed("total_stats", stats["rows"][0])

# Human viewer must remove token from the address bar and keep it in a Secure HttpOnly cookie.
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
human_url = WORKER + "/log?k=" + urllib.parse.quote(TOKEN, safe="-._~") + "&limit=2"
status, final_url, headers, html = read_url(human_url, opener)
assert status == 200 and "k=" not in final_url
assert b"HTTP Relay" in html
cookies = list(jar)
assert any(c.name == "relay_access" and c.secure for c in cookies)
passed("human_log_view")

report["ok"] = True
save_report()
print(json.dumps(report, ensure_ascii=False, indent=2))
