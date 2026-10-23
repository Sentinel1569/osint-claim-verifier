"""SQLite persistence for cases, sources, claims and statements."""

from __future__ import annotations

import json
import os
import sqlite3

from .evidence import utcnow

DB_PATH = os.environ.get("CLAIMBENCH_DB", "claimbench.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT DEFAULT '', created TEXT);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                  -- official | news | factcheck | social | archive | image | document | other
    url TEXT DEFAULT '', title TEXT DEFAULT '', publisher TEXT DEFAULT '', author TEXT DEFAULT '',
    published TEXT DEFAULT '', modified TEXT DEFAULT '', retrieved_at TEXT, sha256 TEXT DEFAULT '',
    reliability TEXT DEFAULT 'F', credibility INTEGER DEFAULT 6,
    text TEXT DEFAULT '', archive TEXT DEFAULT '{}', image TEXT DEFAULT '{}', note TEXT DEFAULT '', created TEXT
);
CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    text TEXT NOT NULL, event_date TEXT DEFAULT '', created TEXT
);
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY, claim_id INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    stance TEXT NOT NULL,                -- supports | refutes | attributes | mentions
    quote TEXT DEFAULT '', value TEXT DEFAULT '', note TEXT DEFAULT '', created TEXT,
    UNIQUE(claim_id, source_id)
);
"""
STANCES = ("supports", "refutes", "attributes", "mentions")
KINDS = ("official", "news", "factcheck", "social", "archive", "image", "document", "other")


class Store:
    def __init__(self, path: str | None = None):
        self.con = sqlite3.connect(path or DB_PATH, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        self.con.executescript(SCHEMA)

    def _ins(self, table: str, **cols) -> int:
        with self.con:
            cur = self.con.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", tuple(cols.values()))
        return cur.lastrowid

    # cases
    def add_case(self, title: str, description: str = "") -> int:
        return self._ins("cases", title=title, description=description, created=utcnow())

    def cases(self) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM claims WHERE case_id=c.id) claims, (SELECT COUNT(*) FROM sources WHERE case_id=c.id) sources "
            "FROM cases c ORDER BY id DESC")]

    def case(self, cid: int) -> dict | None:
        r = self.con.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
        return dict(r) if r else None

    def delete_case(self, cid: int) -> None:
        with self.con:
            self.con.execute("DELETE FROM cases WHERE id=?", (cid,))

    # sources
    def add_source(self, case_id: int, kind: str, **f) -> int:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        for k in ("archive", "image"):
            if k in f and not isinstance(f[k], str):
                f[k] = json.dumps(f[k])
        return self._ins("sources", case_id=case_id, kind=kind, created=utcnow(), retrieved_at=f.pop("retrieved_at", utcnow()), **f)

    def update_source(self, sid: int, **f) -> None:
        allowed = {"reliability", "credibility", "note", "kind", "title", "publisher", "published", "archive"}
        f = {k: (json.dumps(v) if k == "archive" and not isinstance(v, str) else v) for k, v in f.items() if k in allowed}
        if f:
            with self.con:
                self.con.execute(f"UPDATE sources SET {', '.join(f'{k}=?' for k in f)} WHERE id=?", (*f.values(), sid))

    def sources(self, case_id: int) -> list[dict]:
        out = []
        for r in self.con.execute("SELECT * FROM sources WHERE case_id=? ORDER BY published, id", (case_id,)):
            d = dict(r)
            d["archive"] = json.loads(d["archive"] or "{}")
            d["image"] = json.loads(d["image"] or "{}")
            out.append(d)
        return out

    def delete_source(self, sid: int) -> None:
        with self.con:
            self.con.execute("DELETE FROM sources WHERE id=?", (sid,))

    # claims & statements
    def add_claim(self, case_id: int, text: str, event_date: str = "") -> int:
        return self._ins("claims", case_id=case_id, text=text, event_date=event_date, created=utcnow())

    def claims(self, case_id: int) -> list[dict]:
        return [dict(r) for r in self.con.execute("SELECT * FROM claims WHERE case_id=? ORDER BY id", (case_id,))]

    def delete_claim(self, cid: int) -> None:
        with self.con:
            self.con.execute("DELETE FROM claims WHERE id=?", (cid,))

    def set_statement(self, claim_id: int, source_id: int, stance: str, quote: str = "", value: str = "", note: str = "") -> None:
        if stance not in STANCES + ("none",):
            raise ValueError(f"stance must be one of {', '.join(STANCES)} or none")
        with self.con:
            if stance == "none":
                self.con.execute("DELETE FROM statements WHERE claim_id=? AND source_id=?", (claim_id, source_id))
            else:
                self.con.execute("INSERT INTO statements (claim_id, source_id, stance, quote, value, note, created) VALUES (?,?,?,?,?,?,?) "
                                 "ON CONFLICT(claim_id, source_id) DO UPDATE SET stance=excluded.stance, quote=excluded.quote, "
                                 "value=excluded.value, note=excluded.note",
                                 (claim_id, source_id, stance, quote, value, note, utcnow()))

    def statements(self, case_id: int) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT s.* FROM statements s JOIN claims c ON c.id = s.claim_id WHERE c.case_id=? ORDER BY s.id", (case_id,))]
