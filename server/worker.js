// Satsuma's anonymous user counter: a Cloudflare Worker with a D1 database.
//
//   POST /ping           {"id": "<random uuid>", "v": "<version>"}   from every running Satsuma (no secret)
//   GET  /stats          Authorization: Bearer <STATS_KEY>            the owner's numbers and charts
//   GET  /downloads.svg  public: a chart of GitHub downloads, shown in the README
//   every hour (cron)    saves GitHub's download totals
//
// Only the random id, the version and the days it was running are stored. Nothing else.

const REPO = "Elmozoop/Satsuma";
const ONLINE_SECONDS = 15 * 60;        // pings come every 10 minutes: online = seen in the last 15
const KEEP_DAYS = 120;
const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

// The tables (same as schema.sql). Created on first use, so a new or updated counter needs no SQL
// pasted by hand: deploying this file is enough. "IF NOT EXISTS" keeps existing data.
const SCHEMA = [
  "CREATE TABLE IF NOT EXISTS pings (id TEXT PRIMARY KEY, version TEXT, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL)",
  "CREATE INDEX IF NOT EXISTS pings_last_seen ON pings (last_seen)",
  "CREATE TABLE IF NOT EXISTS daily (day TEXT NOT NULL, id TEXT NOT NULL, version TEXT, PRIMARY KEY (day, id))",
  "CREATE TABLE IF NOT EXISTS downloads (at INTEGER PRIMARY KEY, total INTEGER NOT NULL, releases TEXT NOT NULL)",
];
let schemaReady = null;
function ensureSchema(env) {
  schemaReady ||= env.DB.batch(SCHEMA.map((sql) => env.DB.prepare(sql))).catch((error) => {
    schemaReady = null;          // try again on the next request
    throw error;
  });
  return schemaReady;
}

const dayOf = (seconds) => new Date(seconds * 1000).toISOString().slice(0, 10);

function lastDays(now, count) {
  const days = [];
  for (let i = count - 1; i >= 0; i--) days.push(dayOf(now - i * 86400));
  return days;
}

// "1.2k" -> 1200, as shields.io writes big numbers.
function shieldsNumber(text) {
  const match = String(text || "").trim().toLowerCase().match(/^([\d.]+)\s*([kmb]?)/);
  if (!match) return null;
  return Math.round(parseFloat(match[1]) * ({ "": 1, k: 1e3, m: 1e6, b: 1e9 })[match[2]]);
}

// GitHub's download counts per release. GitHub sometimes refuses requests without a login from
// Cloudflare's shared addresses; then the total comes from shields.io (what the README badge uses).
async function readDownloads(env) {
  const headers = { "User-Agent": "satsuma-stats", Accept: "application/vnd.github+json" };
  if (env.GITHUB_TOKEN) headers.Authorization = `Bearer ${env.GITHUB_TOKEN}`;   // optional
  const response = await fetch(`https://api.github.com/repos/${REPO}/releases?per_page=100`, { headers });
  if (response.ok) {
    const counts = {};
    let total = 0;
    for (const release of await response.json()) {
      const n = (release.assets || []).reduce((sum, asset) => sum + (asset.download_count || 0), 0);
      counts[release.tag_name] = n;
      total += n;
    }
    return { total, counts };
  }
  console.log(`GitHub said ${response.status}: ${(await response.text()).slice(0, 200)}`);
  const badge = await fetch(`https://img.shields.io/github/downloads/${REPO}/total.json`,
    { headers: { "User-Agent": "satsuma-stats" } });
  if (!badge.ok) {
    console.log(`shields.io said ${badge.status}`);
    return null;
  }
  const total = shieldsNumber((await badge.json()).message);
  return total === null ? null : { total, counts: {} };
}

async function saveDownloads(env) {
  const found = await readDownloads(env);
  if (!found) return;
  const { total, counts } = found;
  const now = Math.floor(Date.now() / 1000);
  await env.DB.prepare("INSERT OR REPLACE INTO downloads (at, total, releases) VALUES (?1, ?2, ?3)")
    .bind(now, total, JSON.stringify(counts)).run();
  await env.DB.prepare("DELETE FROM daily WHERE day < ?1").bind(dayOf(now - KEEP_DAYS * 86400)).run();
}

// The last saved total of each day, oldest first.
async function downloadsByDay(env, since) {
  const rows = await env.DB.prepare("SELECT at, total, releases FROM downloads WHERE at > ?1 ORDER BY at")
    .bind(since).all();
  const byDay = new Map();
  for (const row of rows.results || []) byDay.set(dayOf(row.at), row);
  return [...byDay.entries()].map(([day, row]) => ({ day, total: row.total, releases: JSON.parse(row.releases) }));
}

async function stats(env, now) {
  const one = (sql, ...args) => env.DB.prepare(sql).bind(...args).first("n");
  const all = async (sql, ...args) => (await env.DB.prepare(sql).bind(...args).all()).results || [];
  const days = lastDays(now, 30);

  const versions = await all(
    "SELECT version, COUNT(*) AS n FROM pings WHERE last_seen > ?1 GROUP BY version ORDER BY n DESC",
    now - 30 * 86400);
  const active = await all("SELECT day, COUNT(*) AS n FROM daily WHERE day >= ?1 GROUP BY day", days[0]);
  const adoption = await all(
    "SELECT day, version, COUNT(*) AS n FROM daily WHERE day >= ?1 GROUP BY day, version", days[0]);
  const fresh = await all(
    "SELECT first_seen / 86400 AS d, COUNT(*) AS n FROM pings WHERE first_seen > ?1 GROUP BY d",
    now - 30 * 86400);

  const activeMap = Object.fromEntries(active.map((r) => [r.day, r.n]));
  const freshMap = Object.fromEntries(fresh.map((r) => [dayOf(r.d * 86400), r.n]));
  const adoptionMap = {};
  for (const r of adoption) (adoptionMap[r.day] ||= {})[r.version || "?"] = r.n;

  return {
    online: await one("SELECT COUNT(*) AS n FROM pings WHERE last_seen > ?1", now - ONLINE_SECONDS),
    today: await one("SELECT COUNT(*) AS n FROM pings WHERE last_seen > ?1", now - 86400),
    month: await one("SELECT COUNT(*) AS n FROM pings WHERE last_seen > ?1", now - 30 * 86400),
    installs: await one("SELECT COUNT(*) AS n FROM pings"),
    versions: Object.fromEntries(versions.map((r) => [r.version || "?", r.n])),
    days: days.map((day) => ({
      day,
      active: activeMap[day] || 0,
      new: freshMap[day] || 0,
      versions: adoptionMap[day] || {},
    })),
    downloads: (await downloadsByDay(env, now - 30 * 86400)).map(({ day, total }) => ({ day, total })),
    at: now,
  };
}

// ----------------------------------------------------------------------------- the public chart
const escape = (text) => String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

async function downloadsSvg(env, now) {
  const W = 760, H = 300, left = 52, right = 20, top = 54, bottom = 40;
  let series = await downloadsByDay(env, now - 90 * 86400);
  if (!series.length) {            // nothing saved yet (a new counter): take today's numbers now
    await saveDownloads(env);
    series = await downloadsByDay(env, now - 90 * 86400);
  }
  const latest = series.length ? series[series.length - 1] : null;
  const total = latest ? latest.total : 0;
  const ink = "#8b949e", accent = "#f97316";
  const parts = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="Segoe UI, -apple-system, Helvetica, Arial, sans-serif">`,
    `<text x="${left}" y="26" font-size="16" font-weight="600" fill="${accent}">Satsuma downloads</text>`,
    `<text x="${W - right}" y="26" font-size="14" text-anchor="end" fill="${ink}">${total.toLocaleString("en-US")} in total</text>`,
  ];
  const plotW = W - left - right, plotH = H - top - bottom;

  if (series.length >= 2) {
    // Daily new downloads as bars, the running total as a line.
    const daily = series.map((p, i) => Math.max(0, i ? p.total - series[i - 1].total : 0));
    const maxDaily = Math.max(1, ...daily), maxTotal = Math.max(1, ...series.map((p) => p.total));
    const step = plotW / series.length;
    series.forEach((p, i) => {
      const h = (daily[i] / maxDaily) * plotH * 0.6;
      parts.push(`<rect x="${(left + i * step + step * 0.15).toFixed(1)}" y="${(top + plotH - h).toFixed(1)}" width="${(step * 0.7).toFixed(1)}" height="${h.toFixed(1)}" rx="2" fill="${accent}" opacity="0.35"><title>${p.day}: ${daily[i]} downloads</title></rect>`);
    });
    const points = series.map((p, i) =>
      `${(left + i * step + step / 2).toFixed(1)},${(top + plotH - (p.total / maxTotal) * plotH).toFixed(1)}`).join(" ");
    parts.push(`<polyline points="${points}" fill="none" stroke="${accent}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`);
    for (const [frac, label] of [[0, "0"], [0.5, Math.round(maxTotal / 2)], [1, maxTotal]]) {
      const y = top + plotH - frac * plotH;
      parts.push(`<line x1="${left}" x2="${W - right}" y1="${y}" y2="${y}" stroke="${ink}" stroke-opacity="0.2"/>`);
      parts.push(`<text x="${left - 8}" y="${y + 4}" font-size="11" text-anchor="end" fill="${ink}">${escape(Number(label).toLocaleString("en-US"))}</text>`);
    }
    parts.push(`<text x="${left}" y="${H - 14}" font-size="11" fill="${ink}">${series[0].day}</text>`);
    parts.push(`<text x="${W - right}" y="${H - 14}" font-size="11" text-anchor="end" fill="${ink}">${series[series.length - 1].day}</text>`);
    parts.push(`<text x="${left}" y="44" font-size="11" fill="${ink}">— total downloads   ▮ downloads per day</text>`);
  } else {
    // Not enough history yet: downloads of each release.
    const releases = latest ? Object.entries(latest.releases).reverse().slice(-12) : [];
    if (!releases.length) {
      parts.push(`<text x="${W / 2}" y="${top + plotH / 2 + 10}" font-size="44" font-weight="700" text-anchor="middle" fill="${accent}">${total.toLocaleString("en-US")}</text>`);
      parts.push(`<text x="${W / 2}" y="${top + plotH / 2 + 40}" font-size="13" text-anchor="middle" fill="${ink}">downloads so far · the day-by-day chart appears after a couple of days</text>`);
      parts.push("</svg>");
      return new Response(parts.join(""), {
        headers: { "Content-Type": "image/svg+xml; charset=utf-8", "Cache-Control": "public, max-age=3600" },
      });
    }
    const max = Math.max(1, ...releases.map(([, n]) => n));
    const step = plotW / Math.max(1, releases.length);
    releases.forEach(([tag, n], i) => {
      const h = (n / max) * (plotH - 18);
      const x = left + i * step + step * 0.2;
      parts.push(`<rect x="${x.toFixed(1)}" y="${(top + plotH - h).toFixed(1)}" width="${(step * 0.6).toFixed(1)}" height="${h.toFixed(1)}" rx="3" fill="${accent}"/>`);
      parts.push(`<text x="${(x + step * 0.3).toFixed(1)}" y="${(top + plotH - h - 6).toFixed(1)}" font-size="11" text-anchor="middle" fill="${ink}">${n}</text>`);
      parts.push(`<text x="${(x + step * 0.3).toFixed(1)}" y="${H - 14}" font-size="11" text-anchor="middle" fill="${ink}">${escape(tag)}</text>`);
    });
    parts.push(`<text x="${left}" y="44" font-size="11" fill="${ink}">Downloads of each release (the day-by-day chart appears after a couple of days)</text>`);
  }
  parts.push("</svg>");
  return new Response(parts.join(""), {
    headers: { "Content-Type": "image/svg+xml; charset=utf-8", "Cache-Control": "public, max-age=3600" },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const now = Math.floor(Date.now() / 1000);
    await ensureSchema(env);

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
      await env.DB.batch([
        env.DB.prepare(
          "INSERT INTO pings (id, version, first_seen, last_seen) VALUES (?1, ?2, ?3, ?3) " +
          "ON CONFLICT(id) DO UPDATE SET version = ?2, last_seen = ?3").bind(id, version, now),
        env.DB.prepare("INSERT OR REPLACE INTO daily (day, id, version) VALUES (?1, ?2, ?3)")
          .bind(dayOf(now), id, version),
      ]);
      return new Response(null, { status: 204 });
    }

    if (request.method === "GET" && url.pathname === "/stats") {
      if (!env.STATS_KEY || request.headers.get("Authorization") !== `Bearer ${env.STATS_KEY}`) {
        return new Response("not allowed", { status: 401 });
      }
      return Response.json(await stats(env, now));
    }

    if (request.method === "GET" && url.pathname === "/downloads.svg") {
      return downloadsSvg(env, now);
    }

    return new Response("Satsuma counter", { status: 404 });
  },

  async scheduled(_event, env, ctx) {
    ctx.waitUntil(ensureSchema(env).then(() => saveDownloads(env)));
  },
};
