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
    "suite": "github-transport-selftest-v1",
    "results": results,
}
(ROOT / "selftest-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
