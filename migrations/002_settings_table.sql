-- Create a simple key/value Settings table (SQLite/Postgres friendly)
CREATE TABLE IF NOT EXISTS Settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
