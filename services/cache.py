"""Small thread-safe TTL caches used by the web application."""

from __future__ import annotations

import functools
import threading
import time


def ttl_cache(ttl: int = 3600):
    """Cache function results for ``ttl`` seconds and expose ``clear()``."""
    def decorate(func):
        values = {}
        lock = threading.RLock()

        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            with lock:
                cached = values.get(key)
                if cached and now - cached[0] < ttl:
                    return cached[1]
            result = func(*args, **kwargs)
            with lock:
                values[key] = (now, result)
            return result

        def clear():
            with lock:
                values.clear()

        wrapped.clear = clear
        return wrapped
    return decorate


def singleton(func):
    """Process-wide resource cache with the same clear API as ttl_cache."""
    return ttl_cache(ttl=10 * 365 * 24 * 60 * 60)(func)
