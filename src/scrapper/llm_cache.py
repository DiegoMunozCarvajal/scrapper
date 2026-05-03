import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta


class LLMCache:
    """SQLite-backed key-value cache with TTL expiry, thread-safe access, and context manager support."""

    def __init__(self, db_path="llm_cache.db", ttl=86400):
        """Initialize the cache with a database path and TTL in seconds."""
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.ttl = ttl
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS cache "
            "(key TEXT PRIMARY KEY, result TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        self.db.commit()

    def get(self, key):
        """Retrieve a cached value by key, returning None if missing or expired."""
        expiry = (datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=self.ttl)).isoformat()
        with self._lock:
            row = self.db.execute(
                "SELECT result FROM cache WHERE key = ? AND created_at > ?",
                (key, expiry),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, key, value):
        """Store a value under the given key, overwriting any existing entry."""
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO cache (key, result, created_at) VALUES (?, ?, ?)",
                (key, json.dumps(value), datetime.now(UTC).replace(tzinfo=None).isoformat()),
            )
            self.db.commit()

    def close(self):
        """Close the underlying database connection."""
        with self._lock:
            self.db.close()
            self.db = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
