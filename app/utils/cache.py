import time
from typing import Any, Optional


class SimpleCache:
    """TTL-based in-memory cache."""

    def __init__(self, ttl: int = 300):
        self._ttl = ttl
        self._store: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        """Get value by key. Returns None if expired or not found."""
        if key not in self._store:
            return None
        value, expires_at = self._store[key]
        if time.time() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value with optional custom TTL."""
        expire_time = time.time() + (ttl if ttl is not None else self._ttl)
        self._store[key] = (value, expire_time)

    def delete(self, key: str) -> None:
        """Delete a specific key."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Clear all cached values."""
        self._store.clear()

    def cleanup(self) -> None:
        """Remove all expired entries."""
        now = time.time()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
