# GitHub Transport Design Notes

This file preserves the design work done before implementation so that useful constraints and rejected approaches are not lost.

## Why GitHub transport exists

The ChatGPT sandbox may have no direct outbound Internet access. The GitHub connector, however, can manipulate repository content, inspect Actions runs, and download workflow artifacts. GitHub-hosted runners have normal network access.

That creates a useful bridge:

`ChatGPT -> GitHub connector -> GitHub Actions runner -> Internet -> artifact -> GitHub connector -> sandbox`

It is slower than the Cloudflare relay but better for large/binary data and operations that need a normal runner environment.

## Multi-agent requirement

Several ChatGPT agents/chats may use the same repository concurrently. Therefore request transport must not rely on one mutable shared slot without correlation.

Every logical request should have a unique request ID and its result artifact should include that ID in its name or metadata.

Avoid using accumulating request commits as the long-term RPC queue. Git history is an excellent history mechanism and a fairly ridiculous message queue.

## Public repository and sensitive payloads

The repository is public. Plain request JSON in commits, Issues, PR comments, workflow input history, or artifacts may expose URLs, headers, bodies, cookies, API keys, or returned content.

For sensitive GitHub-transport traffic, the intended design is:

1. The agent creates an ephemeral symmetric key for the request.
2. Request metadata/body are compressed and encrypted locally.
3. The ciphertext is stored as an unreferenced Git blob or another opaque GitHub object rather than committed into the repository tree.
4. A small public trigger carries only a correlation/request ID and blob SHA.
5. The Action retrieves and decrypts the blob using a key made available through GitHub Actions Secrets or an asymmetric key-encryption scheme.
6. The result is encrypted before it is uploaded as an artifact.
7. The requesting sandbox decrypts the artifact locally.

An unreferenced blob is not treated as secret by itself. Anyone who learns its SHA may be able to fetch it from a public repository, so encryption is mandatory for sensitive content.

## Trigger options explored

### workflow_dispatch

Clean and natural, but the currently available ChatGPT GitHub connector does not expose a workflow-dispatch operation.

### Persistent PR branches

A request file committed to a long-lived PR branch can trigger `pull_request:synchronize`, but naïve use accumulates commits and turns Git history into transport state.

A force-replaced one-commit branch avoids most accumulation, but still adds complexity.

### Issue/comment trigger

One fixed Issue/comment can be edited to trigger `issue_comment:edited`, avoiding request commits. This is useful only for non-sensitive data or a ciphertext/blob pointer. Plain sensitive request content must not be placed in a public comment.

### Encrypted blob + tiny trigger

Preferred design for sensitive multi-agent use. The trigger contains no meaningful payload, only opaque identifiers. The actual request and result remain encrypted.

## Large file flow

For a large download the runner should fetch directly from the origin and upload the result as a GitHub Actions artifact:

`origin -> runner -> artifact`

Recommended controls:

- retries and retry-all-errors;
- resume where the origin supports it;
- explicit maximum size when appropriate;
- SHA-256 verification when a known digest exists;
- `compression-level: 0` for already-compressed or incompressible files;
- short artifact retention for transient transfers.

The ChatGPT GitHub connector can download the artifact ZIP and the Files bridge can materialize it into the sandbox.

## HTTP request flow

The generic request action deliberately accepts a JSON descriptor rather than hardcoding one API. This keeps it reusable for POST/PUT/custom headers, authenticated APIs and future utilities.

For credentials, prefer a named auth profile stored in Actions Secrets instead of putting long-lived secrets into request descriptors.

## Relationship to Cloudflare relay

Use Cloudflare relay for fast API-sized requests that can travel through the ChatGPT web gateway.

Use GitHub transport for:

- large binary downloads;
- large request bodies;
- byte-exact file transfer;
- long-running jobs;
- dependency/package preparation;
- cases that need a full runner environment.
