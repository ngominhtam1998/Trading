"""SQLite state persistence for the live bot.

Tables:
- positions   : currently-open positions managed by the bot (metadata not
                derivable from the exchange: orig SL %, BE/trail flags, entry time, score).
- closed      : closed trade history (audit/PnL).
- events      : append-only event log (entries, exits, errors, reconciliation actions).

The exchange is the source of truth for WHAT positions exist; this DB stores the
EXTRA metadata the bot needs to keep managing them (and a full audit trail).

WAL mode + synchronous=NORMAL gives crash-safety: a kill mid-write won't corrupt
the DB; at worst the last uncommitted transaction is lost.
"""
import sqlite3
import time
import json
import threading


class StateDB:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS positions (
                symbol        TEXT PRIMARY KEY,
                direction     TEXT NOT NULL,
                entry_price   REAL NOT NULL,
                qty           REAL NOT NULL,
                leverage      INTEGER NOT NULL,
                orig_sl_pct   REAL NOT NULL,
                sl_price      REAL NOT NULL,
                tp_price      REAL NOT NULL,
                be_moved      INTEGER DEFAULT 0,
                trail_moved   INTEGER DEFAULT 0,
                entry_time    INTEGER NOT NULL,   -- ms epoch
                score         INTEGER,
                margin        REAL,
                sl_client_id  TEXT,
                tp_client_id  TEXT,
                entry_client_id TEXT,
                adopted       INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS closed (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol        TEXT,
                direction     TEXT,
                entry_price   REAL,
                exit_price    REAL,
                qty           REAL,
                pnl           REAL,
                reason        TEXT,
                entry_time    INTEGER,
                exit_time     INTEGER
            );
            CREATE TABLE IF NOT EXISTS events (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                ts     INTEGER,
                kind   TEXT,
                symbol TEXT,
                detail TEXT
            );
            CREATE TABLE IF NOT EXISTS kv (
                k TEXT PRIMARY KEY,
                v TEXT
            );
            """)
            self.conn.commit()

    # ---------- positions ----------
    def upsert_position(self, pos: dict):
        with self._lock:
            self.conn.execute("""
                INSERT INTO positions (symbol, direction, entry_price, qty, leverage,
                    orig_sl_pct, sl_price, tp_price, be_moved, trail_moved, entry_time,
                    score, margin, sl_client_id, tp_client_id, entry_client_id, adopted)
                VALUES (:symbol, :direction, :entry_price, :qty, :leverage,
                    :orig_sl_pct, :sl_price, :tp_price, :be_moved, :trail_moved, :entry_time,
                    :score, :margin, :sl_client_id, :tp_client_id, :entry_client_id, :adopted)
                ON CONFLICT(symbol) DO UPDATE SET
                    direction=excluded.direction, entry_price=excluded.entry_price,
                    qty=excluded.qty, leverage=excluded.leverage, orig_sl_pct=excluded.orig_sl_pct,
                    sl_price=excluded.sl_price, tp_price=excluded.tp_price,
                    be_moved=excluded.be_moved, trail_moved=excluded.trail_moved,
                    entry_time=excluded.entry_time, score=excluded.score, margin=excluded.margin,
                    sl_client_id=excluded.sl_client_id, tp_client_id=excluded.tp_client_id,
                    entry_client_id=excluded.entry_client_id, adopted=excluded.adopted
            """, {
                "symbol": pos["symbol"], "direction": pos["direction"],
                "entry_price": pos["entry_price"], "qty": pos["qty"],
                "leverage": pos["leverage"], "orig_sl_pct": pos["orig_sl_pct"],
                "sl_price": pos["sl_price"], "tp_price": pos["tp_price"],
                "be_moved": int(pos.get("be_moved", 0)), "trail_moved": int(pos.get("trail_moved", 0)),
                "entry_time": pos["entry_time"], "score": pos.get("score"),
                "margin": pos.get("margin"), "sl_client_id": pos.get("sl_client_id"),
                "tp_client_id": pos.get("tp_client_id"), "entry_client_id": pos.get("entry_client_id"),
                "adopted": int(pos.get("adopted", 0)),
            })
            self.conn.commit()

    def update_position_fields(self, symbol, **fields):
        if not fields:
            return
        with self._lock:
            cols = ", ".join(f"{k}=?" for k in fields)
            vals = list(fields.values()) + [symbol]
            self.conn.execute(f"UPDATE positions SET {cols} WHERE symbol=?", vals)
            self.conn.commit()

    def get_position(self, symbol):
        cur = self.conn.execute("SELECT * FROM positions WHERE symbol=?", (symbol,))
        row = cur.fetchone()
        return dict(row) if row else None

    def all_positions(self):
        cur = self.conn.execute("SELECT * FROM positions")
        return [dict(r) for r in cur.fetchall()]

    def delete_position(self, symbol):
        with self._lock:
            self.conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
            self.conn.commit()

    # ---------- closed trades ----------
    def record_closed(self, symbol, direction, entry_price, exit_price, qty, pnl, reason,
                      entry_time, exit_time=None):
        with self._lock:
            self.conn.execute("""
                INSERT INTO closed (symbol, direction, entry_price, exit_price, qty, pnl,
                    reason, entry_time, exit_time)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (symbol, direction, entry_price, exit_price, qty, pnl, reason,
                  entry_time, exit_time or int(time.time() * 1000)))
            self.conn.commit()

    # ---------- events ----------
    def log_event(self, kind, symbol="", detail=""):
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail)
        with self._lock:
            self.conn.execute("INSERT INTO events (ts, kind, symbol, detail) VALUES (?,?,?,?)",
                             (int(time.time() * 1000), kind, symbol, str(detail)))
            self.conn.commit()

    # ---------- kv (misc state, e.g. daily_halt) ----------
    def set_kv(self, k, v):
        with self._lock:
            self.conn.execute("INSERT INTO kv (k,v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                             (k, json.dumps(v)))
            self.conn.commit()

    def get_kv(self, k, default=None):
        cur = self.conn.execute("SELECT v FROM kv WHERE k=?", (k,))
        row = cur.fetchone()
        return json.loads(row["v"]) if row else default

    def close(self):
        self.conn.close()
