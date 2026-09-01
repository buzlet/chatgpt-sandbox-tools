# rpc_sandbox.py
import argparse
import base64
import brotli
import json
import re
import secrets
import struct
import sys

SAFE_Q = re.compile(r"^[A-Za-z0-9_-]+$")
SAFE_AGENT = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
DEFAULT_MAX_URL = 15000


def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    if not SAFE_Q.fullmatch(text):
        raise ValueError("invalid Base64url-no-padding payload")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def new_agent(scope: str) -> str:
    scope = re.sub(r"[^A-Za-z0-9._-]+", "-", scope.strip()).strip("-") or "chat"
    agent = f"{scope}:{secrets.token_hex(4)}"
    if not SAFE_AGENT.fullmatch(agent):
        raise ValueError("generated agent id is invalid")
    return agent


def new_rid() -> str:
    return secrets.token_hex(6)


def encode_frame(method, url, token, agent, headers=None, body=b"", timeout_ms=15000, redirects=0, quality=11, rid=None):
    if not token:
        raise ValueError("token is required")
    if not SAFE_AGENT.fullmatch(agent):
        raise ValueError("agent must match [A-Za-z0-9._:-]{1,80}")

    meta = {
        "v": 2,
        "m": method.upper(),
        "u": url,
        "h": headers or [],
        "t": int(timeout_ms),
        "r": int(redirects),
        "k": token,
        "a": agent,
        "id": rid or new_rid(),
    }
    metadata = json.dumps(meta, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    frame = struct.pack(">I", len(metadata)) + metadata + body
    return b64u_encode(brotli.compress(frame, quality=quality)), meta["id"]


def decode_frame(q):
    raw = brotli.decompress(b64u_decode(q))
    if len(raw) < 4:
        raise ValueError("short frame")
    metadata_length = struct.unpack(">I", raw[:4])[0]
    if metadata_length > len(raw) - 4:
        raise ValueError("invalid metadata length")
    return json.loads(raw[4:4 + metadata_length].decode("utf-8")), raw[4 + metadata_length:]


def build_relay_url(relay_url: str, q: str, max_url=DEFAULT_MAX_URL) -> str:
    separator = "&" if "?" in relay_url else "?"
    result = f"{relay_url}{separator}q={q}"
    if len(result) > max_url:
        raise ValueError(f"relay URL too long: {len(result)} > {max_url}")
    return result


def parse_headers(items):
    result = []
    for item in items:
        if ":" not in item:
            raise ValueError(f"invalid header: {item}")
        name, value = item.split(":", 1)
        result.append([name.strip(), value.strip()])
    return result


def main():
    parser = argparse.ArgumentParser(description="ChatGPT Cloudflare HTTP relay codec v2")
    sub = parser.add_subparsers(dest="cmd", required=True)

    agent_cmd = sub.add_parser("new-agent")
    agent_cmd.add_argument("scope")

    encode_cmd = sub.add_parser("encode")
    encode_cmd.add_argument("method")
    encode_cmd.add_argument("url")
    encode_cmd.add_argument("--token", required=True)
    encode_cmd.add_argument("--agent", required=True)
    encode_cmd.add_argument("--rid")
    encode_cmd.add_argument("--header", action="append", default=[])
    body = encode_cmd.add_mutually_exclusive_group()
    body.add_argument("--body")
    body.add_argument("--body-file")
    encode_cmd.add_argument("--timeout", type=int, default=15000)
    encode_cmd.add_argument("--redirects", type=int, default=0)
    encode_cmd.add_argument("--quality", type=int, default=11)
    encode_cmd.add_argument("--relay-url")
    encode_cmd.add_argument("--max-url", type=int, default=DEFAULT_MAX_URL)

    inspect_cmd = sub.add_parser("inspect")
    inspect_cmd.add_argument("q")

    args = parser.parse_args()

    if args.cmd == "new-agent":
        print(new_agent(args.scope))
        return

    if args.cmd == "inspect":
        meta, body_bytes = decode_frame(args.q)
        safe_meta = dict(meta)
        if "k" in safe_meta:
            safe_meta["k"] = "***"
        print(json.dumps({"meta": safe_meta, "bodyBytes": len(body_bytes)}, ensure_ascii=False, indent=2))
        return

    payload = open(args.body_file, "rb").read() if args.body_file else (args.body or "").encode("utf-8")
    q, rid = encode_frame(
        args.method,
        args.url,
        args.token,
        args.agent,
        parse_headers(args.header),
        payload,
        args.timeout,
        args.redirects,
        args.quality,
        args.rid,
    )
    print(build_relay_url(args.relay_url, q, args.max_url) if args.relay_url else q)
    print(f"rid={rid} q_chars={len(q)} raw_body={len(payload)}", file=sys.stderr)


if __name__ == "__main__":
    main()
