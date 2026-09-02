// worker.mjs
import { DurableObject } from "cloudflare:workers";
import { StateStore } from "./state_store.mjs";
import { handleLog, handleRpc } from "./worker_core.mjs";

export class RelayState extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.store = new StateStore(ctx.storage);
  }

  async record(entry) {
    return await this.store.record(entry);
  }

  async logs(options) {
    return await this.store.logs(options);
  }

  async stats(period, limit) {
    return await this.store.stats(period, limit);
  }
}

async function selftestEcho(request) {
  const headers = new Headers({
    "content-type": request.headers.get("content-type") || "application/octet-stream",
    "x-selftest-method": request.method,
    "x-selftest-header": request.headers.get("x-relay-selftest") || "",
  });

  if (request.method === "HEAD") {
    return new Response(null, { status: 200, headers });
  }

  return new Response(await request.arrayBuffer(), { status: 200, headers });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return Response.json({
        ok: true,
        protocol: 2,
        logCapacity: 1000,
        storage: "durable-object",
      });
    }

    // Exact-byte echo exists only in explicit self-test deployments. It keeps
    // protocol tests deterministic without exposing an unnecessary public echo
    // service in normal deployments.
    if (env.SELFTEST_MODE === "1" && url.pathname === "/__selftest/echo") {
      return await selftestEcho(request);
    }

    const state = env.RELAY_STATE.getByName("global");

    if (url.pathname === "/v1/rpc" && request.method === "GET") {
      return await handleRpc(request, env, state);
    }

    if (url.pathname === "/log" && request.method === "GET") {
      return await handleLog(request, env, state);
    }

    return new Response("Not found", { status: 404 });
  },
};
