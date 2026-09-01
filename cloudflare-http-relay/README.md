# Cloudflare HTTP Relay

Fast HTTP RPC bridge intended for ChatGPT's web gateway when the sandbox itself has no reliable outbound Internet access.

`Sandbox -> Brotli/Base64url -> HTTPS GET -> Cloudflare Worker -> target HTTP service`

## Current v2 behavior

- HTTP methods: GET / HEAD / POST / PUT / PATCH / DELETE / OPTIONS.
- Request body remains raw bytes inside the compressed RPC frame, so binary POST/PUT does not need a second Base64 layer.
- One random deployment-wide `RELAY_TOKEN`; no refresh or rotation protocol.
- Multiple clients identified as `scope:instance`, for example `android-reader:a817c924`.
- Unique `rid` for every proxied request.
- Last 1000 authenticated proxy calls retained.
- Aggregate global counters by UTC day, ISO week, month and all-time.
- `/log` returns minimal server-rendered HTML by default and JSON with `format=json`.
- No React or frontend runtime.
- No D1 or external database. One Durable Object stores the ring buffer and counters.

Network fetches execute in the normal Worker. The Durable Object is used only for small serialized state updates and queries, so multiple agents can continue making network requests concurrently.

## Endpoints

### `GET /v1/rpc?q=...`

`q` contains a v2 RPC frame described in [PROTOCOL.md](PROTOCOL.md).

Successful relay response includes the request ID:

```json
{
  "ok": true,
  "rid": "abcdef123456",
  "status": 200,
  "headers": [],
  "bodyEncoding": "utf8",
  "body": "..."
}
```

### `GET /log`

The same deployment token protects the log endpoint.

For ChatGPT/machine use:

```text
/log?k=TOKEN&format=json&type=all&limit=50
/log?k=TOKEN&format=json&agent=android-reader:a817c924
/log?k=TOKEN&format=json&rid=abcdef123456
/log?k=TOKEN&format=json&type=stats&period=day&limit=31
```

Filters:

- `agent=scope:instance`
- `rid=<request-id>`
- `type=all|meta|request|response|stats`
- `period=day|week|month|total` for statistics
- `limit=1..1000`
- `format=json`

For a browser, opening `/log?k=TOKEN` stores the token in a Secure, HttpOnly, SameSite=Strict cookie and redirects to a clean `/log` URL.

## Logging

Only authenticated proxy calls are retained. Invalid tokens are rejected before logging so an outsider cannot evict useful entries from the 1000-entry ring.

Per request the relay stores:

- timestamp;
- agent and `rid`;
- method and target URL;
- outcome and duration;
- request/response headers;
- request/response body preview up to 32 KiB per side;
- byte counts and truncation flags.

The response returned through the web gateway is capped separately at 1 MiB.

Statistics are deliberately simple and global: requests, successes, errors, request bytes, response bytes, total/average duration. There are no analytics dimensions by agent or target.

## Deployment token

`RELAY_TOKEN` is generated at deployment time. How the token is handed to and persisted by ChatGPT clients is intentionally kept outside the relay protocol for now.

The temporary deployment workflow stores the generated token and Worker URL in a short-lived authenticated GitHub Actions artifact.

## Security model

There is no additional application-level encryption. HTTPS protects the request in transit; the ChatGPT web gateway and Cloudflare are treated as trusted participants that can see/decode the request.

The deployment token is authorization, not encryption. The token lives inside the compressed RPC metadata for `/v1/rpc`; it is verified and never written to the relay log.

Literal localhost, RFC1918 and link-local targets are rejected in production as basic SSRF defense in depth.
