import json
import sqlite3
from datetime import datetime, timedelta, timezone


class LLMCache:
    def __init__(self, db_path="llm_cache.db", ttl=86400):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.ttl = ttl
        self._init_db()

    def _init_db(self):
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS cache "
            "(key TEXT PRIMARY KEY, result TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        self.db.commit()

    def get(self, key):
        expiry = (datetime.now(timezone.utc) - timedelta(seconds=self.ttl)).isoformat()
        row = self.db.execute(
            "SELECT result FROM cache WHERE key = ? AND created_at > ?",
            (key, expiry),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, key, value):
        self.db.execute(
            "INSERT OR REPLACE INTO cache (key, result, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), datetime.now(timezone.utc).isoformat()),
        )
        self.db.commit()
