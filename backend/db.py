"""SQLite storage: RFQs (seeded from seed/rfqs.json) and past evaluations."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "app.db"
SEED_PATH = ROOT / "seed" / "rfqs.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS rfqs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    data TEXT NOT NULL              -- full RFQ as JSON
);
CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rfq_id TEXT NOT NULL REFERENCES rfqs(id),
    vendor_name TEXT NOT NULL,
    profile_text TEXT NOT NULL,
    score INTEGER NOT NULL,
    reasons TEXT NOT NULL,          -- JSON list (3)
    gaps TEXT NOT NULL,             -- JSON list (2)
    breakdown TEXT NOT NULL,        -- JSON: per-criterion verdicts + score maths
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)


def seed_rfqs() -> int:
    """Load seed/rfqs.json. Idempotent: re-running updates RFQs, keeps evaluations."""
    rfqs = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    with connect() as conn:
        for r in rfqs:
            conn.execute(
                "INSERT INTO rfqs (id, title, data) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET title=excluded.title, data=excluded.data",
                (r["id"], r["title"], json.dumps(r)),
            )
    return len(rfqs)


def list_rfqs() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT data FROM rfqs ORDER BY id").fetchall()
    return [json.loads(r["data"]) for r in rows]


def get_rfq(rfq_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT data FROM rfqs WHERE id = ?", (rfq_id,)).fetchone()
    return json.loads(row["data"]) if row else None


def save_evaluation(*, rfq_id, vendor_name, profile_text, score, reasons, gaps, breakdown, model) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO evaluations (rfq_id, vendor_name, profile_text, score, reasons, gaps, "
            "breakdown, model, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                rfq_id, vendor_name, profile_text, score,
                json.dumps(reasons), json.dumps(gaps), json.dumps(breakdown), model,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        return cur.lastrowid


def _row_to_eval(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in ("reasons", "gaps", "breakdown"):
        d[k] = json.loads(d[k])
    return d


def list_evaluations(limit: int = 50) -> list[dict]:
    """Most recent first. id DESC as tie-break (timestamps have 1s resolution)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT e.*, r.title AS rfq_title FROM evaluations e JOIN rfqs r ON r.id = e.rfq_id "
            "ORDER BY e.created_at DESC, e.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_eval(r) for r in rows]


def get_evaluation(eval_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT e.*, r.title AS rfq_title FROM evaluations e JOIN rfqs r ON r.id = e.rfq_id "
            "WHERE e.id = ?", (eval_id,),
        ).fetchone()
    return _row_to_eval(row) if row else None
