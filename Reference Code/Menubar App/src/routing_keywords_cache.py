"""
Routing keyword cache: maps keywords from devlogs, experiments, and zettels
to file paths. Used to boost keyword-matched items into routing/reference context
so "Butler" matches Smart Butler devlog even when not in recent-10.
"""

import json
import os
import re
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from . import memory
from .butler_writes_cache import is_template_path
from .types import (
    CACHE_DB_PATH,
    DEVLOG_DIR,
    EXPERIMENT_DIR,
    ZETTELKASTEN_FOLDERS,
    ZETTEL_VAULT_ROOT,
    get_setting,
    is_vault_path_protected,
)

CACHE_PATH = os.path.join(os.path.dirname(CACHE_DB_PATH), "routing_keywords_cache.json")

# Curated stopwords: common English + noise in compound names. No NLTK dependency.
ROUTING_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by", "can",
    "could", "did", "do", "does", "during", "etc", "even", "for", "from", "general",
    "good", "had", "has", "have", "in", "into", "is", "just", "least", "less",
    "little", "many", "may", "might", "more", "most", "much", "must", "new",
    "no", "not", "of", "off", "on", "only", "or", "other", "some", "such",
    "than", "that", "the", "their", "then", "there", "these", "they", "this",
    "through", "to", "very", "was", "were", "will", "with", "would", "same",
    "different", "another", "old", "bad", "great", "big", "so", "also", "still",
    "any", "all", "each", "every", "both", "few", "most", "own", "same",
})

# Zettel filename stems we skip when deriving keywords (e.g. "Reference - X" -> skip "reference")
ZETTEL_GENERIC_STEM_WORDS = frozenset({"reference", "note", "notes", "zettel", "idea", "ideas"})

# Experiment filename pattern: tiny-experiment-{name}-{YYYY-MM-DD}.md
EXPERIMENT_PATTERN = re.compile(r"^tiny-experiment-(.+)-(\d{4}-\d{2}-\d{2})\.md$", re.I)


def _filter_keyword(w: str) -> bool:
    """True if keyword should be kept (not a stopword, and for stem-derived: len >= 3)."""
    if not w or not w.strip():
        return False
    w = w.strip().lower()
    if w in ROUTING_STOPWORDS:
        return False
    # For stem-derived keywords, skip very short (but "ai" is 2 chars - allow len >= 2 for acronyms)
    if len(w) < 2:
        return False
    return True


def _parse_butler_frontmatter(raw: str) -> tuple:
    """Parse butler_summary and butler_keywords from YAML frontmatter."""
    summary_str = "none"
    keywords_str = "none"
    if not raw or "---" not in raw:
        return summary_str, keywords_str
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return summary_str, keywords_str
    fm = parts[1].strip()
    m = re.search(r"butler_summary:\s*(.+?)(?=\n\w|\n---|\Z)", fm, re.DOTALL)
    if m:
        summary_str = m.group(1).strip().strip("\"'")
    m = re.search(r"butler_keywords:\s*(.+?)(?=\n\w|\n---|\Z)", fm, re.DOTALL)
    if m:
        kw = m.group(1).strip()
        keywords_str = kw.strip("\"'") if not kw.startswith("[") else kw
    return summary_str, keywords_str


def _extract_keywords_from_string(s: str, min_len_for_stem: int = 3) -> set:
    """Extract normalized keywords from comma-separated or space/hyphen-separated string."""
    if not s or not s.strip():
        return set()
    # Split on comma, space, hyphen
    tokens = re.split(r"[\s,\-]+", s.strip().lower())
    out = set()
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        if t in ROUTING_STOPWORDS:
            continue
        if len(t) < min_len_for_stem and t not in ("ai", "id", "os"):
            continue
        out.add(t)
    return out


def _extract_keywords_from_stem(stem: str) -> set:
    """Extract keywords from file stem; filter stopwords and short words (min 3)."""
    if not stem:
        return set()
    tokens = re.split(r"[\s\-_]+", stem.strip().lower())
    out = set()
    for t in tokens:
        if not t or t in ROUTING_STOPWORDS or len(t) < 3:
            continue
        out.add(t)
    return out


def _add_to_keyword_map(m: dict, keyword: str, path: str) -> None:
    if keyword not in m:
        m[keyword] = []
    if path not in m[keyword]:
        m[keyword].append(path)


def _scan_devlogs() -> tuple:
    """Scan DEVLOG_DIR; return (keyword_to_devlog dict, path_to_mtime dict)."""
    keyword_to_devlog = {}
    path_to_mtime = {}
    if not DEVLOG_DIR or not os.path.isdir(DEVLOG_DIR):
        return keyword_to_devlog, path_to_mtime
    devlog_abs = os.path.abspath(DEVLOG_DIR)
    for name in os.listdir(DEVLOG_DIR) or []:
        if not name.endswith(".md"):
            continue
        path = os.path.join(DEVLOG_DIR, name)
        if not os.path.isfile(path) or not memory.is_safe_path(path) or is_vault_path_protected(path):
            continue
        if is_template_path(path):
            continue
        try:
            mtime = os.path.getmtime(path)
            path_to_mtime[path] = mtime
        except Exception:
            continue
        stem = name[:-3]  # strip .md
        keywords = _extract_keywords_from_stem(stem)
        try:
            with open(path, "r", encoding="utf-8") as f:
                head = f.read(8192)
            _, kw_str = _parse_butler_frontmatter(head)
            if kw_str and kw_str != "none":
                # Parse comma-separated butler_keywords
                for part in kw_str.split(","):
                    tokens = re.split(r"[\s\-]+", part.strip().lower())
                    for t in tokens:
                        if t and t not in ROUTING_STOPWORDS and len(t) >= 2:
                            keywords.add(t)
        except Exception:
            pass
        for kw in keywords:
            _add_to_keyword_map(keyword_to_devlog, kw, path)
    return keyword_to_devlog, path_to_mtime


def _scan_experiments() -> tuple:
    """Scan EXPERIMENT_DIR; return (keyword_to_experiment dict, path_to_mtime dict)."""
    keyword_to_experiment = {}
    path_to_mtime = {}
    if not EXPERIMENT_DIR or not os.path.isdir(EXPERIMENT_DIR):
        return keyword_to_experiment, path_to_mtime
    for name in os.listdir(EXPERIMENT_DIR) or []:
        if not name.endswith(".md"):
            continue
        path = os.path.join(EXPERIMENT_DIR, name)
        if not os.path.isfile(path) or not memory.is_safe_path(path) or is_vault_path_protected(path):
            continue
        try:
            mtime = os.path.getmtime(path)
            path_to_mtime[path] = mtime
        except Exception:
            continue
        m = EXPERIMENT_PATTERN.match(name)
        if m:
            exp_name = m.group(1)  # e.g. "socializing-more" or "coffee"
            tokens = re.split(r"[\-]+", exp_name.strip().lower())
            for t in tokens:
                if t and t not in ROUTING_STOPWORDS and len(t) >= 3:
                    _add_to_keyword_map(keyword_to_experiment, t, path)
        else:
            # Non-standard filename: use stem words
            stem = name[:-3]
            keywords = _extract_keywords_from_stem(stem)
            for kw in keywords:
                _add_to_keyword_map(keyword_to_experiment, kw, path)
    return keyword_to_experiment, path_to_mtime


def _is_zettel_excluded_dir(path: str, zettel_root: str) -> bool:
    """Exclude Attachments, 10 Log, 00 Command per memory.py."""
    try:
        rel = os.path.relpath(path, zettel_root)
        parts = rel.replace("\\", "/").split("/")
        excluded = ("Attachments", "10 Log", "00 Command")
        return any(p in excluded for p in parts)
    except ValueError:
        return True


def _scan_zettels() -> tuple:
    """Scan ZETTELKASTEN_FOLDERS; return (keyword_to_zettel dict, path_to_mtime dict)."""
    keyword_to_zettel = {}
    path_to_mtime = {}
    zettel_root = os.path.abspath(ZETTEL_VAULT_ROOT) if ZETTEL_VAULT_ROOT and os.path.isdir(ZETTEL_VAULT_ROOT) else None
    if not ZETTELKASTEN_FOLDERS:
        return keyword_to_zettel, path_to_mtime
    for folder in ZETTELKASTEN_FOLDERS:
        if not folder or not os.path.isdir(folder):
            continue
        for dp, _, filenames in os.walk(folder):
            for name in filenames:
                if not name.endswith(".md"):
                    continue
                path = os.path.join(dp, name)
                if not os.path.isfile(path) or not memory.is_safe_path(path) or is_vault_path_protected(path):
                    continue
                if zettel_root and _is_zettel_excluded_dir(path, zettel_root):
                    continue
                if is_template_path(path):
                    continue
                try:
                    mtime = os.path.getmtime(path)
                    path_to_mtime[path] = mtime
                except Exception:
                    continue
                stem = name[:-3]
                keywords = set()
                # Primarily butler_keywords
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        head = f.read(8192)
                    _, kw_str = _parse_butler_frontmatter(head)
                    if kw_str and kw_str != "none":
                        for part in kw_str.split(","):
                            tokens = re.split(r"[\s\-]+", part.strip().lower())
                            for t in tokens:
                                if t and t not in ROUTING_STOPWORDS and len(t) >= 2:
                                    keywords.add(t)
                except Exception:
                    pass
                # Optionally add stem words if not generic
                stem_tokens = re.split(r"[\s\-_]+", stem.lower())
                for t in stem_tokens:
                    if t and t not in ZETTEL_GENERIC_STEM_WORDS and t not in ROUTING_STOPWORDS and len(t) >= 3:
                        keywords.add(t)
                for kw in keywords:
                    _add_to_keyword_map(keyword_to_zettel, kw, path)
    return keyword_to_zettel, path_to_mtime


def build_routing_keywords_cache() -> dict:
    """Build and save the routing keyword cache. Returns the cache dict."""
    k2d, mtime_d = _scan_devlogs()
    k2e, mtime_e = _scan_experiments()
    k2z, mtime_z = _scan_zettels()

    devlog_mtime = os.path.getmtime(DEVLOG_DIR) if DEVLOG_DIR and os.path.isdir(DEVLOG_DIR) else 0
    exp_mtime = os.path.getmtime(EXPERIMENT_DIR) if EXPERIMENT_DIR and os.path.isdir(EXPERIMENT_DIR) else 0
    zettel_mtime = 0
    for f in (ZETTELKASTEN_FOLDERS or []):
        if os.path.isdir(f):
            zettel_mtime = max(zettel_mtime, os.path.getmtime(f))

    cache = {
        "built_at": time.time(),
        "devlog_dir_mtime": devlog_mtime,
        "experiment_dir_mtime": exp_mtime,
        "zettel_folders_mtime": zettel_mtime,
        "keyword_to_devlog": k2d,
        "keyword_to_experiment": k2e,
        "keyword_to_zettel": k2z,
        "_path_to_mtime_devlog": mtime_d,
        "_path_to_mtime_experiment": mtime_e,
        "_path_to_mtime_zettel": mtime_z,
    }
    os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
    to_save = {k: v for k, v in cache.items() if not k.startswith("_")}
    to_save["_path_to_mtime_devlog"] = mtime_d
    to_save["_path_to_mtime_experiment"] = mtime_e
    to_save["_path_to_mtime_zettel"] = mtime_z
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(to_save, f, indent=0)
    memory.log_debug(f"Built routing keyword cache: {len(k2d)} devlog kws, {len(k2e)} experiment kws, {len(k2z)} zettel kws")
    return cache


def _is_cache_stale(cache: dict) -> bool:
    """True if cache should be rebuilt."""
    if not cache:
        return True
    try:
        if DEVLOG_DIR and os.path.isdir(DEVLOG_DIR):
            if os.path.getmtime(DEVLOG_DIR) != cache.get("devlog_dir_mtime", 0):
                return True
        if EXPERIMENT_DIR and os.path.isdir(EXPERIMENT_DIR):
            if os.path.getmtime(EXPERIMENT_DIR) != cache.get("experiment_dir_mtime", 0):
                return True
        for f in (ZETTELKASTEN_FOLDERS or []):
            if os.path.isdir(f) and os.path.getmtime(f) != cache.get("zettel_folders_mtime", 0):
                return True
    except Exception:
        return True
    return False


def get_routing_keywords_cache() -> dict:
    """Load cache from disk; rebuild if stale or missing."""
    cache = None
    if os.path.isfile(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except (json.JSONDecodeError, IOError):
            cache = None
    if cache is None or _is_cache_stale(cache):
        cache = build_routing_keywords_cache()
    return cache


def match_keywords_in_content(content: str) -> tuple:
    """
    Match content against the keyword cache.
    Returns (matched_devlogs, matched_experiments, matched_zettels)
    where each is dict: path -> [matched_keywords]
    """
    if not content or not content.strip():
        return {}, {}, {}
    cache = get_routing_keywords_cache()
    k2d = cache.get("keyword_to_devlog", {})
    k2e = cache.get("keyword_to_experiment", {})
    k2z = cache.get("keyword_to_zettel", {})

    words = set(re.findall(r"\b\w+\b", content.lower()))
    matched_devlogs = {}
    matched_experiments = {}
    matched_zettels = {}

    for w in words:
        for path in k2d.get(w, []):
            matched_devlogs.setdefault(path, []).append(w)
        for path in k2e.get(w, []):
            matched_experiments.setdefault(path, []).append(w)
        for path in k2z.get(w, []):
            matched_zettels.setdefault(path, []).append(w)

    return matched_devlogs, matched_experiments, matched_zettels


def apply_category_limits(
    matched_devlogs: dict,
    matched_experiments: dict,
    matched_zettels: dict,
    max_devlogs: int = None,
    max_experiments: int = None,
    max_zettels: int = None,
) -> tuple:
    """
    Limit each category to max_per items. Sort by: (1) number of matched keywords desc,
    (2) mtime desc. Returns (limited_devlogs, limited_experiments, limited_zettels)
    each as dict path -> [matched_keywords].
    """
    max_devlogs = max_devlogs if max_devlogs is not None else get_setting("max-keyword-matched-devlogs", 5)
    max_experiments = max_experiments if max_experiments is not None else get_setting("max-keyword-matched-experiments", 5)
    max_zettels = max_zettels if max_zettels is not None else get_setting("max-keyword-matched-zettels", 5)

    try:
        max_devlogs = int(max_devlogs) if max_devlogs is not None else 5
    except (TypeError, ValueError):
        max_devlogs = 5
    try:
        max_experiments = int(max_experiments) if max_experiments is not None else 5
    except (TypeError, ValueError):
        max_experiments = 5
    try:
        max_zettels = int(max_zettels) if max_zettels is not None else 5
    except (TypeError, ValueError):
        max_zettels = 5

    cache = get_routing_keywords_cache()
    mtime_d = cache.get("_path_to_mtime_devlog", {})
    mtime_e = cache.get("_path_to_mtime_experiment", {})
    mtime_z = cache.get("_path_to_mtime_zettel", {})

    def _limit(d: dict, mtime_map: dict, n: int) -> dict:
        if not d or n <= 0:
            return {}
        items = [(p, kws) for p, kws in d.items() if os.path.isfile(p)]
        # Sort: (1) more matched keywords first, (2) more recent mtime first
        items.sort(key=lambda x: (-len(x[1]), -(mtime_map.get(x[0], 0))))
        return dict(items[:n])

    return (
        _limit(matched_devlogs, mtime_d, max_devlogs),
        _limit(matched_experiments, mtime_e, max_experiments),
        _limit(matched_zettels, mtime_z, max_zettels),
    )
