"""SQLite index living inside the photo library at .pcull/index.db."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
  id INTEGER PRIMARY KEY,
  rel_path TEXT UNIQUE NOT NULL,
  filename TEXT NOT NULL,
  ext TEXT NOT NULL,
  size INTEGER NOT NULL,
  mtime REAL NOT NULL,
  width INTEGER,
  height INTEGER,
  taken_at REAL,
  is_video INTEGER NOT NULL DEFAULT 0,
  duration REAL,
  phash TEXT,
  analyzed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_photos_taken ON photos(taken_at);

CREATE TABLE IF NOT EXISTS metrics (
  photo_id INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
  blur REAL,          -- 0-100, higher = sharper
  blur_raw REAL,      -- raw laplacian variance for debugging
  exposure REAL,      -- 0-100, higher = balanced
  under REAL,         -- fraction of clipped shadows
  over REAL,          -- fraction of clipped highlights
  colorfulness REAL,  -- 0-100
  faces INTEGER,      -- number of detected faces, NULL if analyzer unavailable
  eye_open_min REAL,  -- 1 - max(eyeBlink) over faces, NULL if no faces/analyzer
  closed_eye INTEGER, -- 1 if any face has a clear blink
  score REAL,         -- composite 0-100
  recommendation TEXT,-- keep | review | delete
  reasons TEXT        -- JSON array of Chinese reason labels
);

CREATE TABLE IF NOT EXISTS groups (
  group_id INTEGER NOT NULL,
  photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
  distance INTEGER,   -- phash hamming distance to group representative
  PRIMARY KEY (group_id, photo_id)
);

CREATE TABLE IF NOT EXISTS decisions (
  photo_id INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
  decision TEXT NOT NULL CHECK (decision IN ('keep','delete')),
  decided_at REAL NOT NULL
);
"""

TRASH_DIRNAME = "_pcull_trash"


def connect(library: Path) -> sqlite3.Connection:
    library = Path(library)
    db_dir = library / ".pcull"
    db_dir.mkdir(exist_ok=True)
    conn = sqlite3.connect(db_dir / "index.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
