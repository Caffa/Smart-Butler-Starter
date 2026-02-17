"""
Request cache (debounce), context cache (hot data), and idempotency for the task queue.
"""

import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime


def get_cache_manager(db_path=None):
    """Return singleton CacheManager using configured cache db path."""
    from .types import CACHE_DB_PATH
    path = db_path or CACHE_DB_PATH
    if not hasattr(get_cache_manager, "_instance"):
        get_cache_manager._instance = {}
    if path not in get_cache_manager._instance:
        get_cache_manager._instance[path] = CacheManager(db_path=path)
    return get_cache_manager._instance[path]


class CacheManager:
    """Request cache (5s debounce) and context cache (5min TTL)."""

    def __init__(self, db_path=None):
        from .types import CACHE_DB_PATH
        self.db_path = db_path or CACHE_DB_PATH
        self._init_db()

    def _init_db(self):
        """Create request_cache and context_cache tables."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS request_cache (
                content_hash TEXT,
                task_type TEXT,
                timestamp REAL,
                created_at TEXT,
                PRIMARY KEY (content_hash, task_type)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS context_cache (
                key TEXT PRIMARY KEY,
                value TEXT,
                expires_at REAL
            )
        """)
        conn.commit()
        conn.close()

    def should_process_request(self, content, task_type, ttl_seconds=5):
        """Return True if request should be processed (not a duplicate within TTL)."""
        content_hash = hashlib.sha256(
            f"{content}{task_type}".encode("utf-8")
        ).hexdigest()
        now = time.time()
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            "SELECT timestamp FROM request_cache WHERE content_hash=? AND task_type=?",
            (content_hash, task_type),
        )
        row = cur.fetchone()
        if row and (now - row[0]) < ttl_seconds:
            conn.close()
            return False
        conn.execute(
            "INSERT OR REPLACE INTO request_cache VALUES (?, ?, ?, ?)",
            (content_hash, task_type, now, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
        return True

    def cleanup_expired_requests(self, older_than_seconds=300):
        """Remove old request cache entries."""
        cutoff = time.time() - older_than_seconds
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM request_cache WHERE timestamp < ?", (cutoff,))
        conn.commit()
        conn.close()

    def get_context(self, key):
        """Get cached context value if not expired."""
        now = time.time()
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            "SELECT value FROM context_cache WHERE key=? AND expires_at > ?",
            (key, now),
        )
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None

    def set_context(self, key, value, ttl_seconds=300):
        """Store context with TTL (default 5 minutes)."""
        expires_at = time.time() + ttl_seconds
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO context_cache VALUES (?, ?, ?)",
            (key, value, expires_at),
        )
        conn.commit()
        conn.close()

    def cleanup_expired_contexts(self):
        """Remove expired context cache entries."""
        now = time.time()
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM context_cache WHERE expires_at < ?", (now,))
        conn.commit()
        conn.close()


class IdempotencyManager:
    """Prevent duplicate operations (e.g. same zettelkasten content processed twice)."""

    def __init__(self, db_path=None):
        from .types import CACHE_DB_PATH
        self.db_path = db_path or CACHE_DB_PATH
        self._init_db()

    def _init_db(self):
        """Create idempotency_log table."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS idempotency_log (
                operation_id TEXT PRIMARY KEY,
                operation_type TEXT,
                content_hash TEXT,
                file_path TEXT,
                created_at TEXT,
                status TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_idempotency_content_type
            ON idempotency_log (content_hash, operation_type)
        """)
        conn.commit()
        conn.close()

    def generate_operation_id(self, content, operation_type):
        """Generate unique ID: hash(content + timestamp rounded to second)."""
        timestamp = int(time.time())
        combined = f"{content}{operation_type}{timestamp}"
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()

    def _content_hash(self, content):
        """Hash of content for duplicate detection."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def check_and_record(self, operation_id, operation_type, content, file_path=None):
        """
        Check if operation already done for this content. If file still exists, raise.
        If file was deleted, allow and update. Otherwise record new operation.
        """
        conn = sqlite3.connect(self.db_path)
        content_hash = self._content_hash(content)
        # Look up by content_hash + operation_type for duplicate detection
        cur = conn.execute(
            "SELECT operation_id, file_path, status FROM idempotency_log "
            "WHERE content_hash=? AND operation_type=? ORDER BY created_at DESC LIMIT 1",
            (content_hash, operation_type),
        )
        row = cur.fetchone()
        if row:
            _op_id, existing_path, status = row
            if existing_path and os.path.exists(existing_path):
                conn.close()
                raise ValueError(
                    f"Duplicate operation detected: {operation_type}. "
                    f"File still exists at {existing_path}"
                )
            # File was deleted, allow reprocessing
            conn.execute(
                "UPDATE idempotency_log SET status='reprocessed', created_at=?, file_path=? "
                "WHERE operation_id=?",
                (datetime.now().isoformat(), file_path or existing_path, _op_id),
            )
        else:
            conn.execute(
                "INSERT INTO idempotency_log VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    operation_type,
                    content_hash,
                    file_path,
                    datetime.now().isoformat(),
                    "completed",
                ),
            )
        conn.commit()
        conn.close()
