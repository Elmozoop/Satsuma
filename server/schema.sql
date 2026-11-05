-- The only table: one row per Satsuma install (a random id), and when it was last running.
CREATE TABLE IF NOT EXISTS pings (
  id TEXT PRIMARY KEY,
  version TEXT,
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS pings_last_seen ON pings (last_seen);
