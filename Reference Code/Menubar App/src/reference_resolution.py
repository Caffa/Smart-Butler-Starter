"""
Reference resolution: detect when user refers to a previous note, resolve which note,
inject links or append to zettel. Uses recent-notes pool (vault scan + extended butler cache).
"""

import os
import re
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from prompt_loader import load_prompt

from . import memory
from .butler_writes_cache import get_recent_butler_writes_with_mtime
from .llm_client import call_llm_structured
from .llm_models import ReferenceResolutionResponse
from .routing_keywords_cache import (
    apply_category_limits,
    get_routing_keywords_cache,
    match_keywords_in_content,
)
from .types import MODEL_MED, VAULT_ROOT, ZETTEL_VAULT_ROOT, get_setting

# Hours to look back when building "recent notes" pool for resolution (default 7 days)
RECENT_NOTES_POOL_HOURS_DEFAULT = 168
RECENT_NOTES_LIMIT_DEFAULT = 50

# Excalidraw: exclude paths containing this (case-insensitive)
EXCALIDRAW_SUBSTR = "excalidraw"

# Closed list of phrases that trigger reference resolution (user referring to another note)
REFERENCE_PHRASES = (
    "previous note",
    "what i just said",
    "my last thought",
    "that note i made",
    "the zettel about",
    "my previous thought",
    "that thought i had",
    "referring to my note",
    "that note about",
    "the note i wrote",
    "what i said earlier",
    "my earlier note",
    "that idea i had",
    "the note about",
)
# Phrases that mean "adding onto" (may trigger append if single in window)
ADDING_ONTO_PHRASES = (
    "adding onto",
    "adding on to",
    "adding to my previous",
    "continuing from",
    "continuing my",
    "follow up to",
    "follow-up to",
    "building on",
    "expanding on",
)


def _vault_name_for_path(path: str) -> str:
    """Return display name of vault for path (first segment under VAULT_ROOT)."""
    if not path or not VAULT_ROOT:
        return ""
    abs_path = os.path.abspath(path)
    if not abs_path.startswith(VAULT_ROOT + os.sep) and abs_path != VAULT_ROOT:
        return ""
    try:
        rel = os.path.relpath(abs_path, VAULT_ROOT)
        parts = rel.replace("\\", "/").split("/")
        return parts[0] if parts and parts[0] else ""
    except ValueError:
        return ""


def _scan_vault_recent_md(
    root: str, since_ts: float, limit: int, exclude_excalidraw: bool = True
):
    """
    Scan root for .md files modified after since_ts. Exclude excalidraw if requested.
    Returns list of (path, mtime) sorted by mtime desc.
    """
    if not root or not os.path.isdir(root):
        return []
    found = []
    for dp, _, filenames in os.walk(root):
        for f in filenames:
            if not f.endswith(".md"):
                continue
            fp = os.path.join(dp, f)
            if exclude_excalidraw and EXCALIDRAW_SUBSTR in fp.lower():
                continue
            try:
                mtime = os.path.getmtime(fp)
                if mtime >= since_ts:
                    found.append((fp, mtime))
            except Exception:
                continue
    found.sort(key=lambda x: x[1], reverse=True)
    return found[:limit]


def get_recent_notes_for_resolution(
    hours: int = None,
    limit: int = None,
) -> list:
    """
    Return list of (path, mtime, vault_name) for recent .md files across vault(s).
    Merges extended butler cache with vault scan under VAULT_ROOT. Excludes excalidraw.
    Sorted by mtime descending. Uses memory.is_safe_path so only vault paths included.
    """
    hours = hours if hours is not None else RECENT_NOTES_POOL_HOURS_DEFAULT
    limit = limit if limit is not None else RECENT_NOTES_LIMIT_DEFAULT
    since_ts = time.time() - (hours * 3600)

    by_path = {}
    # Butler cache first (fast path)
    for path, mtime in get_recent_butler_writes_with_mtime(limit * 2):
        if mtime >= since_ts and memory.is_safe_path(path) and os.path.isfile(path):
            by_path[path] = mtime
    # Vault scan
    if VAULT_ROOT and os.path.isdir(VAULT_ROOT):
        for path, mtime in _scan_vault_recent_md(VAULT_ROOT, since_ts, limit * 2):
            if memory.is_safe_path(path) and path not in by_path:
                by_path[path] = mtime
            elif path in by_path and mtime > by_path[path]:
                by_path[path] = mtime

    entries = [(p, t, _vault_name_for_path(p)) for p, t in by_path.items()]
    entries.sort(key=lambda x: x[1], reverse=True)
    return entries[:limit]


def pattern_match_reference(content: str) -> bool:
    """True if content matches closed list of phrases indicating user is referring to another note."""
    if not content or not content.strip():
        return False
    text = content.strip().lower()
    for p in REFERENCE_PHRASES:
        if p in text:
            return True
    for p in ADDING_ONTO_PHRASES:
        if p in text:
            return True
    if re.search(r"\b(previous|last|that)\s+(note|thought|zettel|idea)\b", text):
        return True
    return False


def pattern_match_adding_onto(content: str) -> bool:
    """True if content matches 'adding onto' style (may append to single referent in window)."""
    if not content or not content.strip():
        return False
    text = content.strip().lower()
    for p in ADDING_ONTO_PHRASES:
        if p in text:
            return True
    return False


def _parse_butler_frontmatter(raw: str) -> tuple:
    """Parse butler_summary and butler_keywords from YAML front matter. Returns (summary, keywords)."""
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


def build_recent_notes_context(
    hours: int = None,
    limit: int = None,
    content: str = None,
) -> tuple:
    """
    Build context string for LLM and list of (path, mtime, vault_name) for resolution.
    Ensures zettel files in ZettelPublish have butler_summary/butler_keywords (writes if missing).
    When content is provided: prepend keyword-matched zettels to entries and annotate with Matched hint.
    Returns (context_str, entries) where entries = [(path, mtime, vault_name), ...].
    """
    entries = get_recent_notes_for_resolution(hours=hours, limit=limit)
    keyword_zettel_entries = []
    path_to_matched_kws = {}
    if content and content.strip():
        matched_d, matched_e, matched_z = match_keywords_in_content(content)
        _, _, limited_zettels = apply_category_limits(
            matched_d, matched_e, matched_z
        )
        if limited_zettels:
            cache = get_routing_keywords_cache()
            mtime_z = cache.get("_path_to_mtime_zettel", {})
            zettel_root_abs = os.path.abspath(ZETTEL_VAULT_ROOT) if ZETTEL_VAULT_ROOT else ""
            for path in limited_zettels:
                if os.path.isfile(path):
                    mtime = mtime_z.get(path)
                    if mtime is None:
                        try:
                            mtime = os.path.getmtime(path)
                        except Exception:
                            mtime = 0
                    vault_name = _vault_name_for_path(path)
                    keyword_zettel_entries.append((path, mtime, vault_name))
                    path_to_matched_kws[path] = limited_zettels[path]
    keyword_paths = {e[0] for e in keyword_zettel_entries}
    entries = keyword_zettel_entries + [
        e for e in entries if e[0] not in keyword_paths
    ]
    if not entries:
        return "No recent notes found.", []
    lines = []
    zettel_root_abs = os.path.abspath(ZETTEL_VAULT_ROOT) if ZETTEL_VAULT_ROOT else ""
    for i, (path, mtime, vault_name) in enumerate(entries, 1):
        if zettel_root_abs and os.path.abspath(path).startswith(
            zettel_root_abs + os.sep
        ):
            memory.ensure_zettel_butler_summary(path)
        summary_str = "none"
        keywords_str = "none"
        try:
            with open(path, "r", encoding="utf-8") as f:
                head = f.read(8192)
            summary_str, keywords_str = _parse_butler_frontmatter(head)
        except Exception:
            pass
        fname = os.path.basename(path)
        line = f"{i}. FILE: {fname}\n   PATH: {path}\n   VAULT: {vault_name}\n   BUTLER_SUMMARY: {summary_str}\n   KEYWORDS: {keywords_str}"
        if path in path_to_matched_kws:
            kws = path_to_matched_kws[path]
            quoted = ", ".join(f'"{k}"' for k in kws[:5])
            line += f"\n   Matched: content mentions {quoted}"
        lines.append(line)
    return "\n\n".join(lines), entries


def resolve_references(content: str, context_str: str) -> ReferenceResolutionResponse:
    """Use LLM to select which recent note(s) the user is referring to."""
    system = load_prompt("13-reference-resolution/01-resolve_paths")
    user = f"CONTEXT (recent notes):\n{context_str[:12000]}\n\nCONTENT (user message):\n{content[:2000]}\n\nReturn the PATH(s) from CONTEXT that the user is referring to (exact paths, or empty list)."
    try:
        resp = call_llm_structured(
            system=system,
            user=user,
            model=MODEL_MED,
            response_model=ReferenceResolutionResponse,
            max_retries=2,
        )
        return resp
    except Exception as e:
        memory.log_debug(f"Reference resolution LLM failed: {e}")
        return ReferenceResolutionResponse(selected_paths=[])


def get_reference_append_hours() -> int:
    """Rolling window in hours for append-to-zettel decision. From Settings.yaml, default 72."""
    val = get_setting("reference-append-hours", 72)
    try:
        return int(val) if val is not None else 72
    except (TypeError, ValueError):
        return 72


def apply_append_rule(
    selected_paths: list,
    is_adding_onto: bool,
    entries: list,
) -> tuple:
    """
    Decide append vs link. entries = [(path, mtime, vault_name), ...] from get_recent_notes_for_resolution.
    Returns (append_to_path or None, link_refs: [(path, vault_name), ...]).
    Rule: if is_adding_onto and exactly one selected path and that path is in the rolling window (by mtime), append to it.
    Otherwise return link_refs for all selected paths.
    """
    window_hours = get_reference_append_hours()
    since_ts = time.time() - (window_hours * 3600)
    path_to_mtime = {p: t for p, t, _ in entries}
    in_window = [p for p in selected_paths if path_to_mtime.get(p, 0) >= since_ts]
    if is_adding_onto and len(in_window) == 1:
        return (in_window[0], [])
    link_refs = [(p, _vault_name_for_path(p)) for p in selected_paths]
    return (None, link_refs)


def inject_reference_links(
    content: str, resolved_refs: list, destination_path: str
) -> str:
    """
    resolved_refs = [(path, vault_name), ...]. destination_path = path of the note we're writing to.
    Same vault: [[basename]]. Different vault: (VaultName: [[basename]]).
    """
    if not resolved_refs:
        return content
    dest_vault = _vault_name_for_path(destination_path) if destination_path else ""
    parts = []
    for ref_path, ref_vault in resolved_refs:
        basename = os.path.basename(ref_path)
        if ref_vault == dest_vault:
            parts.append(f"[[{basename}]]")
        else:
            parts.append(f"({ref_vault}: [[{basename}]])")
    prefix = " ".join(parts) + "\n\n"
    return prefix + content


def run_reference_resolution(content: str) -> tuple:
    """
    If content matches reference pattern: load recent notes, resolve, apply append rule.
    Returns (content_or_none, append_to_path or None, link_refs: [(path, vault_name), ...]).
    - If append_to_path set: caller should execute use_zettel_append only (content = original content).
    - If link_refs: caller should run router and inject these links when writing (per-destination).
    - content_or_none: if link_refs, pass original content to router; links injected at write time.
    """
    if not pattern_match_reference(content):
        return (None, None, [])
    context_str, entries = build_recent_notes_context(content=content)
    if not entries:
        return (None, None, [])
    resp = resolve_references(content, context_str)
    selected = [p for p in resp.selected_paths if p and os.path.isfile(p)]
    if not selected:
        return (None, None, [])
    is_adding_onto = pattern_match_adding_onto(content)
    append_path, link_refs = apply_append_rule(selected, is_adding_onto, entries)
    if append_path:
        return (content, append_path, [])
    return (None, None, link_refs)
