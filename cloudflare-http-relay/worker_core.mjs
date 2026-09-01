// worker_core.mjs
import zlib from "node:zlib";
import { Buffer } from "node:buffer";

const METHODS = new Set(["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]);
const SAFE_AGENT = /^[A-Za-z0-9._:-]{1,80}$/;
const MAX_Q = 15000;
const MAX_REPLY = 1024 * 1024;
const LOG_PREVIEW = 32 * 1024;

const b64uDecode = value => Buffer.from(value, "base64url");
const b64uEncode = value => Buffer.from(value).toString("base64url");

export function decodeFrame(q) {
  if (!q || q.length > MAX_Q || !/^[A-Za-z0-9_-]+$/.test(q)) throw new Error("bad q");
  const raw = zlib.brotliDecompressSync(b64uDecode(q));
  if (raw.length < 4) throw new Error("short frame");
  const metadataLength = raw.readUInt32BE(0);
  if (metadataLength > raw.length - 4) throw new Error("bad metadata length");
  return {
    meta: JSON.parse(raw.subarray(4, 4 + metadataLength).toString("utf8")),
    body: raw.subarray(4 + metadataLength),
  };
}

function isPrivateLiteralHost(hostname) {
  const host = hostname.toLowerCase().replace(/\.$/, "");
  if (host === "localhost" || host.endsWith(".localhost")) return true;
  if (/^(127\.|0\.|10\.|192\.168\.|169\.254\.)/.test(host)) return true;
  const match = host.match(/^172\.(\d+)\./);
  if (match && +match[1] >= 16 && +match[1] <= 31) return true;
  return host === "::1" || host.startsWith("fc") || host.startsWith("fd") || host.startsWith("fe80:");
}

function checkedUrl(value, allowPrivate = false) {
  const url = new URL(value);
  if (!/^https?:$/.test(url.protocol) || url.username || url.password) throw new Error("target not allowed");
  if (!allowPrivate && isPrivateLiteralHost(url.hostname)) throw new Error("target not allowed");
  return url;
}

function isTextContentType(contentType) {
  return /^(text\/|application\/(json|.*\+json|xml|.*\+xml|javascript|x-www-form-urlencoded))/i.test(contentType || "");
}

function previewBytes(bytes, contentType) {
  const part = bytes.subarray(0, LOG_PREVIEW);
  const textual = isTextContentType(contentType);
  return {
    encoding: textual ? "utf8" : "base64url",
    body: textual ? new TextDecoder().decode(part) : b64uEncode(part),
    bytes: bytes.length,
    truncated: bytes.length > part.length,
  };
}

async function readLimited(response, limit) {
  if (!response.body) return { bytes: new Uint8Array(), truncated: false };
  const reader = response.body.getReader();
  const chunks = [];
  let total = 0;
  let truncated = false;

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    if (total + value.length > limit) {
      const remaining = limit - total;
      if (remaining > 0) chunks.push(value.subarray(0, remaining));
      truncated = true;
      await reader.cancel();
      break;
    }
    chunks.push(value);
    total += value.length;
  }

  const output = new Uint8Array(chunks.reduce((sum, chunk) => sum + chunk.length, 0));
  let offset = 0;
  for (const chunk of chunks) {
    output.set(chunk, offset);
    offset += chunk.length;
  }
  return { bytes: output, truncated };
}

function contentTypeFromHeaders(headers) {
  for (const [name, value] of headers) {
    if (String(name).toLowerCase() === "content-type") return String(value);
  }
  return "";
}

function validateMeta(meta, token) {
  if (meta?.v !== 2) throw new Error("unsupported protocol version");
  if (!METHODS.has(meta.m)) throw new Error("method not allowed");
  if (meta.k !== token) {
    const error = new Error("forbidden");
    error.httpStatus = 403;
    throw error;
  }
  if (!SAFE_AGENT.test(meta.a || "")) throw new Error("invalid agent");
  if (!/^[A-Fa-f0-9]{8,64}$/.test(meta.id || "")) throw new Error("invalid request id");
}

function requestLog(meta, body) {
  const headers = [...new Headers(meta.h || []).entries()];
  return {
    method: meta.m,
    url: meta.u,
    headers,
    ...previewBytes(body, contentTypeFromHeaders(headers)),
  };
}

export async function executeRpc(meta, body, allowPrivate = false) {
  let url = checkedUrl(meta.u, allowPrivate);
  let method = meta.m;
  let payload = body;
  const headers = new Headers(meta.h || []);

  for (const name of ["host", "content-length", "cf-connecting-ip", "x-forwarded-for", "x-real-ip"]) {
    headers.delete(name);
  }

  const redirects = Math.max(0, Math.min(Number(meta.r || 0), 5));
  const timeout = Math.max(100, Math.min(Number(meta.t || 15000), 60000));
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const started = performance.now();

  try {
    for (let i = 0; ; i++) {
      const init = { method, headers, redirect: "manual", signal: controller.signal };
      if (method !== "GET" && method !== "HEAD" && payload.length) init.body = payload;

      const response = await fetch(url, init);

      if (i < redirects && [301, 302, 303, 307, 308].includes(response.status) && response.headers.get("location")) {
        url = checkedUrl(new URL(response.headers.get("location"), url).href, allowPrivate);
        if (response.status === 303 || ((response.status === 301 || response.status === 302) && method === "POST")) {
          method = "GET";
          payload = Buffer.alloc(0);
        }
        continue;
      }

      const { bytes, truncated } = await readLimited(response, MAX_REPLY);
      const contentType = response.headers.get("content-type") || "";
      const textual = isTextContentType(contentType);

      return {
        publicResponse: {
          ok: true,
          rid: meta.id,
          status: response.status,
          statusText: response.statusText,
          url: response.url,
          headers: [...response.headers.entries()],
          bodyEncoding: textual ? "utf8" : "base64url",
          body: textual ? new TextDecoder().decode(bytes) : b64uEncode(bytes),
          bodyTruncated: truncated,
        },
        logResponse: {
          status: response.status,
          statusText: response.statusText,
          url: response.url,
          headers: [...response.headers.entries()],
          ...previewBytes(bytes, contentType),
          relayTruncated: truncated,
        },
        durationMs: Math.round((performance.now() - started) * 1000) / 1000,
      };
    }
  } finally {
    clearTimeout(timer);
  }
}

export async function handleRpc(request, env, state) {
  let decoded;
  try {
    decoded = decodeFrame(new URL(request.url).searchParams.get("q"));
    validateMeta(decoded.meta, env.RELAY_TOKEN);
  } catch (error) {
    return Response.json({ ok: false, error: String(error.message || error) }, { status: error.httpStatus || 400 });
  }

  const { meta, body } = decoded;
  const base = {
    ts: new Date().toISOString(),
    rid: meta.id,
    agent: meta.a,
    method: meta.m,
    target: meta.u,
    request: requestLog(meta, body),
  };

  try {
    const result = await executeRpc(meta, body, env.TEST_ALLOW_PRIVATE === "1");
    await state.record({
      ...base,
      outcome: "ok",
      response: result.logResponse,
      durationMs: result.durationMs,
    });
    return Response.json(result.publicResponse);
  } catch (error) {
    await state.record({
      ...base,
      outcome: "error",
      response: { status: 0, bytes: 0, headers: [], body: "", encoding: "utf8", truncated: false },
      durationMs: 0,
      error: String(error.message || error),
    });
    return Response.json({ ok: false, rid: meta.id, error: String(error.message || error) }, { status: 502 });
  }
}

const htmlEscape = value => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#39;");

function cookieValue(request, name) {
  for (const part of (request.headers.get("cookie") || "").split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return "";
}

function prettyMaybe(value) {
  if (typeof value !== "string") return JSON.stringify(value, null, 2);
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

function renderLogRows(rows) {
  return rows.map(row => {
    const request = row.request || {};
    const response = row.response || {};
    return `
      <article class="entry">
        <div class="summary">
          <code>${htmlEscape(row.ts)}</code>
          <strong>${htmlEscape(row.agent)}</strong>
          <span>${htmlEscape(row.method)}</span>
          <span>${htmlEscape(response.status ?? "ERR")}</span>
          <span>${htmlEscape(row.durationMs)} ms</span>
        </div>
        <div class="url">${htmlEscape(row.target)}</div>
        <div class="rid">rid: ${htmlEscape(row.rid)}</div>
        <details>
          <summary>Request</summary>
          <h4>Headers</h4>
          <pre>${htmlEscape(JSON.stringify(request.headers || [], null, 2))}</pre>
          <h4>Body ${request.truncated ? "(preview)" : ""}</h4>
          <pre>${htmlEscape(prettyMaybe(request.body || ""))}</pre>
        </details>
        <details>
          <summary>Response</summary>
          <h4>Headers</h4>
          <pre>${htmlEscape(JSON.stringify(response.headers || [], null, 2))}</pre>
          <h4>Body ${response.truncated || response.relayTruncated ? "(preview)" : ""}</h4>
          <pre>${htmlEscape(prettyMaybe(response.body || ""))}</pre>
        </details>
        ${row.error ? `<pre class="error">${htmlEscape(row.error)}</pre>` : ""}
      </article>`;
  }).join("\n");
}

function renderStatsRows(rows) {
  return `
    <table>
      <thead><tr>
        <th>Bucket</th><th>Requests</th><th>Success</th><th>Errors</th>
        <th>Req bytes</th><th>Resp bytes</th><th>Avg ms</th>
      </tr></thead>
      <tbody>${rows.map(row => `<tr>
        <td>${htmlEscape(row.bucket)}</td><td>${row.requests}</td><td>${row.success}</td>
        <td>${row.errors}</td><td>${row.requestBytes}</td><td>${row.responseBytes}</td><td>${row.avgDurationMs}</td>
      </tr>`).join("")}</tbody>
    </table>`;
}

function renderHtml({ rows, type, agent, rid, limit, period }) {
  const body = type === "stats" ? renderStatsRows(rows) : renderLogRows(rows);
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HTTP Relay Log</title>
<style>
:root{color-scheme:light dark;font-family:system-ui,sans-serif}body{max-width:1200px;margin:24px auto;padding:0 16px}form{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}input,select,button{padding:7px 9px;font:inherit}.entry{border:1px solid #7776;border-radius:8px;padding:12px;margin:10px 0}.summary{display:grid;grid-template-columns:190px minmax(160px,1fr) 70px 60px 90px;gap:8px}.url{margin-top:7px;overflow-wrap:anywhere}.rid{opacity:.65;font-size:.9em;margin-top:4px}details{margin-top:10px}pre{overflow:auto;padding:10px;border-radius:6px;background:#7772}.error{border-left:3px solid currentColor}table{border-collapse:collapse;width:100%}th,td{text-align:left;border-bottom:1px solid #7775;padding:8px}@media(max-width:800px){.summary{grid-template-columns:1fr 1fr}}
</style>
</head>
<body>
<h1>HTTP Relay</h1>
<form method="get" action="/log">
  <input name="agent" value="${htmlEscape(agent)}" placeholder="agent">
  <input name="rid" value="${htmlEscape(rid)}" placeholder="rid">
  <select name="type">${["all", "meta", "request", "response", "stats"].map(value => `<option value="${value}" ${value === type ? "selected" : ""}>${value}</option>`).join("")}</select>
  <select name="period">${["day", "week", "month", "total"].map(value => `<option value="${value}" ${value === period ? "selected" : ""}>${value}</option>`).join("")}</select>
  <input name="limit" type="number" min="1" max="1000" value="${Number(limit) || 50}">
  <button>View</button>
</form>
${body}
</body>
</html>`;
}

export async function handleLog(request, env, state) {
  const url = new URL(request.url);
  const supplied = url.searchParams.get("k") || cookieValue(request, "relay_access");
  if (!env.RELAY_TOKEN || supplied !== env.RELAY_TOKEN) return new Response("Forbidden", { status: 403 });

  const format = url.searchParams.get("format") || "html";

  if (url.searchParams.has("k") && format !== "json") {
    url.searchParams.delete("k");
    return new Response(null, {
      status: 302,
      headers: {
        location: url.pathname + (url.search || ""),
        "set-cookie": `relay_access=${encodeURIComponent(env.RELAY_TOKEN)}; Path=/log; Max-Age=31536000; HttpOnly; Secure; SameSite=Strict`,
      },
    });
  }

  const type = url.searchParams.get("type") || "all";
  const agent = url.searchParams.get("agent") || "";
  const rid = url.searchParams.get("rid") || "";
  const period = url.searchParams.get("period") || "day";
  const limit = Math.max(1, Math.min(Number(url.searchParams.get("limit") || 50), 1000));

  const rows = type === "stats"
    ? await state.stats(period, limit)
    : await state.logs({ limit, agent, rid, type });

  if (format === "json") {
    return Response.json({
      ok: true,
      type,
      period: type === "stats" ? period : undefined,
      agent: agent || undefined,
      rid: rid || undefined,
      count: rows.length,
      rows,
    });
  }

  return new Response(renderHtml({ rows, type, agent, rid, limit, period }), {
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}
