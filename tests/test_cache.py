import time
from unittest.mock import patch

from app.utils.cache import SimpleCache


class TestSimpleCache:
    def test_get_returns_none_for_missing_key(self):
        cache = SimpleCache(ttl=60)
        assert cache.get("missing") is None

    def test_set_and_get(self):
        cache = SimpleCache(ttl=60)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_returns_none_after_expiry(self):
        cache = SimpleCache(ttl=1)
        cache.set("key1", "value1")
        with patch("app.utils.cache.time.time", return_value=time.time() + 2):
            assert cache.get("key1") is None

    def test_set_with_custom_ttl(self):
        cache = SimpleCache(ttl=60)
        cache.set("key1", "value1", ttl=1)
        with patch("app.utils.cache.time.time", return_value=time.time() + 2):
            assert cache.get("key1") is None

    def test_delete_existing_key(self):
        cache = SimpleCache(ttl=60)
        cache.set("key1", "value1")
        cache.delete("key1")
        assert cache.get("key1") is None

    def test_delete_nonexistent_key_does_not_raise(self):
        cache = SimpleCache(ttl=60)
        cache.delete("nonexistent")  # Should not raise

    def test_clear_removes_all_entries(self):
        cache = SimpleCache(ttl=60)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_cleanup_removes_expired_entries(self):
        now = time.time()
        cache = SimpleCache(ttl=60)
        cache.set("fresh", "value1")
        cache.set("stale", "value2", ttl=1)
        with patch("app.utils.cache.time.time", return_value=now + 2):
            cache.cleanup()
        # stale was removed by cleanup
        assert "stale" not in cache._store
        # fresh is still there (not expired yet with default ttl=60)
        assert "fresh" in cache._store

    def test_default_ttl(self):
        cache = SimpleCache()
        assert cache._ttl == 300
