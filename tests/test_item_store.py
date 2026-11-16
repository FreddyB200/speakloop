"""Tests for the SQLite item store."""

from pathlib import Path

import pytest

from speakloop.items.store import ItemStore
from speakloop.models import Evidence, Item, ItemKind, ItemStatus, ItemUse


def make(id_: str = "i1", **over: object) -> Item:
    data: dict[str, object] = {
        "id": id_,
        "kind": ItemKind.PHRASE,
        "key": "phrase:trade-off",
        "front": "f",
        "back": "b",
        "examples": ("a",),
        "source_finding_ids": ("f1",),
    }
    return Item.model_validate(data | over)


def use(correct: bool, session_id: str = "20260101-000000-aaaa") -> ItemUse:
    ev = Evidence(quote="q", start=0, end=1, track="mic")
    return ItemUse(item_id="i1", session_id=session_id, correct=correct, evidence=ev)


def test_upsert_insert_and_get(tmp_path: Path) -> None:
    with ItemStore(tmp_path / "x" / "items.db") as store:
        store.upsert(make())
        assert store.get("i1") == make()
        assert store.get_by_key("phrase:trade-off") == make()
        assert store.get("nope") is None
        assert store.get_by_key("nope") is None


def test_upsert_dedupes_and_merges(tmp_path: Path) -> None:
    with ItemStore(tmp_path / "items.db") as store:
        store.upsert(make())
        merged = store.upsert(
            make("i2", examples=("a", "b"), source_finding_ids=("f2", "f1"), front="other")
        )
        assert merged.id == "i1"
        assert merged.examples == ("a", "b")
        assert merged.source_finding_ids == ("f1", "f2")
        assert merged.front == "f"
        assert len(store.list()) == 1
        assert store.get("i2") is None


def test_list_filter_by_status(tmp_path: Path) -> None:
    with ItemStore(tmp_path / "items.db") as store:
        store.upsert(make())
        store.upsert(make("i2", key="word:x", status=ItemStatus.MASTERED))
        assert [i.id for i in store.list(ItemStatus.MASTERED)] == ["i2"]
        assert store.list(ItemStatus.LEARNING) == []
        assert len(store.list()) == 2


def test_record_use_counters_and_uses(tmp_path: Path) -> None:
    with ItemStore(tmp_path / "items.db") as store:
        store.upsert(make())
        store.record_use(use(True))
        store.record_use(use(False))
        store.record_use(use(True, "20260102-000000-bbbb"))
        item = store.get("i1")
        assert item is not None
        assert (item.uses_correct, item.uses_incorrect) == (2, 1)
        assert item.last_seen_session == "20260102-000000-bbbb"
        assert [u.correct for u in store.uses("i1")] == [True, False, True]
        assert store.uses("other") == []


def test_record_use_unknown_item(tmp_path: Path) -> None:
    with ItemStore(tmp_path / "items.db") as store, pytest.raises(KeyError):
        store.record_use(use(True))


def test_persistence_and_schema_version(tmp_path: Path) -> None:
    db = tmp_path / "items.db"
    with ItemStore(db) as store:
        store.upsert(make())
        store.record_use(use(True))
    with ItemStore(db) as store:
        assert store.get("i1") is not None
        assert len(store.uses("i1")) == 1
        version = store._conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == 1


def test_newer_schema_rejected(tmp_path: Path) -> None:
    import sqlite3

    db = tmp_path / "items.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(RuntimeError):
        ItemStore(db)
