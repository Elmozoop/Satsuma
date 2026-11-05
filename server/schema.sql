/* Satsuma's user counter. Safe to run again: it only creates what's missing.
   pings: one row per install (a random id), and when it was first and last running.
   daily: which installs were running on each day (UTC), for the daily charts; kept 120 days.
   downloads: GitHub's download totals, saved every hour, for the downloads chart.
   (Block comments, so it still works when the dashboard console puts it all on one line.) */
CREATE TABLE IF NOT EXISTS pings (id TEXT PRIMARY KEY, version TEXT, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS pings_last_seen ON pings (last_seen);
CREATE TABLE IF NOT EXISTS daily (day TEXT NOT NULL, id TEXT NOT NULL, version TEXT, PRIMARY KEY (day, id));
CREATE TABLE IF NOT EXISTS downloads (at INTEGER PRIMARY KEY, total INTEGER NOT NULL, releases TEXT NOT NULL);
