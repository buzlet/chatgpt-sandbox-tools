# Agent Self-Test Protocol

These utilities exist primarily for ChatGPT agents, so a green workflow icon by itself is not sufficient evidence. The agent should verify the complete transport path it is about to use.

## GitHub transport readiness

Workflow: `.github/workflows/github-transport-selftest.yml`

A PASS proves all of the following on a real GitHub-hosted runner:

1. an external service accepts the required `Authorization` header;
2. a UTF-8 JSON POST body survives the Internet round-trip unchanged;
3. PUT, PATCH and DELETE methods are preserved;
4. a deterministic external file can be downloaded twice and verified by SHA-256;
5. a real 5 MiB binary file can be downloaded from a second provider;
6. the workflow produces a GitHub Actions artifact containing the report and downloaded bytes;
7. the ChatGPT GitHub connector can download that artifact;
8. the artifact can be materialized/opened in the sandbox and its ZIP digest matches the digest reported by GitHub;
9. `selftest-report.json` contains `"ok": true`.

For serious file-transfer work, the agent should treat steps 6-9 as mandatory. They verify the return path `GitHub runner -> artifact -> GitHub connector -> sandbox`, not merely outbound Internet access from the runner.

## Cloudflare HTTP relay readiness

Workflow: `.github/workflows/cloudflare-http-relay-selftest.yml`

A PASS must prove on a freshly deployed temporary Worker:

1. `/health` reports protocol v2, Durable Object storage and the expected log capacity;
2. JSON POST survives `codec -> HTTPS -> Worker -> target -> Worker` unchanged;
3. a required Authorization header reaches the target;
4. PUT is preserved;
5. arbitrary binary request bytes survive the relay round-trip;
6. `/log?format=json` can filter by agent/request ID and does not expose the relay token;
7. a bad relay token returns 403 and does not consume a log-ring entry;
8. accumulated statistics are updated;
9. the human `/log` view renders and moves the access token from the URL into a Secure HttpOnly cookie;
10. `selftest-report.json` contains `"ok": true`.

The test client identifies as `ChatGPT-User/1.0`, because the actual production transport is the ChatGPT HTTPS web gateway. Cloudflare may reject Python's default `Python-urllib/*` fingerprint before a request reaches the Worker, which is not a failure of the intended ChatGPT transport.

Temporary workers.dev deployment can briefly return 404 while edge propagation finishes. The self-test therefore requires stable health and retries only propagation-style 404/502/503/504 responses. Application errors such as an intentional 403 are not retried.

## Agent policy

Before depending on a utility after meaningful code/workflow changes, use its self-test and inspect the actual result rather than assuming previous success still applies.

If a self-test fails:

1. inspect the exact failed job step and decoded job log;
2. distinguish target-service/transient-network failure from utility failure;
3. fix the utility or the test only when the failure mode is understood;
4. rerun until the complete path passes;
5. do not call the utility production-ready based only on local mocks.

The self-tests themselves are deliberately external and end-to-end. Local unit tests remain useful for fast development, but they are not a substitute for these readiness checks.
