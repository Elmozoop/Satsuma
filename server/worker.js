// Satsuma's anonymous user counter: a Cloudflare Worker with a D1 database.
//
//   POST /ping   {"id": "<random uuid>", "v": "<version>"}   from every running Satsuma (no secret)
//   GET  /stats  Authorization: Bearer <STATS_KEY>            the owner's numbers
//
// Only the random id, the version and when it was first/last seen are stored. Nothing else.

const ONLINE_SECONDS = 15 * 60;        // pings come every 10 minutes: online = seen in the last 15
const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const now = Math.floor(Date.now() / 1000);

    if (request.method === "POST" && url.pathname === "/ping") {
      let body;
      try {
        body = await request.json();
      } catch {
        return new Response("bad request", { status: 400 });
      }
      const id = String(body.id || "").toLowerCase();
      const version = String(body.v || "").slice(0, 20);
      if (!ID.test(id)) return new Response("bad request", { status: 400 });
      await env.DB.prepare(
        "INSERT INTO pings (id, version, first_seen, last_seen) VALUES (?1, ?2, ?3, ?3) " +
        "ON CONFLICT(id) DO UPDATE SET version = ?2, last_seen = ?3"
      ).bind(id, version, now).run();
      return new Response(null, { status: 204 });
    }

    if (request.method === "GET" && url.pathname === "/stats") {
      if (!env.STATS_KEY || request.headers.get("Authorization") !== `Bearer ${env.STATS_KEY}`) {
        return new Response("not allowed", { status: 401 });
      }
      const one = (sql, ...args) => env.DB.prepare(sql).bind(...args).first("n");
      const online = await one("SELECT COUNT(*) AS n FROM pings WHERE last_seen > ?1", now - ONLINE_SECONDS);
      const today = await one("SELECT COUNT(*) AS n FROM pings WHERE last_seen > ?1", now - 86400);
      const month = await one("SELECT COUNT(*) AS n FROM pings WHERE last_seen > ?1", now - 30 * 86400);
      const installs = await one("SELECT COUNT(*) AS n FROM pings");
      const versions = await env.DB.prepare(
        "SELECT version, COUNT(*) AS n FROM pings WHERE last_seen > ?1 GROUP BY version ORDER BY n DESC"
      ).bind(now - 30 * 86400).all();
      return Response.json({
        online, today, month, installs,
        versions: Object.fromEntries((versions.results || []).map((r) => [r.version || "?", r.n])),
        at: now,
      });
    }

    return new Response("Satsuma counter", { status: 404 });
  },
};
