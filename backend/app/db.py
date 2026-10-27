import json
import os
import sqlite3
import threading
from pathlib import Path

# backend/.env (KEY=VALUE per line); variables already set in the environment win
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "app.db"

_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.execute("PRAGMA journal_mode=WAL")

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- one row per scheduled-job execution
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  log TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS runs_job ON runs(job, id DESC);

-- trade-board posts seen in the list pages (one row per post id)
CREATE TABLE IF NOT EXISTS trade_posts (
  post_id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  author TEXT NOT NULL DEFAULT '',
  views INTEGER NOT NULL DEFAULT 0,
  replies INTEGER NOT NULL DEFAULT 0,
  first_seen TEXT NOT NULL,           -- YYYY-MM-DD, the night it was first scraped
  last_seen TEXT NOT NULL,
  signal INTEGER NOT NULL DEFAULT 0,  -- title looks like a deal (rule pre-screen)
  content TEXT,                       -- detail body, only fetched for signal posts
  posted_at TEXT,
  edited_at TEXT,
  merchant TEXT,
  model TEXT,
  side TEXT,                          -- sell / buy
  premium REAL,                       -- in original currency; NULL = not stated
  currency TEXT,
  premium_cny REAL,
  premium_est INTEGER NOT NULL DEFAULT 0,  -- 1 = premium worked out from price − remaining value
  price REAL,                         -- asking price as written (total), original currency
  price_cny REAL,
  discount REAL,
  is_deal INTEGER NOT NULL DEFAULT 0,
  deal_date TEXT,
  llm_note TEXT,
  llm_title TEXT                      -- title the LLM last saw; re-run when it changes
);
CREATE INDEX IF NOT EXISTS trade_first_seen ON trade_posts(first_seen);
CREATE INDEX IF NOT EXISTS trade_deal ON trade_posts(is_deal, deal_date);

-- titles collected from RSS for the heat analysis
CREATE TABLE IF NOT EXISTS topics (
  post_id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT '',
  author TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL,
  fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS topics_pub ON topics(published_at);

CREATE TABLE IF NOT EXISTS hot_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  win TEXT NOT NULL,                  -- 1h / 24h
  created_at TEXT NOT NULL,
  post_count INTEGER NOT NULL,
  keywords TEXT NOT NULL,             -- JSON [{word, heat, count, post_ids}]
  summary TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS hot_win ON hot_snapshots(win, id DESC);

-- LLM-written posts / comments waiting for the user to publish
CREATE TABLE IF NOT EXISTS drafts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,                 -- post / comment
  target_id INTEGER,                  -- post id being commented on
  target_title TEXT,
  category TEXT,
  title TEXT,
  content TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '',    -- what it was written from (news link / keyword)
  status TEXT NOT NULL DEFAULT 'pending',  -- pending / published / discarded / failed
  result TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  published_at TEXT
);
CREATE INDEX IF NOT EXISTS drafts_status ON drafts(status, id DESC);

CREATE TABLE IF NOT EXISTS checkins (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day TEXT NOT NULL,
  at TEXT NOT NULL,
  ok INTEGER NOT NULL,
  message TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  module TEXT NOT NULL,
  text TEXT NOT NULL,
  ok INTEGER NOT NULL,
  error TEXT NOT NULL DEFAULT ''
);
"""
# columns added after the first release: add them to existing databases
MIGRATIONS = {
    "trade_posts": [("premium_est", "INTEGER NOT NULL DEFAULT 0"), ("price", "REAL"), ("price_cny", "REAL")],
}

with _lock:
    _conn.executescript(SCHEMA)
    for _table, _cols in MIGRATIONS.items():
        _have = {r[1] for r in _conn.execute(f"PRAGMA table_info({_table})")}
        for _name, _type in _cols:
            if _name not in _have:
                _conn.execute(f"ALTER TABLE {_table} ADD COLUMN {_name} {_type}")
    _conn.commit()


def q(sql, args=()):
    with _lock:
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


def one(sql, args=()):
    rows = q(sql, args)
    return rows[0] if rows else None


def ex(sql, args=()):
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur.lastrowid


def get_setting(key, default=None):
    r = one("SELECT value FROM settings WHERE key=?", (key,))
    return json.loads(r["value"]) if r else default


def set_setting(key, value):
    ex(
        "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )


def many(sql, rows):
    with _lock:
        _conn.executemany(sql, rows)
        _conn.commit()
