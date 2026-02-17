"""
Persistent cache of the last N unique markdown files the smart butler wrote to.
Used by open_last_butler_file.py for "open last" and Alfred script filter list.
Extended format: stores path + mtime for reference resolution fast path.

Butler metadata safety (see memory.py): The butler metadata system only ever modifies
YAML frontmatter (butler_summary, butler_keywords, butler_body_hash). It never changes
file body content or Templater/script syntax. Files with "Template"/"Templates" in
path or Templater (<% %>) in frontmatter are skipped.
"""

import json
import os
import time

# Note Sorting Scripts directory (parent of src/)
_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(_SCRIPT_DIR, "butler_recent_writes.json")
_MAX_PATHS = 10


def _load_entries():
    """Return list of entries from disk. Each entry is either str (path) or dict with path, mtime."""
    if not os.path.isfile(CACHE_PATH):
        return []
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return data
    except (json.JSONDecodeError, IOError):
        return []


def _normalize_entries(entries):
    """Ensure each entry is dict with path and mtime. Backfill mtime from disk for old string entries."""
    out = []
    seen = set()
    for e in entries:
        if isinstance(e, dict) and e.get("path"):
            p = os.path.abspath(e["path"])
            mt = e.get("mtime") or 0
            if p not in seen:
                if not mt and os.path.isfile(p):
                    try:
                        mt = os.path.getmtime(p)
                    except Exception:
                        pass
                out.append({"path": p, "mtime": mt})
                seen.add(p)
        elif isinstance(e, str) and e.strip():
            p = os.path.abspath(e.strip())
            if p not in seen:
                mt = 0
                if os.path.isfile(p):
                    try:
                        mt = os.path.getmtime(p)
                    except Exception:
                        pass
                out.append({"path": p, "mtime": mt})
                seen.add(p)
    return out


def _save_entries(entries):
    """Write list of {path, mtime} to disk."""
    os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=0)


def is_template_path(path: str) -> bool:
    """
    True if the path should be excluded from butler metadata (never add or modify
    butler_summary/butler_keywords). Excludes: filename contains "template", path component is "Template"/"Templates", or basename stem ends with "template". Case-insensitive.
    """
    if not path or not str(path).strip():
        return False
    norm = os.path.normpath(path.strip())
    base = os.path.basename(norm)
    if "template" in base.lower():
        return True
    for part in norm.split(os.sep):
        if part and part.lower() in ("template", "templates"):
            return True
    return False


def record_butler_write(path: str) -> None:
    """
    Record a butler write to path. Normalizes to absolute path; if already in list,
    move to front; else prepend. Keeps at most _MAX_PATHS unique paths. Persists to JSON.
    Stores path + mtime for reference resolution. Only records .md files.
    """
    if not path or not str(path).strip():
        return
    path = os.path.abspath(os.path.normpath(path.strip()))
    if not path.lower().endswith(".md"):
        return
    if is_template_path(path):
        return
    entries = _normalize_entries(_load_entries())
    now = time.time()
    entries = [e for e in entries if e["path"] != path]
    entries.insert(0, {"path": path, "mtime": now})
    entries = entries[:_MAX_PATHS]
    _save_entries(entries)


def get_recent_butler_writes(limit: int = 10) -> list:
    """Return up to `limit` most recent paths (empty list if none). Backward compatible."""
    entries = _normalize_entries(_load_entries())
    return [e["path"] for e in entries[:limit]]


def get_recent_butler_writes_with_mtime(limit: int = 10) -> list:
    """Return up to `limit` (path, mtime) tuples, most recent first."""
    entries = _normalize_entries(_load_entries())
    return [(e["path"], e["mtime"]) for e in entries[:limit]]
