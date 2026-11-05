-- Satsuma's user counter. Safe to run again: it only creates what's missing.

-- One row per Satsuma install (a random id), and when it was first and last running.
CREATE TABLE IF NOT EXISTS pings (
  id TEXT PRIMARY KEY,
  version TEXT,
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS pings_last_seen ON pings (last_seen);

-- Which installs were running on each day (UTC), for the daily-users and version charts.
-- Rows older than 120 days are deleted.
CREATE TABLE IF NOT EXISTS daily (
  day TEXT NOT NULL,          -- YYYY-MM-DD
  id TEXT NOT NULL,
  version TEXT,
  PRIMARY KEY (day, id)
);

-- GitHub's download totals, saved every hour, for the downloads chart.
CREATE TABLE IF NOT EXISTS downloads (
  at INTEGER PRIMARY KEY,     -- unix time
  total INTEGER NOT NULL,
  releases TEXT NOT NULL      -- JSON: {"v1.15.1": 12, ...}
);
