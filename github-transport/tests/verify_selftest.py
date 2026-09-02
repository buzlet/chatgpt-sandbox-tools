# verify_selftest.py
import hashlib
import json
from pathlib import Path

ROOT = Path(".selftest")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_status(name, expected=200):
    meta = load_json(ROOT / name / "meta.json")
    assert meta["status"] == expected, f"{name}: HTTP {meta['status']} != {expected}"
    return meta


def check_method(name, method):
    check_status(name)
    body = load_json(ROOT / name / "body.txt")
    assert body.get("method") == method, f"{name}: remote method={body.get('method')!r}, expected {method}"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


results = {}

# Canonical example 1: GET with URL/query parameters.
get_meta = check_status("get-query")
get_body = load_json(ROOT / "get-query" / "body.txt")
assert get_body["method"] == "GET"
assert get_body["args"] == {"alpha": "one", "n": "42", "unicode": "тест"}, get_body
results["example_get_query"] = {"status": get_meta["status"], "args": get_body["args"]}

# Canonical example 2: POST with URL/query parameters and JSON body.
post_query_meta = check_status("post-query-body")
post_query_body = load_json(ROOT / "post-query-body" / "body.txt")
expected_query_json = {"message": "hello from github transport", "unicode": "тест", "count": 3}
assert post_query_body["method"] == "POST"
assert post_query_body["args"] == {"id": "42", "mode": "full"}, post_query_body
assert post_query_body["json"] == expected_query_json, post_query_body
results["example_post_query_body"] = {
    "status": post_query_meta["status"],
    "args": post_query_body["args"],
    "json": post_query_body["json"],
}

# Canonical example 3: raw file download without URL/query parameters.
plain_file = ROOT / "file-plain" / "plain-1000.bin"
plain_meta = load_json(ROOT / "file-plain" / "meta.json")
assert plain_file.stat().st_size == 1000
assert plain_meta["bytes"] == 1000
assert plain_meta["sha256"] == sha256(plain_file)
results["example_file_plain"] = {"bytes": 1000, "sha256": plain_meta["sha256"]}

# Canonical example 4: raw file download where URL contains query parameters.
query_file = ROOT / "file-query" / "query-4096.bin"
query_meta = load_json(ROOT / "file-query" / "meta.json")
assert query_file.stat().st_size == 4096
assert query_meta["bytes"] == 4096
assert query_meta["sha256"] == sha256(query_file)
results["example_file_query"] = {"bytes": 4096, "sha256": query_meta["sha256"]}

# Authentication header must actually be accepted by the remote service.
auth = check_status("auth")
results["bearer_header"] = {"status": auth["status"], "bytes": auth["bytes"]}

# JSON body and UTF-8 data must survive the complete action -> Internet -> response path.
post = check_status("post")
post_body = load_json(ROOT / "post" / "body.txt")
expected_post = {"probe": "chatgpt-sandbox-tools", "unicode": "тест", "n": 42}
assert post_body == expected_post, f"POST payload mismatch: {post_body!r}"
results["post_json_roundtrip"] = {"status": post["status"], "body": post_body}

# Method preservation.
for method in ("PUT", "PATCH", "DELETE"):
    name = method.lower()
    check_method(name, method)
    results[f"method_{name}"] = "ok"

# Deterministic Internet file downloaded twice; second pass exercises expected SHA verification.
range1 = ROOT / "range1" / "range-1000.bin"
range2 = ROOT / "range2" / "range-1000.bin"
assert range1.read_bytes() == range2.read_bytes(), "deterministic download changed between passes"
range_meta1 = load_json(ROOT / "range1" / "meta.json")
range_meta2 = load_json(ROOT / "range2" / "meta.json")
actual_range_sha = sha256(range1)
assert range_meta1["bytes"] == 1000, f"range1 size={range_meta1['bytes']}"
assert range_meta2["bytes"] == 1000, f"range2 size={range_meta2['bytes']}"
assert range_meta1["sha256"] == actual_range_sha == range_meta2["sha256"], "range SHA mismatch"
results["checksum_download"] = {"bytes": 1000, "sha256": actual_range_sha}

# Real multi-megabyte download from a different external provider.
large = ROOT / "large" / "cloudflare-5m.bin"
large_meta = load_json(ROOT / "large" / "meta.json")
expected_size = 5 * 1024 * 1024
assert large.stat().st_size == expected_size, f"large file size={large.stat().st_size}, expected {expected_size}"
actual_large_sha = sha256(large)
assert large_meta["bytes"] == expected_size, "large meta byte count mismatch"
assert large_meta["sha256"] == actual_large_sha, "large SHA mismatch"
results["large_download"] = {"bytes": expected_size, "sha256": actual_large_sha}

report = {
    "ok": True,
    "suite": "github-transport-selftest-v2",
    "results": results,
}
(ROOT / "selftest-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
