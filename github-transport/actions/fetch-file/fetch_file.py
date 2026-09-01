# fetch_file.py
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse


def as_headers(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    if isinstance(value, list):
        return {str(k): str(v) for k, v in value}
    raise ValueError("headers must be an object or a list of pairs")


def main():
    request_file = Path(os.environ["REQUEST_FILE"])
    output_dir = Path(os.environ.get("OUTPUT_DIR", "download"))
    output_dir.mkdir(parents=True, exist_ok=True)

    req = json.loads(request_file.read_text(encoding="utf-8"))
    url = str(req["url"])
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("only HTTP/HTTPS URLs are supported")

    filename = Path(req.get("filename") or Path(parsed.path).name or "download.bin").name
    if filename in {"", ".", ".."}:
        raise ValueError("invalid filename")
    destination = output_dir / filename

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

    args = [
        "curl",
        "--location",
        "--fail-with-body",
        "--silent",
        "--show-error",
        "--retry", str(int(req.get("retries", 4))),
        "--retry-all-errors",
        "--connect-timeout", str(int(req.get("connect_timeout_seconds", 20))),
        "--output", str(destination),
    ]

    if bool(req.get("resume", True)):
        args += ["--continue-at", "-"]

    max_time = int(req.get("max_time_seconds", 0))
    if max_time > 0:
        args += ["--max-time", str(max_time)]

    max_bytes = int(req.get("max_bytes", 0))
    if max_bytes > 0:
        args += ["--max-filesize", str(max_bytes)]

    if not bool(req.get("verify_tls", True)):
        args += ["--insecure"]

    for name, value in headers.items():
        args += ["--header", f"{name}: {value}"]

    args.append(url)
    result = subprocess.run(args)
    if result.returncode:
        raise SystemExit(result.returncode)

    sha256 = hashlib.sha256(destination.read_bytes()).hexdigest()
    expected = str(req.get("sha256", "")).strip().lower()
    if expected and sha256 != expected:
        destination.unlink(missing_ok=True)
        raise SystemExit(f"sha256 mismatch: got {sha256}, expected {expected}")

    meta = {
        "url": url,
        "filename": filename,
        "bytes": destination.stat().st_size,
        "sha256": sha256,
    }
    (output_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as out:
            print(f"filename={filename}", file=out)
            print(f"bytes={meta['bytes']}", file=out)
            print(f"sha256={sha256}", file=out)


if __name__ == "__main__":
    main()
