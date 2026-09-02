# Runtime usage

This file contains operational instructions for ChatGPT agents using `chatgpt-sandbox-tools` to make Internet requests or download raw files.

## Bootstrap

The canonical private bootstrap file is stored in the user's ChatGPT Library at:

`/ChatGPT Tools/chatgpt-sandbox-tools-access.json`

The bootstrap contains this instruction URL/path plus any private runtime access data. Do not ask the user to paste Cloudflare credentials if the bootstrap is available.

Expected structure:

```json
{
  "version": 1,
  "instructions": {
    "repository": "buzlet/chatgpt-sandbox-tools",
    "path": "USAGE.md",
    "url": "https://github.com/buzlet/chatgpt-sandbox-tools/blob/main/USAGE.md"
  },
  "cloudflare": {
    "worker_url": "https://example.workers.dev",
    "relay_token": "secret",
    "expires_at": null
  }
}
```

If `expires_at` is non-null, verify that it is still valid. Never print `relay_token` unless explicitly requested. If credentials are missing or expired, do not invent them.

## Cloudflare Relay

Use `cloudflare-http-relay/` for fast small/medium HTTP requests and raw downloads that fit the relay response limit.

Protocol references:

- `cloudflare-http-relay/README.md`
- `cloudflare-http-relay/PROTOCOL.md`
- `cloudflare-http-relay/rpc_sandbox.py`

Create one agent id per chat in the form `chat:<8 random hex>` and a fresh request id per request.

For raw downloads, decode the relay response according to `bodyEncoding`, write the original bytes into the sandbox, and return the sandbox file link plus size and SHA-256.

Do not silently replace a requested Cloudflare Relay operation with an ordinary web request.

## GitHub transport

Use `github-transport/` for requests/downloads that need a GitHub runner, especially large binary downloads and artifact return.

References:

- `github-transport/README.md`
- `.github/workflows/github-transport-http-request.yml`
- `.github/workflows/github-transport-fetch-large-file.yml`

Retrieve the resulting GitHub Actions artifact with the GitHub connector and materialize/extract the raw response or downloaded file into the sandbox. Return the sandbox file link plus size and SHA-256.

If the available GitHub connector cannot start the required workflow, do not silently replace the requested GitHub transport with a normal web request.

## Minimal prompts

The following are complete user requests when the bootstrap file is available:

- `Выполни GET <URL> через Cloudflare Relay. Конфиг возьми из Library: /ChatGPT Tools/chatgpt-sandbox-tools-access.json.`
- `Выполни POST <URL> с телом <BODY> через Cloudflare Relay. Конфиг возьми из Library: /ChatGPT Tools/chatgpt-sandbox-tools-access.json.`
- `Скачай <URL> через Cloudflare Relay в sandbox. Конфиг возьми из Library: /ChatGPT Tools/chatgpt-sandbox-tools-access.json.`
- `Скачай <URL> через GitHub transport в sandbox. Конфиг возьми из Library: /ChatGPT Tools/chatgpt-sandbox-tools-access.json.`
