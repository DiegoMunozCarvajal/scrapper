from scrapper.llm_cache import LLMCache


def test_set_and_get(tmp_path):
    db = tmp_path / "test.db"
    cache = LLMCache(db_path=str(db), ttl=86400)
    cache.set("key1", [{"title": "Test"}])
    result = cache.get("key1")
    assert result == [{"title": "Test"}]


def test_get_missing_key_returns_none(tmp_path):
    db = tmp_path / "test.db"
    cache = LLMCache(db_path=str(db), ttl=86400)
    assert cache.get("nonexistent") is None


def test_ttl_expiry(tmp_path):
    db = tmp_path / "test.db"
    cache = LLMCache(db_path=str(db), ttl=-1)
    cache.set("key1", [{"title": "Test"}])
    assert cache.get("key1") is None


def test_upsert_replaces_value(tmp_path):
    db = tmp_path / "test.db"
    cache = LLMCache(db_path=str(db), ttl=86400)
    cache.set("key1", [{"title": "First"}])
    cache.set("key1", [{"title": "Second"}])
    assert cache.get("key1") == [{"title": "Second"}]


def test_context_manager(tmp_path):
    db = tmp_path / "test.db"
    with LLMCache(db_path=str(db), ttl=86400) as cache:
        cache.set("key1", [{"title": "Test"}])
        result = cache.get("key1")
        assert result == [{"title": "Test"}]