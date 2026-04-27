-- Initial schema (mirror of schema.sql).
PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS files (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  rel_path      TEXT    NOT NULL UNIQUE,
  name          TEXT    NOT NULL,
  ext           TEXT    NOT NULL,
  size_bytes    INTEGER NOT NULL,
  mtime_ns      INTEGER NOT NULL,
  added_at      INTEGER NOT NULL,
  width         INTEGER,
  height        INTEGER,
  thumb_hash    TEXT,
  tags_json     TEXT    DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_files_name  ON files(name);
CREATE INDEX IF NOT EXISTS idx_files_mtime ON files(mtime_ns);
CREATE INDEX IF NOT EXISTS idx_files_ext   ON files(ext);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_state (
  id            INTEGER PRIMARY KEY CHECK (id = 1),
  last_scan_ns  INTEGER NOT NULL,
  file_count    INTEGER NOT NULL
);
