"""Tests for v2 forge_meta and auto features."""

from __future__ import annotations

import pytest

from forge.storage.queries import get_meta, set_meta


class TestForgeMeta:
    def test_set_and_get(self, db):
        set_meta(db, "last_dedup_test", "2026-03-17T00:00:00")
        assert get_meta(db, "last_dedup_test") == "2026-03-17T00:00:00"

    def test_get_nonexistent(self, db):
        assert get_meta(db, "nonexistent_key") is None

    def test_upsert(self, db):
        set_meta(db, "key1", "value1")
        set_meta(db, "key1", "value2")
        assert get_meta(db, "key1") == "value2"

    def test_multiple_keys(self, db):
        set_meta(db, "a", "1")
        set_meta(db, "b", "2")
        assert get_meta(db, "a") == "1"
        assert get_meta(db, "b") == "2"
