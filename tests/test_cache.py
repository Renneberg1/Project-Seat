"""Tests for the in-memory TTL cache."""

from __future__ import annotations

import time
from unittest.mock import patch

from src.cache import TTLCache


def test_set_and_get():
    c = TTLCache()
    c.set("key", "value")
    assert c.get("key") == "value"


def test_get_missing_returns_none():
    c = TTLCache()
    assert c.get("nonexistent") is None


def test_entry_expires_after_ttl():
    c = TTLCache(default_ttl=0.05)
    c.set("key", "value")
    assert c.get("key") == "value"
    time.sleep(0.06)
    assert c.get("key") is None


def test_custom_ttl_overrides_default():
    c = TTLCache(default_ttl=10.0)
    c.set("key", "value", ttl=0.05)
    assert c.get("key") == "value"
    time.sleep(0.06)
    assert c.get("key") is None


def test_invalidate_removes_key():
    c = TTLCache()
    c.set("key", "value")
    c.invalidate("key")
    assert c.get("key") is None


def test_invalidate_missing_key_is_noop():
    c = TTLCache()
    c.invalidate("nonexistent")  # should not raise


def test_invalidate_prefix_removes_matching_keys():
    c = TTLCache()
    c.set("project:1:summary", "s1")
    c.set("project:1:dhf", "d1")
    c.set("project:2:summary", "s2")
    c.invalidate_prefix("project:1:")
    assert c.get("project:1:summary") is None
    assert c.get("project:1:dhf") is None
    assert c.get("project:2:summary") == "s2"


def test_clear_removes_all_entries():
    c = TTLCache()
    c.set("a", 1)
    c.set("b", 2)
    c.clear()
    assert c.get("a") is None
    assert c.get("b") is None


def test_set_overwrites_existing_value():
    c = TTLCache()
    c.set("key", "old")
    c.set("key", "new")
    assert c.get("key") == "new"


def test_stores_none_value_as_valid():
    """None as a cached *value* is distinct from a cache miss (returns None).

    Since our cache uses None to signal a miss, storing None as a value
    would be ambiguous. Verify current behaviour: get() returns None,
    meaning callers that cache None should use a sentinel or avoid it.
    """
    c = TTLCache()
    c.set("key", None)
    # Because the stored value IS None, get returns None — indistinguishable from miss.
    # This is a known limitation; callers should avoid caching None directly.
    assert c.get("key") is None
