# GitHub Transport

GitHub Actions based transport for operations that are awkward or unreliable through the ChatGPT sandbox network path, especially arbitrary HTTP requests and large file downloads.

The utility is deliberately independent from the Cloudflare relay. It is slower, but it is binary-safe, produces reproducible logs, can verify hashes, and returns results as GitHub Actions artifacts that the ChatGPT GitHub connector can retrieve.

## Components

### Reusable HTTP action

`actions/http-request/`

Executes an HTTP request described by a JSON file. Supports:

- GET / HEAD / POST / PUT / PATCH / DELETE / OPTIONS;
- request headers;
- UTF-8 body, JSON body, Base64 body or body from a repository file;
- timeout;
- optional redirect following;
- optional TLS verification disable for controlled diagnostics;
- response body as `body.bin` and, when UTF-8, `body.txt`;
- response metadata and SHA-256.

### Reusable large-file action

`actions/fetch-file/`

Downloads an HTTP/HTTPS file with:

- redirects;
- retries;
- retry on transient errors;
- optional resume;
- connect timeout;
- optional maximum runtime;
- optional maximum file size;
- custom headers;
- optional SHA-256 verification;
- artifact-friendly output.

### Workflows

GitHub requires workflows to live in `.github/workflows/`. Files belonging to this utility use the `github-transport-` prefix:

- `.github/workflows/github-transport-http-request.yml`
- `.github/workflows/github-transport-fetch-large-file.yml`

They expose `workflow_dispatch` for normal/manual use and package their results as artifacts.

## Multi-agent and sensitive requests

The repository is public, so real credentials or sensitive request bodies must not be committed, placed in Issues, or written to public workflow parameters without protection.

The proposed secure multi-agent transport is documented in [DESIGN.md](DESIGN.md). The key idea is to keep the repository public while carrying sensitive payloads only as encrypted objects/artifacts. That design is intentionally documented separately until its trigger/key handoff is implemented and tested.

## Returning artifacts to ChatGPT

The GitHub connector can:

1. locate a workflow run;
2. enumerate its artifacts;
3. download an artifact ZIP;
4. pass the resulting file reference to the Files bridge;
5. materialize it into the sandbox when raw bytes are needed.

This is the preferred transport for large binary files because the normal ChatGPT web path is not a byte-exact large-file channel.
