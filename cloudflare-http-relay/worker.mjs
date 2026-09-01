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
