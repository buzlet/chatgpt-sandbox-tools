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
    "suite": "cloudflare-http-relay-selftest-v2",
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


def relay_body_bytes(response):
    if response["bodyEncoding"] == "base64url":
        return rpc.b64u_decode(response["body"])
    return response["body"].encode("utf-8")


save_report()

# Temporary relay Worker and its Durable Object binding are alive.
status, _, _, health = read_json(WORKER + "/health")
assert status == 200
assert health["ok"] is True and health["protocol"] == 2
assert health["storage"] == "durable-object" and health["logCapacity"] == 1000
passed("health", health)

expected_rids = set()

# Canonical example 1: GET with URL/query parameters, preserving Unicode.
rid_get_query = "bb0000000001"
status, _, _, response = relay(
    "GET",
    "https://httpbin.org/anything/get-demo?alpha=one&n=42&unicode=%D1%82%D0%B5%D1%81%D1%82",
    rid_get_query,
)
assert status == 200 and response["status"] == 200, response
get_echo = json.loads(response["body"])
assert get_echo["method"] == "GET"
assert get_echo["args"] == {"alpha": "one", "n": "42", "unicode": "тест"}, get_echo
expected_rids.add(rid_get_query)
passed("example_get_query", {"args": get_echo["args"]})

# Canonical example 2: POST with parameters in URL/query and JSON body.
rid_post_query_body = "bb0000000002"
example_post_body = {"message": "hello from cloudflare relay", "unicode": "тест", "count": 3}
status, _, _, response = relay(
    "POST",
    "https://httpbin.org/anything/post-demo?mode=full&id=42",
    rid_post_query_body,
    [["Content-Type", "application/json"]],
    json.dumps(example_post_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
)
assert status == 200 and response["status"] == 200, response
post_echo = json.loads(response["body"])
assert post_echo["method"] == "POST"
assert post_echo["args"] == {"id": "42", "mode": "full"}, post_echo
assert post_echo["json"] == example_post_body, post_echo
expected_rids.add(rid_post_query_body)
passed("example_post_query_body", {"args": post_echo["args"], "json": post_echo["json"]})

# Canonical example 3: download raw file bytes from URL without query parameters.
rid_file_plain = "bb0000000003"
status, _, _, response = relay("GET", "https://httpbin.org/bytes/1000", rid_file_plain)
assert status == 200 and response["status"] == 200, response
plain_bytes = relay_body_bytes(response)
assert len(plain_bytes) == 1000, len(plain_bytes)
expected_rids.add(rid_file_plain)
passed("example_file_plain", {"bytes": len(plain_bytes)})

# Canonical example 4: download raw file bytes where URL carries query parameters.
rid_file_query = "bb0000000004"
status, _, _, response = relay("GET", "https://httpbin.org/bytes/4096?seed=123", rid_file_query)
assert status == 200 and response["status"] == 200, response
query_bytes = relay_body_bytes(response)
assert len(query_bytes) == 4096, len(query_bytes)
expected_rids.add(rid_file_query)
passed("example_file_query", {"bytes": len(query_bytes), "query": "seed=123"})

# Provider 1: real outbound Internet plus UTF-8 JSON body handling.
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
expected_rids.add(rid_post)
passed("external_post_json_roundtrip", {"provider": "httpbun.com"})

# Provider 2: prove that Authorization changes target behavior: 401 -> 200.
rid_auth_missing = "aa0000000002"
status, _, _, response = relay("GET", "https://httpbin.org/bearer", rid_auth_missing)
assert status == 200, f"relay transport HTTP={status}, body={response!r}"
assert response["status"] == 401, f"httpbin without bearer returned {response!r}"
expected_rids.add(rid_auth_missing)
passed("authorization_required", {"provider": "httpbin.org", "withoutHeaderStatus": 401})

rid_auth = "aa0000000003"
status, _, _, response = relay(
    "GET", "https://httpbin.org/bearer", rid_auth,
    [["Authorization", "Bearer cloudflare-relay-selftest"]],
)
assert status == 200, f"relay transport HTTP={status}, body={response!r}"
assert response["status"] == 200, f"httpbin with bearer returned {response!r}"
expected_rids.add(rid_auth)
passed("authorization_header", {"provider": "httpbin.org", "withHeaderStatus": 200})

# Provider 3: method matrix. /anything accepts these methods; /head is HEAD-only.
method_results = {}
methods = ("GET", "HEAD", "PUT", "PATCH", "DELETE", "OPTIONS")
for index, method in enumerate(methods, start=4):
    rid = f"aa{index:010d}"
    target = "https://httpcan.org/head" if method == "HEAD" else "https://httpcan.org/anything"
    body = b"" if method in {"GET", "HEAD"} else (method + "-body").encode("ascii")
    headers = [["X-Relay-Selftest", f"method-{method.lower()}"]]
    if body:
        headers.append(["Content-Type", "text/plain"])

    status, _, _, response = relay(method, target, rid, headers, body)
    assert status == 200 and response["status"] == 200, f"{method}: {response!r}"
    if method != "HEAD":
        echoed = json.loads(response["body"])
        assert echoed.get("method") == method, f"{method}: {echoed!r}"
    expected_rids.add(rid)
    method_results[method] = "ok"
passed("method_matrix", {"provider": "httpcan.org", "methods": method_results})

# Exact binary body round-trip through an external echo endpoint.
binary = bytes(range(256)) * 4
rid_binary = "aa0000000010"
status, _, _, response = relay(
    "POST", "https://httpbun.com/payload", rid_binary,
    [["Content-Type", "application/octet-stream"]], binary,
)
assert status == 200 and response["status"] == 200, response
assert response["bodyEncoding"] == "base64url", response
assert rpc.b64u_decode(response["body"]) == binary
expected_rids.add(rid_binary)
passed("binary_roundtrip", {"provider": "httpbun.com", "bytes": len(binary)})

# Every authenticated proxy call must be queryable by agent; relay token must never be logged.
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

# Invalid relay token is rejected before proxy execution and cannot evict a ring entry.
rid_bad = "aa0000000011"
status, _, _, bad = relay("GET", "https://httpbin.org/get", rid_bad, token="wrong-token")
assert status == 403 and bad["ok"] is False
status, _, _, logs_after = read_json(log_url)
assert status == 200 and logs_after["count"] == count_before_invalid
assert rid_bad not in {row["rid"] for row in logs_after["rows"]}
passed("invalid_token_not_logged")

# All authenticated calls, including target 401, count as successfully executed proxy operations.
stats_url = WORKER + "/log?k=" + urllib.parse.quote(TOKEN, safe="-._~") + "&format=json&type=stats&period=total&limit=1"
status, _, _, stats = read_json(stats_url)
assert status == 200 and stats["count"] == 1
assert stats["rows"][0]["requests"] >= len(expected_rids)
assert stats["rows"][0]["success"] >= len(expected_rids)
passed("total_stats", stats["rows"][0])

# Human viewer removes token from the address bar and keeps it in a Secure HttpOnly cookie.
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
