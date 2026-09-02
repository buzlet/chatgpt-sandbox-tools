# Repository agent notes

This file is for agents developing and maintaining `chatgpt-sandbox-tools` itself.

Operational instructions for using the tools live in [`USAGE.md`](USAGE.md). Do not duplicate runtime bootstrap details here.

## Repository layout

Each utility owns its implementation, tests, and detailed README in a top-level directory. GitHub workflow files must live under `.github/workflows/` and use a utility-specific filename prefix.

Current utilities:

- `github-transport/` — GitHub Actions based HTTP and large-file transport.
- `cloudflare-http-relay/` — Cloudflare Worker HTTP relay.

## Development rules

- Keep utilities independent unless shared code is genuinely necessary.
- Preserve binary-safe request/response handling.
- Do not commit secrets, live relay tokens, claim URLs, or sensitive request payloads to this public repository.
- Keep self-tests end-to-end: external Internet request, transport execution, returned artifact/body, and sandbox verification where applicable.
- After material changes, the relevant self-test workflow must pass before the utility is considered ready.
- Prefer small, explicit workflows with utility prefixes over generic workflow names.

## Runtime documentation

User-facing and agent runtime instructions belong in [`USAGE.md`](USAGE.md). The private runtime bootstrap is deliberately kept outside the public repository in the user's ChatGPT Library.
