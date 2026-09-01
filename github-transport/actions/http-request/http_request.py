# http_request.py
import base64
import hashlib
import json
import os
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.request

ALLOWED_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def as_headers(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    if isinstance(value, list):
        return {str(k): str(v) for k, v in value}
    raise ValueError("headers must be an object or a list of pairs")


def request_body(req, workspace: Path):
    fields = [name for name in ("body", "body_json", "body_base64", "body_file") if name in req]
    if len(fields) > 1:
        raise ValueError("use only one of body/body_json/body_base64/body_file")
    if not fields:
        return None

    field = fields[0]
    if field == "body":
        return str(req[field]).encode("utf-8")
    if field == "body_json":
        return json.dumps(req[field], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if field == "body_base64":
        return base64.b64decode(req[field], validate=True)

    path = (workspace / str(req[field])).resolve()
    if path != workspace and workspace not in path.parents:
        raise ValueError("body_file escapes GITHUB_WORKSPACE")
    return path.read_bytes()


def main():
    request_file = Path(os.environ["REQUEST_FILE"])
    output_dir = Path(os.environ.get("OUTPUT_DIR", "response"))
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    req = json.loads(request_file.read_text(encoding="utf-8"))
    method = str(req.get("method", "GET")).upper()
    if method not in ALLOWED_METHODS:
        raise ValueError(f"unsupported method: {method}")

    url = str(req["url"])
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("only HTTP/HTTPS URLs are supported")

    headers = {}
    profile_name = req.get("auth_profile")
    profiles_raw = os.environ.get("HTTP_AUTH_PROFILES_JSON", "").strip()
    if profile_name:
        if not profiles_raw:
            raise ValueError("auth_profile requested but HTTP_AUTH_PROFILES_JSON is empty")
        profiles = json.loads(profiles_raw)
        if profile_name not in profiles:
            raise ValueError(f"unknown auth_profile: {profile_name}")
        headers.update(as_headers(profiles[profile_name]))
    headers.update(as_headers(req.get("headers")))

    body = request_body(req, workspace)
    timeout = float(req.get("timeout_seconds", 30))
    follow_redirects = bool(req.get("follow_redirects", True))
    verify_tls = bool(req.get("verify_tls", True))

    opener = urllib.request.build_opener(*([] if follow_redirects else [NoRedirect()]))
    context = None if verify_tls else ssl._create_unverified_context()

    request = urllib.request.Request(url, data=body, method=method)
    for name, value in headers.items():
        request.add_header(name, value)

    started = time.perf_counter()
    try:
        response = opener.open(request, timeout=timeout, context=context) if context else opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        response = error

    try:
        raw = response.read()
        status = int(response.status)
        reason = str(getattr(response, "reason", ""))
        final_url = response.geturl()
        response_headers = list(response.headers.items())
    finally:
        response.close()

    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    sha256 = hashlib.sha256(raw).hexdigest()

    (output_dir / "body.bin").write_bytes(raw)
    try:
        (output_dir / "body.txt").write_text(raw.decode("utf-8"), encoding="utf-8")
        utf8 = True
    except UnicodeDecodeError:
        utf8 = False

    meta = {
        "status": status,
        "reason": reason,
        "final_url": final_url,
        "headers": response_headers,
        "bytes": len(raw),
        "sha256": sha256,
        "elapsed_ms": elapsed_ms,
        "utf8": utf8,
    }
    (output_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as out:
            print(f"status={status}", file=out)
            print(f"bytes={len(raw)}", file=out)
            print(f"sha256={sha256}", file=out)
            print(f"elapsed_ms={elapsed_ms}", file=out)

    expected = req.get("expected_status")
    if expected is not None:
        allowed = {int(x) for x in expected} if isinstance(expected, list) else {int(expected)}
        if status not in allowed:
            raise SystemExit(f"unexpected HTTP status {status}; expected {sorted(allowed)}")


if __name__ == "__main__":
    main()
