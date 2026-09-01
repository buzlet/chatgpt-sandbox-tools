// state_store.mjs
export const LOG_CAPACITY = 1000;

const padSeq = n => String(n).padStart(16, "0");

function isoWeekKey(date) {
  const d = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  const day = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const week = Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
  return `${d.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}

export function periodKeys(ts) {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) throw new Error("invalid timestamp");
  const day = d.toISOString().slice(0, 10);
  return {
    day,
    week: isoWeekKey(d),
    month: day.slice(0, 7),
    total: "all",
  };
}

function emptyStats(period, bucket) {
  return {
    period,
    bucket,
    requests: 0,
    success: 0,
    errors: 0,
    requestBytes: 0,
    responseBytes: 0,
    durationMs: 0,
  };
}

function summarizeStats(stats) {
  return {
    ...stats,
    avgDurationMs: stats.requests
      ? Math.round((stats.durationMs / stats.requests) * 1000) / 1000
      : 0,
  };
}

export class StateStore {
  constructor(storage) {
    this.storage = storage;
  }

  async record(entry) {
    const seq = Number((await this.storage.get("seq")) || 0) + 1;
    await this.storage.put(`log:${padSeq(seq)}`, { ...entry, seq });
    await this.storage.put("seq", seq);

    if (seq > LOG_CAPACITY) {
      await this.storage.delete(`log:${padSeq(seq - LOG_CAPACITY)}`);
    }

    for (const [period, bucket] of Object.entries(periodKeys(entry.ts))) {
      const key = period === "total" ? "stats:total" : `stats:${period}:${bucket}`;
      const stats = (await this.storage.get(key)) || emptyStats(period, bucket);
      stats.requests += 1;
      entry.outcome === "ok" ? stats.success++ : stats.errors++;
      stats.requestBytes += Number(entry.request?.bytes || 0);
      stats.responseBytes += Number(entry.response?.bytes || 0);
      stats.durationMs += Number(entry.durationMs || 0);
      await this.storage.put(key, stats);
    }

    return seq;
  }

  async logs({ limit = 50, agent = "", rid = "", type = "all" } = {}) {
    limit = Math.max(1, Math.min(Number(limit) || 50, LOG_CAPACITY));
    const map = await this.storage.list({ prefix: "log:", reverse: true, limit: LOG_CAPACITY });
    let rows = [...map.values()];

    if (agent) rows = rows.filter(row => row.agent === agent);
    if (rid) rows = rows.filter(row => row.rid === rid);
    rows = rows.slice(0, limit);

    if (type === "meta") {
      return rows.map(({ request, response, ...meta }) => ({
        ...meta,
        status: response?.status ?? null,
        requestBytes: request?.bytes || 0,
        responseBytes: response?.bytes || 0,
      }));
    }
    if (type === "request") return rows.map(({ response, ...rest }) => rest);
    if (type === "response") return rows.map(({ request, ...rest }) => rest);
    return rows;
  }

  async stats(period = "day", limit = 31) {
    if (period === "total") {
      const value = await this.storage.get("stats:total");
      return value ? [summarizeStats(value)] : [];
    }

    if (!["day", "week", "month"].includes(period)) period = "day";
    limit = Math.max(1, Math.min(Number(limit) || 31, 366));
    const map = await this.storage.list({ prefix: `stats:${period}:`, reverse: true, limit });
    return [...map.values()].map(summarizeStats);
  }
}
