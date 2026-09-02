// echo-worker.mjs
export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return Response.json({ ok: true, role: "selftest-echo" });
    }

    if (url.pathname !== "/echo") {
      return new Response("Not found", { status: 404 });
    }

    const headers = new Headers({
      "content-type": request.headers.get("content-type") || "application/octet-stream",
      "x-selftest-method": request.method,
      "x-selftest-header": request.headers.get("x-relay-selftest") || "",
    });

    if (request.method === "HEAD") {
      return new Response(null, { status: 200, headers });
    }

    return new Response(await request.arrayBuffer(), { status: 200, headers });
  },
};
