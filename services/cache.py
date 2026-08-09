"""Small thread-safe TTL caches used by the web application."""

from __future__ import annotations

import functools
import threading
import time
from collections import OrderedDict


def ttl_cache(ttl: int = 3600, max_entries: int = 256):
    """Thread-safe bounded TTL cache that eagerly removes expired values."""
    if ttl <= 0:
        raise ValueError("ttl must be positive")
    if max_entries <= 0:
        raise ValueError("max_entries must be positive")

    def decorate(func):
        values = OrderedDict()
        lock = threading.RLock()

        def purge_expired(now):
            expired = [key for key, (created_at, _) in values.items() if now - created_at >= ttl]
            for key in expired:
                values.pop(key, None)

        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            with lock:
                purge_expired(now)
                cached = values.get(key)
                if cached:
                    values.move_to_end(key)
                    return cached[1]
            result = func(*args, **kwargs)
            with lock:
                now = time.monotonic()
                purge_expired(now)
                values[key] = (now, result)
                values.move_to_end(key)
                while len(values) > max_entries:
                    values.popitem(last=False)
            return result

        def clear():
            with lock:
                values.clear()

        def cache_size():
            with lock:
                purge_expired(time.monotonic())
                return len(values)

        def cache_values():
            with lock:
                purge_expired(time.monotonic())
                return [value for _, value in values.values()]

        wrapped.clear = clear
        wrapped.cache_size = cache_size
        wrapped.cache_values = cache_values
        return wrapped
    return decorate


def singleton(func):
    """Process-wide resource cache with the same clear API as ttl_cache."""
    return ttl_cache(ttl=10 * 365 * 24 * 60 * 60, max_entries=1)(func)
