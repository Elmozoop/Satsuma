# Satsuma's user counter

A tiny Cloudflare Worker that counts how many people run Satsuma. Each running copy sends an
anonymous ping every 10 minutes (a random ID made on that PC, plus the version); the owner's
**Stats** window reads the totals with a private key. Cloudflare's free plan is plenty.

Everything below happens in the Cloudflare website; nothing to install.

## 1. Create the database
1. Sign up or log in at <https://dash.cloudflare.com>.
2. **Storage & Databases → D1 SQL Database → Create**. Name it `satsuma-stats`.
3. Open it → **Console**, paste everything from [`schema.sql`](schema.sql), and press **Execute**.

## 2. Create the Worker
1. **Compute (Workers) → Workers & Pages → Create → Create Worker**. Name it `satsuma-stats`, **Deploy**.
2. **Edit code**: replace everything with [`worker.js`](worker.js), then **Deploy**.
3. Back on the Worker: **Settings → Bindings → Add → D1 database**. Variable name `DB`,
   database `satsuma-stats`. Save.
4. **Settings → Variables and Secrets → Add**: type **Secret**, name `STATS_KEY`, value: the
   `key` from your `%LOCALAPPDATA%\Satsuma\owner.json`. Save and deploy.
5. Copy the Worker's address from its overview page. It looks like
   `https://satsuma-stats.<your-name>.workers.dev`.

## 3. Save GitHub downloads every hour
On the Worker: **Settings → Trigger events → Add → Cron trigger**, enter `0 * * * *` (every hour) and
save. This saves GitHub's download totals for the downloads chart.

## 4. Connect Satsuma
Send that address to whoever builds Satsuma (or put it in `STATS_URL` in `satsuma/config.py`
yourself and rebuild). Until it's set, Satsuma sends nothing.

## Updating an existing counter
When `worker.js` or `schema.sql` change: paste `schema.sql` into the database's **Console** and
**Execute** again (it only adds what's missing, nothing is lost), then **Edit code** on the Worker,
paste the new `worker.js` and **Deploy**.

## Check it
- Open the address in a browser: it should say **Satsuma counter**.
- `/downloads.svg` on that address is the public downloads chart shown in the main README.
- On the owner's PC: right-click the 🍊 → **Stats…** shows *online now*, the last 24 hours and 30
  days, installs ever, charts of people using Satsuma each day and which versions they run, and
  downloads per release and over time.

## What's stored
- One row per install: the random ID, the Satsuma version, and when it was first and last seen.
- One row per install per day it was running (the random ID and version), kept for 120 days, for
  the daily charts.
- GitHub's public download totals, every hour.

No IP addresses, names, file information or anything else.
