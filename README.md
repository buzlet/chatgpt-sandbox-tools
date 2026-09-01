# ChatGPT Sandbox Tools

A small toolbox for bridging ChatGPT's network-restricted sandbox to external services without requiring a custom MCP server.

The repository is intentionally organized by utility. Each tool owns its implementation, tests/documentation, and any reusable actions. GitHub workflow files live in `.github/workflows/` because GitHub requires that location; their filenames are prefixed with the utility name.

## Utilities

### [GitHub transport](github-transport/README.md)

GitHub Actions based transport for tasks that do not fit the direct web gateway well, especially arbitrary HTTP requests and large file downloads. Results are returned through workflow artifacts so the ChatGPT GitHub connector can retrieve them and materialize them into the sandbox.

Includes:

- arbitrary HTTP request runner;
- large-file downloader with retries/resume/SHA-256 verification;
- reusable composite Actions;
- design notes for multi-agent operation and sensitive request payloads.

### [Cloudflare HTTP relay](cloudflare-http-relay/README.md)

Fast HTTP RPC bridge:

`ChatGPT sandbox -> Brotli/Base64url -> ChatGPT HTTPS web gateway -> Cloudflare Worker -> target HTTP service`

Includes:

- GET/HEAD/POST/PUT/PATCH/DELETE/OPTIONS;
- raw binary request bodies;
- one deployment-wide access token;
- multi-agent identification as `scope:instance`;
- last 1000 authenticated requests;
- aggregate day/week/month/total statistics;
- `/log` HTML/JSON viewer;
- Cloudflare Durable Object state, no external database.

## Repository conventions

- Every utility lives in its own top-level directory and has its own `README.md`.
- Utility-specific workflow files use the utility name as a prefix, for example `github-transport-fetch-large-file.yml`.
- Shared or future utilities should follow the same layout rather than accumulating unrelated scripts at repository root.
- Secrets and real request payloads must not be committed to this public repository.
