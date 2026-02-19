"""Simple in-memory TTL cache — no external dependencies."""

from __future__ import annotations

import threading
import time
from typing import Any


class TTLCache:
    """Thread-safe in-memory cache with per-key time-to-live."""

    _SENTINEL = object()

    def __init__(self, default_ttl: float = 60.0) -> None:
        self._default_ttl = default_ttl
        self._store: dict[str, tuple[Any, float]] = {}  # key -> (value, expires_at)
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        """Return cached value or ``None`` if missing/expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store *value* under *key* with the given TTL (seconds)."""
        expires_at = time.monotonic() + (ttl if ttl is not None else self._default_ttl)
        with self._lock:
            self._store[key] = (value, expires_at)

    def invalidate(self, key: str) -> None:
        """Remove a single key."""
        with self._lock:
            self._store.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        """Remove all keys that start with *prefix*."""
        with self._lock:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._store.clear()


# Module-level singleton
cache = TTLCache()
