# Cloudflare Relay Protocol Notes

This file records the transport experiments that led to protocol v2.

## Why Brotli first

The RPC descriptor is structured JSON and usually contains repeated HTTP vocabulary, headers and URLs. Compressing before textual encoding gave the dominant size reduction.

Practical sandbox tests showed that a roughly 11.7 KiB structured JSON request could compress to a few hundred Base64url characters with Brotli. In contrast, changing the textual radix after compression only offered very small gains.

## Why Base64url without padding

The ChatGPT web gateway was tested with URL path/query characters rather than assuming an ideal RFC3986 transport.

Observed behavior:

- stable literal characters: `A-Z a-z 0-9 - . _ ~`;
- most other ASCII punctuation was canonicalized to `%XX`;
- `#` began a fragment and therefore did not reach the server as payload;
- Latin-1 / Unicode characters were encoded as UTF-8 and then percent-encoded;
- using extended characters therefore expanded the transmitted URL instead of providing an 8-bit alphabet.

Base85 looked shorter before URL escaping but became longer after percent encoding. A custom Base66/67 alphabet could save only around one percent compared with Base64url while adding a custom codec and parser edge cases.

The selected alphabet is therefore standard Base64url without `=` padding:

`A-Z a-z 0-9 - _`

It survives the observed gateway canonicalization without expansion and is supported natively by Python/Node.

## Frame v2

Before Brotli compression:

```text
uint32be(metadata_length)
metadata_json_utf8
raw_body_bytes
```

Metadata example:

```json
{
  "v": 2,
  "m": "POST",
  "u": "https://example.com/api",
  "h": [["content-type", "application/json"]],
  "t": 15000,
  "r": 0,
  "k": "deployment-wide-token",
  "a": "project:instance",
  "id": "abcdef123456"
}
```

Fields:

- `v`: protocol version;
- `m`: target HTTP method;
- `u`: target URL;
- `h`: request header pairs;
- `t`: timeout in milliseconds;
- `r`: maximum redirects, currently clamped to 0..5;
- `k`: deployment access token;
- `a`: agent identifier;
- `id`: per-request correlation ID (`rid`).

The body is appended as raw bytes after metadata. It is not embedded in JSON and is not Base64-encoded separately.

Final transport:

```text
frame -> Brotli quality 11 -> Base64url(no padding) -> q=<payload>
```

## URL size guard

The sandbox client should refuse to produce relay URLs beyond a conservative limit around 15,000 characters, leaving headroom below platform/gateway URL limits.

Highly compressible request bodies can be much larger than their final URL representation. Incompressible binary bodies reach the limit quickly; those belong in the GitHub transport/large-file path instead.

## Response format

Text-like content types return UTF-8 directly in the Worker JSON wrapper. Binary content returns Base64url in the wrapper.

The normal relay response is capped at 1 MiB. Large byte-exact transfers should use `github-transport/` instead.

## Agent identity

Recommended identifier:

`scope:instance`

Examples:

- `android-reader:a817c924`
- `ffmpeg-build:290dab17`
- `chat:c013909e`

`scope` is human-readable; `instance` distinguishes concurrent chats/agents working on the same project. Every HTTP call additionally receives a unique `rid`.

## Access token

One random access token is generated when the Worker is deployed. There is no token refresh/rotation protocol in v2.

The token is authorization only. Brotli/Base64url is not encryption. HTTPS is the confidentiality layer for the stated threat model.
