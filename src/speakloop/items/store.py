"""SQLite-backed store for learning items and their uses (stdlib sqlite3 only)."""

import builtins
import json
import sqlite3
from pathlib import Path
from types import TracebackType
from typing import Self

from speakloop.models import Evidence, Item, ItemKind, ItemStatus, ItemUse

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    key TEXT NOT NULL UNIQUE,
    front TEXT NOT NULL,
    back TEXT NOT NULL,
    examples TEXT NOT NULL,
    source_finding_ids TEXT NOT NULL,
    status TEXT NOT NULL,
    uses_correct INTEGER NOT NULL DEFAULT 0,
    uses_incorrect INTEGER NOT NULL DEFAULT 0,
    last_seen_session TEXT
);
CREATE TABLE IF NOT EXISTS item_uses (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items(id),
    session_id TEXT NOT NULL,
    correct INTEGER NOT NULL,
    evidence TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_item_uses_item ON item_uses(item_id);
"""

_COLUMNS = (
    "id, kind, key, front, back, examples, source_finding_ids, status, "
    "uses_correct, uses_incorrect, last_seen_session"
)


def _merge(old: tuple[str, ...], new: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*old, *new)))


def _row_to_item(row: sqlite3.Row) -> Item:
    return Item(
        id=row["id"],
        kind=ItemKind(row["kind"]),
        key=row["key"],
        front=row["front"],
        back=row["back"],
        examples=tuple(json.loads(row["examples"])),
        source_finding_ids=tuple(json.loads(row["source_finding_ids"])),
        status=ItemStatus(row["status"]),
        uses_correct=row["uses_correct"],
        uses_incorrect=row["uses_incorrect"],
        last_seen_session=row["last_seen_session"],
    )


class ItemStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            self._conn.close()
            raise RuntimeError(f"unsupported item store schema version {version}")
        with self._conn:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def upsert(self, item: Item) -> Item:
        """Insert the item, or merge it into the existing one with the same key.

        On merge the existing id, status, counters and last_seen_session are kept; examples
        and source_finding_ids are unioned without duplicates.
        """
        with self._conn:
            existing = self.get_by_key(item.key)
            if existing is None:
                self._conn.execute(
                    f"INSERT INTO items ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item.id,
                        item.kind.value,
                        item.key,
                        item.front,
                        item.back,
                        json.dumps(item.examples),
                        json.dumps(item.source_finding_ids),
                        item.status.value,
                        item.uses_correct,
                        item.uses_incorrect,
                        item.last_seen_session,
                    ),
                )
                return item
            merged = existing.model_copy(
                update={
                    "examples": _merge(existing.examples, item.examples),
                    "source_finding_ids": _merge(
                        existing.source_finding_ids, item.source_finding_ids
                    ),
                }
            )
            self._conn.execute(
                "UPDATE items SET examples = ?, source_finding_ids = ? WHERE id = ?",
                (json.dumps(merged.examples), json.dumps(merged.source_finding_ids), merged.id),
            )
            return merged

    def get(self, item_id: str) -> Item | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        return None if row is None else _row_to_item(row)

    def get_by_key(self, key: str) -> Item | None:
        row = self._conn.execute(f"SELECT {_COLUMNS} FROM items WHERE key = ?", (key,)).fetchone()
        return None if row is None else _row_to_item(row)

    def list(self, status: ItemStatus | None = None) -> list[Item]:
        if status is None:
            rows = self._conn.execute(f"SELECT {_COLUMNS} FROM items ORDER BY key").fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT {_COLUMNS} FROM items WHERE status = ? ORDER BY key", (status.value,)
            ).fetchall()
        return [_row_to_item(r) for r in rows]

    def record_use(self, use: ItemUse) -> None:
        with self._conn:
            if self.get(use.item_id) is None:
                raise KeyError(f"unknown item id: {use.item_id}")
            column = "uses_correct" if use.correct else "uses_incorrect"
            self._conn.execute(
                f"UPDATE items SET {column} = {column} + 1, last_seen_session = ? WHERE id = ?",
                (use.session_id, use.item_id),
            )
            self._conn.execute(
                "INSERT INTO item_uses (item_id, session_id, correct, evidence) "
                "VALUES (?, ?, ?, ?)",
                (use.item_id, use.session_id, int(use.correct), use.evidence.model_dump_json()),
            )

    def uses(self, item_id: str) -> builtins.list[ItemUse]:
        rows = self._conn.execute(
            "SELECT item_id, session_id, correct, evidence FROM item_uses "
            "WHERE item_id = ? ORDER BY rowid",
            (item_id,),
        ).fetchall()
        return [
            ItemUse(
                item_id=r["item_id"],
                session_id=r["session_id"],
                correct=bool(r["correct"]),
                evidence=Evidence.model_validate_json(r["evidence"]),
            )
            for r in rows
        ]
