"""Memory system: file I/O, caching, context gathering, LLM API layer."""

import datetime
import fcntl
import hashlib
import html
import inspect
import json
import os
import re
import subprocess
import sys
import time
import traceback
import unicodedata

import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from prompt_loader import load_prompt

try:
    import tag_aware_search as tag_search
except ImportError:
    tag_search = None

try:
    import safety_core as _safety_core
except ImportError:
    _safety_core = None

try:
    import yaml
except ImportError:
    yaml = None

# Import all constants and config from types (same package)
from . import types
from .butler_writes_cache import is_template_path, record_butler_write

# Re-export types into this module's namespace so existing code works
from .types import *


class OllamaLockRefusedError(Exception):
    """Raised when lock timeout occurs and we refuse to proceed due to low memory."""


# ==============================================================================
# LOGGING & UTILS
# ==============================================================================


def _timestamp_short():
    """Short timestamp for log lines: MM-DD HH:MM:SS."""
    return datetime.datetime.now().strftime("%m-%d %H:%M:%S")


def _should_show_in_filtered_log(message):
    """
    Return True if message should appear in filtered summary log (llm_router_audit.log).
    Succinct allow-list: only high-signal lines; default is False.
    """
    # Run start
    if "[Runner:" in message or "--- Run:" in message:
        return True

    # Failures and safety
    if "⚠️" in message or "❌" in message:
        return True
    if "[Safety]" in message or "[SAFETY]" in message:
        return True

    # Router one-liner: input snippet + routing decision
    if "[Router]" in message:
        return True

    # Deduction high-signal only
    if "[Deduction] New:" in message:
        return True
    if "[Deduction] Heartbeat failed:" in message:
        return True
    if "[Deduction] ===== HEARTBEAT COMPLETE =====" in message:
        return True
    if "question(s) require attention" in message and "[Deduction]" in message:
        return True

    # YouTube transcription: success/failure only
    if "[YouTube]" in message and (
        "✓" in message or "✅" in message or "COMPLETE" in message
    ):
        return True

    # Report notes save to diary (experiment/devlog/zettel diary writes)
    if "[ReportDiary]" in message:
        return True

    # Everything else stays out of the filtered log
    return False


def _write_to_verbose_log(formatted):
    """Write to VERBOSE_LOG_PATH (main.log). On failure, try fallback under script root so logs are never lost."""
    try:
        verbose_dir = os.path.dirname(VERBOSE_LOG_PATH)
        if not os.path.exists(verbose_dir):
            os.makedirs(verbose_dir, exist_ok=True)
        with open(VERBOSE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(formatted)
        return True
    except Exception as e:
        try:
            fallback = os.path.join(_ROOT, "main.log")
            with open(fallback, "a", encoding="utf-8") as f:
                f.write(formatted)
            return True
        except Exception:
            print(f"CRITICAL LOGGING FAIL (main.log and fallback): {e}", file=sys.stderr)
            return False


def log_debug(message):
    """
    Dual logging: verbose log gets everything, filtered log gets summaries only.
    Always writes to main.log (VERBOSE_LOG_PATH); on failure tries fallback under Note Sorting Scripts.
    """
    timestamp = f"[{_timestamp_short()}]"
    formatted = f"{timestamp} {message}\n"

    _write_to_verbose_log(formatted)

    try:
        if _should_show_in_filtered_log(message):
            with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
                f.write(formatted)
    except Exception as e:
        print(f"CRITICAL LOGGING FAIL (filtered): {e}", file=sys.stderr)


def log_memory_debug(message):
    """Memory system logs: prefixed with [Memory System] for filtering."""
    log_debug("[Memory System] " + message)


def log_report_diary(message):
    """Report notes diary writes: [ReportDiary] + 📋 so entries show in main.log and llm_router_audit.log."""
    log_debug("[ReportDiary] 📋 " + message)


def log_write_failure(operation, path_or_msg, error):
    """Unified audit log for write failures (safety / debugging)."""
    log_memory_debug(f"⚠️ Failed to {operation} '{path_or_msg}': {error}")


def _save_failed_prompt(
    system, user, model, fallback_model, primary_error, fallback_error, stream=False
):
    """Save failed prompt and errors to Attempted Prompts for debugging."""
    try:
        os.makedirs(ATTEMPTED_PROMPTS_DIR, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = os.path.join(ATTEMPTED_PROMPTS_DIR, f"failed_prompt_{ts}.txt")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(f"Model: {model}\nFallback: {fallback_model}\nStream: {stream}\n")
            f.write(f"Primary error: {primary_error or '(none)'}\n")
            f.write(f"Fallback error: {fallback_error or '(none)'}\n\n")
            f.write("--- SYSTEM ---\n")
            f.write(system[:50000] if len(system) > 50000 else system)
            f.write("\n\n--- USER ---\n")
            f.write(user[:50000] if len(user) > 50000 else user)
        log_debug(f"📁 Failed prompt saved to: {fname}")
        return fname
    except Exception as e:
        log_debug(f"⚠️ Could not save failed prompt: {e}")
        return None


def log_run_start(
    runner_name, text_snippet=None, destination=None, skip_runner_line=False
):
    """
    Write bordered run header and runner identifier to both logs.

    If text_snippet and destination are provided, the Runner line includes them.
    If skip_runner_line=True, omit the Runner line (use when log_run_item will be called instead).
    """
    now = datetime.datetime.now()
    run_line = f"--- Run: {now.strftime('%a %b %e %H:%M:%S %z %Y')} ---"
    ts = _timestamp_short()

    if skip_runner_line:
        runner_line = None
    elif text_snippet is not None and destination is not None:
        snip = snippet(text_snippet, 80) if text_snippet else "(no input)"
        runner_line = f'[{ts}] [Runner: {runner_name}] "{snip}" → {destination}'
    else:
        runner_line = f"[{ts}] [Runner: {runner_name}]"

    verbose_block = run_line + "\n" + (runner_line + "\n" if runner_line else "") + "\n"
    _write_to_verbose_log(verbose_block)

    try:
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(run_line + "\n")
            if runner_line:
                f.write(runner_line + "\n")
            f.write("\n")
    except Exception as e:
        print(f"CRITICAL LOGGING FAIL (filtered): {e}", file=sys.stderr)


def log_run_item(runner_name, text_snippet, destination, max_snippet_len=80):
    """
    Log one informative Runner line: snippet + where it went.
    Use for runners that process multiple items (e.g. Note Classifier).
    """
    snip = snippet(text_snippet, max_snippet_len) if text_snippet else "(no input)"
    msg = f'[Runner: {runner_name}] "{snip}" → {destination}'
    log_debug(msg)


def snippet(text, max_len=200):
    """Return a one-line snippet for logging (newlines to space, truncated with ...)."""
    if not text or not str(text).strip():
        return "(no input)"
    one_line = str(text).replace("\n", " ").strip()
    if len(one_line) <= max_len:
        return one_line
    return one_line[:max_len] + "..."


def log_input_for_audit(content, label="Input"):
    """
    Log user/transcript input to main.log (VERBOSE_LOG_PATH).
    When write-shortened-snippet-to-log is true: one line with snippet (current behavior).
    When false: full content in a labeled block for debugging.
    """
    use_snippet = get_setting("write-shortened-snippet-to-log", True)
    ts = _timestamp_short()
    try:
        verbose_dir = os.path.dirname(VERBOSE_LOG_PATH)
        if not os.path.exists(verbose_dir):
            os.makedirs(verbose_dir, exist_ok=True)
        with open(VERBOSE_LOG_PATH, "a", encoding="utf-8") as f:
            if use_snippet:
                snip = snippet(content, 200)
                f.write(f"[{ts}] {label} snippet: {snip}\n")
            else:
                f.write(f"[{ts}] --- Full {label} ---\n")
                f.write((content or "") if content else "(no input)")
                if not (content or "").endswith("\n"):
                    f.write("\n")
                f.write("---\n")
    except Exception as e:
        print(f"CRITICAL LOGGING FAIL: {e}")


def acquire_memory_lock(timeout=30):
    """Acquire lock file for memory processing. Returns True if acquired, False if timeout."""
    import time

    start = time.time()
    while os.path.exists(MEMORY_PROCESSING_LOCK_FILE):
        if time.time() - start > timeout:
            return False
        time.sleep(0.5)
    try:
        with open(MEMORY_PROCESSING_LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        return True
    except:
        return False


def release_memory_lock():
    """Release lock file for memory processing."""
    try:
        if os.path.exists(MEMORY_PROCESSING_LOCK_FILE):
            os.remove(MEMORY_PROCESSING_LOCK_FILE)
    except:
        pass


def clean_think_tags(text):
    """Strip <think>...</think> tags from deepseek-r1 output."""
    import re

    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def get_vault_folder(full_path):
    try:
        if not full_path:
            return "Unknown"
        rel = os.path.relpath(full_path, VAULT_ROOT)
        return rel.split(os.sep)[0]
    except:
        return "External"


def is_safe_path(target_path):
    if not target_path:
        return False
    abs_target = os.path.abspath(target_path)
    return os.path.commonpath([VAULT_ROOT, abs_target]) == VAULT_ROOT


def is_safe_preferences_path(target_path):
    """True if target_path is under PREFERENCES_MEMORY_ROOT (no .. escape)."""
    if not target_path or not PREFERENCES_MEMORY_ROOT:
        return False
    abs_target = os.path.abspath(os.path.normpath(target_path))
    return abs_target == PREFERENCES_MEMORY_ROOT or abs_target.startswith(
        PREFERENCES_MEMORY_ROOT + os.sep
    )


def is_safe_temporal_path(target_path):
    """True if target_path is under TEMPORAL_MEMORIES_ROOT (no .. escape)."""
    if not target_path or not TEMPORAL_MEMORIES_ROOT:
        return False
    abs_target = os.path.abspath(os.path.normpath(target_path))
    return abs_target == TEMPORAL_MEMORIES_ROOT or abs_target.startswith(
        TEMPORAL_MEMORIES_ROOT + os.sep
    )


def is_allowed_priority_path(target_path):
    """
    True if target_path is under VAULT_ROOT, TEMPORAL_MEMORIES_ROOT, or
    PREFERENCES_MEMORY_ROOT. Used for priority reading list and file-to-temporal.
    """
    if not target_path:
        return False
    abs_target = os.path.abspath(os.path.normpath(target_path))
    if VAULT_ROOT and (
        abs_target == VAULT_ROOT or abs_target.startswith(VAULT_ROOT + os.sep)
    ):
        return True
    if TEMPORAL_MEMORIES_ROOT and (
        abs_target == TEMPORAL_MEMORIES_ROOT
        or abs_target.startswith(TEMPORAL_MEMORIES_ROOT + os.sep)
    ):
        return True
    if PREFERENCES_MEMORY_ROOT and (
        abs_target == PREFERENCES_MEMORY_ROOT
        or abs_target.startswith(PREFERENCES_MEMORY_ROOT + os.sep)
    ):
        return True
    return False


def load_ai_personality():
    """
    Load AI personality from IDENTITY.md and SOUL.md under AI-Personality/.
    Returns:
      - identity: # Character section only (for chat persona)
      - soul: SOUL.md content (skills)
      - emoji: parsed from # Character
      - backstory: ## Backstory section
      - full_identity: entire IDENTITY.md (for reflection)
    Cached based on file modification times.
    """

    def _loader():
        out = {
            "identity": "",
            "soul": "",
            "emoji": "",
            "backstory": "",
            "full_identity": "",
        }
        if not TEMPORAL_MEMORIES_ROOT or not is_safe_temporal_path(AI_PERSONALITY_DIR):
            return out
        if not os.path.isdir(AI_PERSONALITY_DIR):
            return out
        if is_safe_temporal_path(IDENTITY_PATH) and os.path.isfile(IDENTITY_PATH):
            content = safe_read_text(IDENTITY_PATH, limit_chars=8000)
            if content:
                out["full_identity"] = content.strip()
                # Extract # Character section (from # Character to next ## or end)
                char_match = re.search(
                    r"^#\s*Character\s*\n(.*?)(?=^##|\Z)",
                    content,
                    re.MULTILINE | re.DOTALL | re.IGNORECASE,
                )
                if char_match:
                    out["identity"] = (
                        "# Character\n\n" + char_match.group(1).strip()
                    ).strip()
                else:
                    out["identity"] = content.strip()
                # Extract ## Backstory section
                back_match = re.search(
                    r"^##\s*Backstory\s*\n(.*?)(?=^##|\Z)",
                    content,
                    re.MULTILINE | re.DOTALL | re.IGNORECASE,
                )
                if back_match:
                    out["backstory"] = back_match.group(1).strip()
                # Parse emoji: "- **Emoji**: X" or "Emoji: X"
                emoji_match = re.search(
                    r"[-*]*\s*\*?\*?Emoji\*?\*?:\s*(.+)",
                    content,
                    re.IGNORECASE,
                )
                if emoji_match:
                    out["emoji"] = emoji_match.group(1).strip().strip("\"'")
        if is_safe_temporal_path(SOUL_PATH) and os.path.isfile(SOUL_PATH):
            soul_content = safe_read_text(SOUL_PATH, limit_chars=8000)
            if soul_content:
                out["soul"] = soul_content.strip()
        out["skills"] = out.get("soul", "")
        return out

    filepaths = []
    if IDENTITY_PATH and is_safe_temporal_path(IDENTITY_PATH):
        filepaths.append(IDENTITY_PATH)
    if SOUL_PATH and is_safe_temporal_path(SOUL_PATH):
        filepaths.append(SOUL_PATH)

    return _get_cached("ai_personality", filepaths, _loader)


def is_safe_weekly_note_path(target_path):
    """True if target_path is under WEEKLY_NOTE_DIR and filename matches Weekly - YYYY MMMM (Www).md."""
    if not target_path or not WEEKLY_NOTE_DIR:
        return False
    abs_target = os.path.abspath(os.path.normpath(target_path))
    if abs_target != WEEKLY_NOTE_DIR and not abs_target.startswith(
        WEEKLY_NOTE_DIR + os.sep
    ):
        return False
    base = os.path.basename(abs_target)
    if not base.endswith(".md"):
        return False
    # Match "Weekly - YYYY MMMM (Www).md" (e.g. Weekly - 2026 February (W06).md)
    if not re.match(r"^Weekly - \d{4} [A-Za-z]+ \(W\d{2}\)\.md$", base):
        return False
    return True


def clean_think_tags(text):
    if not text:
        return None
    if "<think>" in text:
        log_debug("Removing <think> tags from output.")
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def format_wiki_link(filename):
    """
    Formats a filename into a valid Obsidian wiki-link list item purely in code.
    Example: "tiny-experiment-coffee.md" -> "- [[tiny-experiment-coffee]]"
    """
    if not filename:
        return None
    base_name = os.path.splitext(os.path.basename(filename))[0]
    return f"- [[{base_name}]]"


def slugify(text, max_len=80):
    if not text:
        return "untitled"
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:max_len].strip("-") or "untitled"


def ensure_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except Exception as e:
        log_debug(f"⚠️ Failed to create directory '{path}': {e}")
        return False


def safe_read_text(path, limit_chars=5000):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = f.read()
        if limit_chars and len(data) > limit_chars:
            return data[:limit_chars] + "\n\n...[truncated]..."
        return data
    except Exception as e:
        log_debug(f"⚠️ Failed to read memory file '{path}': {e}")
        return ""


def list_immediate_subfolders(root_path):
    if not root_path or not os.path.isdir(root_path):
        return []
    subfolders = []
    try:
        for name in os.listdir(root_path):
            full = os.path.join(root_path, name)
            if os.path.isdir(full) and not name.startswith("."):
                subfolders.append(name)
    except Exception as e:
        log_debug(f"⚠️ list_immediate_subfolders failed: {e}")
        return []
    return sorted(subfolders)


def list_md_files_in_folder(folder_path):
    if not folder_path or not os.path.isdir(folder_path):
        return []
    files = []
    try:
        for name in os.listdir(folder_path):
            full = os.path.join(folder_path, name)
            if (
                os.path.isfile(full)
                and name.lower().endswith(".md")
                and not name.startswith(".")
            ):
                files.append(full)
    except Exception as e:
        log_debug(f"⚠️ list_md_files_in_folder failed: {e}")
        return []
    return sorted(files)


def auto_sort_note_memories():
    """
    Auto-organize memory files from the inbox into topic subfolders.

    Strategy:
    - Look at NOTE_SORTER_MEMORY_INBOX_FOLDER only.
    - For each .md file there, ask the model which existing folder it belongs in,
      or whether to create a new folder, or keep it in the inbox.
    - Move files only within NOTE_SORTER_MEMORY_ROOT.
    """
    try:
        ensure_dir(NOTE_SORTER_MEMORY_ROOT)
        inbox_folder = os.path.join(
            NOTE_SORTER_MEMORY_ROOT, NOTE_SORTER_MEMORY_INBOX_FOLDER
        )
        if not os.path.isdir(inbox_folder):
            return

        all_subfolders = list_immediate_subfolders(NOTE_SORTER_MEMORY_ROOT)
        existing_topic_folders = [
            f for f in all_subfolders if f != NOTE_SORTER_MEMORY_INBOX_FOLDER
        ]

        inbox_files = list_md_files_in_folder(inbox_folder)
        if not inbox_files:
            return

        for path in inbox_files:
            content = safe_read_text(path, limit_chars=4000)
            if not content:
                continue

            system = """You are an organizer for Note Sorter memory files.
Each memory file describes a reusable Apple Notes routing rule (note_type, Apple Note name, tag, when_to_use).

Your job:
- Decide if this memory clearly belongs in an existing topic subfolder,
  should cause a new topic folder to be created, or should stay in the inbox.

Guidelines:
- Prefer moving into a specific existing folder if it clearly matches.
- Only create a new folder if the memory describes a distinct category not covered by current folders.
- If you are unsure, keep it in the inbox.

Output ONLY JSON with this schema:
{
  "action": "move_existing" | "create_new" | "stay_in_inbox",
  "target_folder": "ExistingFolderName or null",
  "new_folder_name": "NewFolderName or null"
}
"""

            user = (
                "MEMORY FILE CONTENT (header + notes):\n"
                f"{content[:3000]}\n\n"
                "EXISTING TOPIC FOLDERS (excluding inbox):\n"
                + (
                    "\n".join([f"- {name}" for name in existing_topic_folders])
                    or "- (none yet)"
                )
            )

            try:
                from .llm_client import call_llm_structured
                from .llm_models import MemorySortAction

                data = call_llm_structured(
                    system,
                    user,
                    MODEL_MED,
                    response_model=MemorySortAction,
                    max_retries=2,
                )
            except Exception as e:
                log_debug(f"⚠️ auto_sort memory LLM failed: {e}")
                data = None

            dest_folder_name = None
            if data:
                action = data.action
                target_folder = data.target_folder
                new_folder_name = data.new_folder_name
                if action == "move_existing" and isinstance(target_folder, str):
                    if target_folder in existing_topic_folders:
                        dest_folder_name = target_folder
                elif action == "create_new" and isinstance(new_folder_name, str):
                    clean_name = new_folder_name.strip()
                    if clean_name and clean_name != NOTE_SORTER_MEMORY_INBOX_FOLDER:
                        dest_folder_name = clean_name

            if not dest_folder_name:
                continue

            dest_folder = os.path.join(NOTE_SORTER_MEMORY_ROOT, dest_folder_name)
            if not ensure_dir(dest_folder):
                continue

            dest_path = os.path.join(dest_folder, os.path.basename(path))
            try:
                os.rename(path, dest_path)
                log_debug(
                    f"🗂️ Auto-sorted memory file from inbox -> '{dest_folder_name}': {dest_path}"
                )
            except Exception as move_err:
                log_debug(
                    f"⚠️ Failed to move memory file '{path}' -> '{dest_path}': {move_err}"
                )
    except Exception as outer_err:
        log_debug(f"⚠️ auto_sort_note_memories encountered an error: {outer_err}")


def pick_memory_folders_for_note(content, subfolders):
    """
    Pass 1: Given note content and available memory subfolders, pick likely folders.
    Returns a list of folder names (matching the provided subfolders exactly).
    """
    if not subfolders:
        return []

    system = """You are a memory librarian for a note-sorting system.
Given the note content and a list of existing memory subfolders, pick the 1-3 most relevant subfolders to search for a mapping that tells:
- which Apple Note name to use
- which Apple Notes tag to use

Rules:
- Only choose from the provided folder names (exact match).
- If none seem relevant, return an empty list.
- Output ONLY valid JSON in this schema:
  { "folders": ["Folder Name", "..."] }
"""

    user = (
        "NOTE CONTENT (snippet):\n"
        f"{content[:1200]}\n\n"
        "AVAILABLE SUBFOLDERS:\n" + "\n".join([f"- {name}" for name in subfolders])
    )

    try:
        from .llm_client import call_llm_structured
        from .llm_models import FoldersResponse

        data = call_llm_structured(
            system,
            user,
            MODEL_MED,
            response_model=FoldersResponse,
            max_retries=2,
        )
        picked = [f for f in data.folders if isinstance(f, str) and f in subfolders]
        return picked[:3]
    except Exception as e:
        log_memory_debug(f"⚠️ pick_memory_folders_for_note failed: {e}")
    return []


def pick_or_create_apple_notes_mapping(content, memory_candidates):
    """
    Pass 2: Choose an existing memory file OR create a new mapping.
    memory_candidates: list of dicts: { "rel": "Sub/Name.md", "content": "..." }
    """
    system = """You route content into Apple Notes using a learned memory system.

Goal:
- Pick the best Apple Note name and a single Apple Notes tag for this content.
- Prefer reusing an existing memory mapping if it fits.
- If no existing mapping fits, invent a new note type, a clear note name, and a good tag.

Critical thinking prompt (use this to decide note_type):
- How will this information be searched/retrieved later?
- Is it a recurring log, a reference list, a project tracker, or a one-off?
- Should it be grouped with similar entries into one long-running Apple Note?
- What tag would make filtering inside Apple Notes easy and consistent?

Rules:
- Tag must start with '#', use only letters/numbers/underscores (no spaces).
- note_name should be a short human-friendly title (no tag symbols).
- If you choose an existing memory file, set create_new_memory_file=false and use_memory_file to that rel path.
- If creating new, set create_new_memory_file=true and propose:
  - memory_file_folder: either an existing folder name from the provided candidates, or '00 Inbox'
  - memory_file_name: a slug-like filename ending in '.md' derived from note_type

Output ONLY valid JSON with this schema:
{
  "note_type": "string",
  "note_name": "string",
  "tag": "#tag_string",
  "use_memory_file": "relative/path.md or null",
  "create_new_memory_file": true/false,
  "memory_file_folder": "string",
  "memory_file_name": "string",
  "when_to_use": "1-2 sentence rule"
}
"""

    candidates_block = "MEMORY CANDIDATES:\n"
    if memory_candidates:
        for item in memory_candidates[:25]:
            candidates_block += (
                f"\n---\nFILE: {item.get('rel')}\n"
                f"{(item.get('content') or '')[:2500]}\n"
            )
    else:
        candidates_block += "\n(None)\n"

    user = (
        f"NOTE CONTENT (full or long snippet):\n{content[:3500]}\n\n" + candidates_block
    )

    try:
        from .llm_client import call_llm_structured
        from .llm_models import ResolveAppleNotesResponse

        data = call_llm_structured(
            system,
            user,
            MODEL_SMART_MakeRouterDecisions,
            response_model=ResolveAppleNotesResponse,
            max_retries=2,
        )
    except Exception as e:
        log_memory_debug(f"⚠️ resolve_apple_notes_target_from_memories LLM failed: {e}")
        data = None

    note_type = (
        (data.note_type or "") if data and isinstance(data.note_type, str) else ""
    )
    note_name = (
        (data.note_name or "") if data and isinstance(data.note_name, str) else ""
    )
    tag = (data.tag or "") if data and isinstance(data.tag, str) else ""
    use_memory_rel = (
        data.use_memory_file if data and isinstance(data.use_memory_file, str) else None
    )
    create_new = bool(data.create_new_memory_file) if data else True
    folder = (
        (data.memory_file_folder or "")
        if data and isinstance(data.memory_file_folder, str)
        else ""
    )
    filename = (
        (data.memory_file_name or "")
        if data and isinstance(data.memory_file_name, str)
        else ""
    )
    when_to_use = (
        (data.when_to_use or "") if data and isinstance(data.when_to_use, str) else ""
    )

    if use_memory_rel:
        create_new = False
    else:
        create_new = True

    if not tag.startswith("#"):
        tag = "#" + tag.lstrip("#")
    tag = re.sub(r"[^#A-Za-z0-9_]", "_", tag)
    if not note_name:
        note_name = "Inbox"
    if not note_type:
        note_type = note_name
    if not when_to_use:
        when_to_use = "Use this Apple Note for this type of entry."

    if not filename or not filename.lower().endswith(".md"):
        filename = slugify(note_type) + ".md"
    if not folder:
        folder = NOTE_SORTER_MEMORY_INBOX_FOLDER
    folder = os.path.basename(folder.strip()) or NOTE_SORTER_MEMORY_INBOX_FOLDER

    return {
        "note_type": note_type.strip(),
        "note_name": note_name.strip(),
        "tag": tag.strip(),
        "use_memory_rel": use_memory_rel,
        "create_new": create_new,
        "new_memory_folder": folder.strip(),
        "new_memory_filename": os.path.basename(filename.strip()),
        "when_to_use": when_to_use.strip(),
    }


def _safe_write_wrapper(operation_func, operation_name, validation_func=None):
    """
    Wrap a write operation with safety checks and checkpointing.

    Args:
        operation_func: Callable with no args that performs the write
        operation_name: Name for logging
        validation_func: Optional function to validate result (default: lambda r: r is not None)
    """
    if SAFETY_ENABLED and _safety_core:
        return _safety_core.safe_write_operation(
            operation_func,
            operation_name,
            validation_func=validation_func or (lambda r: r is not None),
            create_checkpoint_before=False,
        )
    return operation_func()


def write_new_memory_file(mapping, content):
    """
    Writes a new memory file describing the mapping. Returns absolute path or None.
    """

    def _do():
        return _write_new_memory_file_impl(mapping, content)

    return _safe_write_wrapper(_do, "write-new-memory-file")


def _write_new_memory_file_impl(mapping, content):
    """Internal: write memory file to disk. See write_new_memory_file."""
    ensure_dir(NOTE_SORTER_MEMORY_ROOT)
    target_folder_name = (
        mapping.get("new_memory_folder") or NOTE_SORTER_MEMORY_INBOX_FOLDER
    )
    if not isinstance(target_folder_name, str):
        target_folder_name = NOTE_SORTER_MEMORY_INBOX_FOLDER

    target_folder = os.path.join(NOTE_SORTER_MEMORY_ROOT, target_folder_name)
    if not ensure_dir(target_folder):
        target_folder = os.path.join(
            NOTE_SORTER_MEMORY_ROOT, NOTE_SORTER_MEMORY_INBOX_FOLDER
        )
        ensure_dir(target_folder)

    base_name = mapping.get("new_memory_filename") or (
        slugify(mapping.get("note_type")) + ".md"
    )
    base_name = os.path.basename(base_name)
    if not base_name.lower().endswith(".md"):
        base_name = base_name + ".md"

    path = os.path.join(target_folder, base_name)
    if os.path.exists(path):
        stem = os.path.splitext(base_name)[0]
        idx = 2
        while True:
            candidate = os.path.join(target_folder, f"{stem}-{idx}.md")
            if not os.path.exists(candidate):
                path = candidate
                break
            idx += 1

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    note_type = mapping.get("note_type", "").strip()
    note_name = mapping.get("note_name", "").strip()
    tag = mapping.get("tag", "").strip()
    when_to_use = mapping.get("when_to_use", "").strip()

    body = (
        f"# Note Sorter Memory: {note_type}\n\n"
        f"- **Created**: {now}\n"
        f"- **Apple Note name**: {note_name}\n"
        f"- **Apple Notes tag**: {tag}\n"
        f"- **When to use**: {when_to_use}\n\n"
        "## Notes\n"
        "- This memory file records a routing decision for Apple Notes.\n"
        "- If future entries match this note type, reuse this Apple Note name and tag.\n\n"
        "## Example input that triggered this mapping\n"
        "```text\n"
        f"{content[:1200]}\n"
        "```\n"
    )

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        log_debug(f"Wrote new memory file: {path}")
        record_butler_write(path)
        return path
    except Exception as e:
        log_write_failure("write memory file", path, e)
        return None


def resolve_apple_notes_target_from_memories(content):
    """
    Uses the memory directory to select or create a (note_name, tag) mapping for Apple Notes.

    Two-pass behavior when memories exist:
    - Pass 1: pick relevant subfolders to search
    - Pass 2: pick an existing memory file or create a new mapping
    """
    if not content:
        return {
            "note_name": "Inbox",
            "tag": "#inbox",
            "note_type": "Inbox",
            "memory_written_path": None,
        }

    ensure_dir(NOTE_SORTER_MEMORY_ROOT)
    ensure_dir(os.path.join(NOTE_SORTER_MEMORY_ROOT, NOTE_SORTER_MEMORY_INBOX_FOLDER))

    subfolders = list_immediate_subfolders(NOTE_SORTER_MEMORY_ROOT)
    md_files_anywhere = []
    for folder_name in subfolders:
        md_files_anywhere.extend(
            list_md_files_in_folder(os.path.join(NOTE_SORTER_MEMORY_ROOT, folder_name))
        )

    if not md_files_anywhere:
        mapping = pick_or_create_apple_notes_mapping(content, memory_candidates=[])
        mapping["create_new"] = True
        written = write_new_memory_file(mapping, content)
        return {
            "note_name": mapping["note_name"],
            "tag": mapping["tag"],
            "note_type": mapping["note_type"],
            "memory_written_path": written,
        }

    picked_folders = pick_memory_folders_for_note(content, subfolders) or subfolders[:3]
    memory_candidates = []
    for folder_name in picked_folders:
        folder_path = os.path.join(NOTE_SORTER_MEMORY_ROOT, folder_name)
        for fp in list_md_files_in_folder(folder_path)[:30]:
            rel = os.path.relpath(fp, NOTE_SORTER_MEMORY_ROOT)
            memory_candidates.append({
                "rel": rel,
                "content": safe_read_text(fp, limit_chars=5000),
            })

    mapping = pick_or_create_apple_notes_mapping(
        content, memory_candidates=memory_candidates
    )

    written = None
    if mapping.get("create_new"):
        for cand in memory_candidates:
            ctext = cand.get("content") or ""
            if mapping.get("note_name") and mapping.get("tag"):
                if mapping["note_name"] in ctext and mapping["tag"] in ctext:
                    mapping["create_new"] = False
                    break

    if mapping.get("create_new"):
        allowed_folders = set(subfolders + [NOTE_SORTER_MEMORY_INBOX_FOLDER])
        if mapping.get("new_memory_folder") not in allowed_folders:
            mapping["new_memory_folder"] = NOTE_SORTER_MEMORY_INBOX_FOLDER
        written = write_new_memory_file(mapping, content)

    # Give the system a chance to tidy the inbox after any new memory is written.
    auto_sort_note_memories()

    return {
        "note_name": mapping["note_name"],
        "tag": mapping["tag"],
        "note_type": mapping["note_type"],
        "memory_written_path": written,
    }


# ==============================================================================
# ==============================================================================
# PREFERENCES MEMORY (My Preferences - separate from Note Sorter)
# ==============================================================================


def pick_preferences_file_or_new(content, memory_candidates):
    """
    Choose an existing preference file or propose a new one.
    memory_candidates: list of dicts { "rel": "filename.md", "content": "..." }.
    Returns either {"use_existing": "coffee.md"} or
    {"create_new": True, "new_filename": "coffee.md", "topic": "Coffee"}.
    """
    system = """You are a librarian for a "My Preferences" (Information on Moi) memory system. The user has stated preferences or facts about themselves.

Goal: Either pick an existing file that matches the topic, or propose a new filename using BROAD, human-friendly categories (how a person would file things away).

Category guidance (10-20 broad categories; prefer these when creating new files):
- health, home, smart-home, food, coffee, tea, skincare, fitness, hobbies, tech, work, family, travel, pets, finance, media, reading, music, etc.
- Think: "How would a person organize this in a filing cabinet?" Use general category names, not product-specific names.
- Example: "Mom bought a Tapo camera for living room" -> home.md or smart-home.md (NOT tapo-camera.md). Specifics go in tags inside the file.
- Example: "I prefer medium roast" -> coffee.md. Example: "sensitive skin" -> skincare.md or health.md.

Rules:
- Only choose from the provided file list (exact filename match) if one clearly matches the topic.
- If no existing file fits, set create_new=true and set new_filename to a BROAD slug (e.g. smart-home.md, health.md, coffee.md). Topic should be a human-readable title (e.g. Smart Home, Health, Coffee).
- new_filename must end with .md and contain only letters, numbers, hyphens.

Output ONLY valid JSON with this schema:
{
  "use_existing": "filename.md or null",
  "create_new": true or false,
  "new_filename": "slug.md or null",
  "topic": "Human-readable topic or null"
}
"""
    candidates_block = "EXISTING FILES:\n"
    if memory_candidates:
        for item in memory_candidates[:30]:
            candidates_block += (
                f"\n---\nFILE: {item.get('rel')}\n"
                f"{(item.get('content') or '')[:1500]}\n"
            )
    else:
        candidates_block += "\n(None)\n"

    user = f"USER CONTENT (snippet):\n{content[:2500]}\n\n" + candidates_block

    try:
        from .llm_client import call_llm_structured
        from .llm_models import AppleNotesMappingResponse

        data = call_llm_structured(
            system,
            user,
            MODEL_MED,
            response_model=AppleNotesMappingResponse,
            max_retries=2,
        )
    except Exception as e:
        log_memory_debug(f"⚠️ pick_or_create_apple_notes_mapping failed: {e}")
        data = None

    use_existing = (
        data.use_existing
        if data and isinstance(data.use_existing, str) and data.use_existing
        else None
    )
    create_new = bool(data.create_new) if data else False
    new_filename = (
        data.new_filename if data and isinstance(data.new_filename, str) else None
    )
    topic = data.topic if data and isinstance(data.topic, str) else None

    if use_existing:
        base = os.path.basename(use_existing)
        if base.endswith(".md"):
            return {"use_existing": base}
    if create_new and new_filename:
        base = os.path.basename(new_filename.strip())
        if not base.lower().endswith(".md"):
            base = base + ".md"
        base = slugify(os.path.splitext(base)[0], max_len=60) + ".md"
        topic = (topic or base.replace(".md", "").replace("-", " ")).strip()
        return {"create_new": True, "new_filename": base, "topic": topic or base}

    return {
        "create_new": True,
        "new_filename": "preferences.md",
        "topic": "Preferences",
    }


def _clean_and_validate_tags(tags, max_count=5):
    """
    Clean and validate a list of tags.

    Args:
        tags: List of tag strings
        max_count: Maximum number of tags to return

    Returns:
        List of cleaned, validated tags
    """
    clean_tags = []
    for t in tags[:max_count]:
        if isinstance(t, str) and t.strip():
            t = t.strip()
            if not t.startswith("#"):
                t = "#" + t
            t = re.sub(r"[^#A-Za-z0-9_-]", "_", t)
            if t and t != "#":
                clean_tags.append(t)
    return clean_tags


def extract_facts_with_tags(content, context_type="preference"):
    """
    Extract factual statements with relevant inline tags.
    context_type: "preference" for Information on Moi (preferences, attributes),
                  "temporal" for activities, tasks, intentions.
    Returns list of dicts: [{"fact": "...", "tags": ["#tag1", "#tag2"]}].
    """
    if not content or not content.strip():
        return []
    if context_type == "preference":
        system = """You extract the user's preference and attribute statements from their message, with searchable tags for each fact.
Ignore the task or request (e.g. "Give me a comparison...", "I bought X today").

For each fact you extract:
- fact: one short, clear statement (e.g. "Prefer medium roast for espresso", "Living room has a Tapo camera").
- tags: 1-5 hashtags that make this fact searchable. Use lowercase, hyphenated (e.g. #medium-roast #espresso #smart-home-devices #cctv-camera #living-room).

Include BOTH preferences (likes, dislikes, habits) AND attributes (facts about the user). If there are none, output empty list.

Output ONLY valid JSON:
{ "facts": [ { "fact": "statement", "tags": ["#tag1", "#tag2"] }, ... ] }"""
    else:
        system = """You extract temporal/activity information from the user's message: what they said they would do, are doing, or what can be inferred about their activities, tasks, intentions.
Ignore preferences or personal attributes (those go elsewhere).
DO NOT extract information about how to sort notes, Apple Notes routing rules, or note organization instructions (those belong in Note Sorter Memories).

For each activity/fact you extract:
- fact: one short statement (e.g. "Setting up a Tapo camera in living room", "Worked on Python script").
- tags: 1-5 hashtags that make this searchable. Use lowercase, hyphenated (e.g. #smart-home #cctv-camera #living-room #programming #python).

If there is nothing temporal, output empty list.

Output ONLY valid JSON:
{ "facts": [ { "fact": "statement", "tags": ["#tag1", "#tag2"] }, ... ] }"""

    user = f"USER MESSAGE:\n{content[:3500]}"
    try:
        from .llm_client import call_llm_structured
        from .llm_models import FactsResponse

        data = call_llm_structured(
            system,
            user,
            MODEL_MED,
            response_model=FactsResponse,
            max_retries=2,
        )
        out = []
        for item in data.facts:
            fact = (item.fact or "").strip()
            if not fact:
                continue
            clean_tags = _clean_and_validate_tags(item.tags, 5)
            out.append({"fact": fact, "tags": clean_tags})
        return out
    except Exception as e:
        log_memory_debug(f"⚠️ extract_facts_with_tags failed: {e}")
    return []


def _format_facts_with_tags_as_bullets(facts_with_tags):
    """Format list from extract_facts_with_tags as markdown bullets with inline tags."""
    if not facts_with_tags:
        return ""
    lines = []
    for item in facts_with_tags:
        fact = item.get("fact", "")
        tags = item.get("tags", [])
        tag_str = " " + " ".join(tags) if tags else ""
        lines.append(f"- {fact}{tag_str}")
    return "\n".join(lines)


def extract_preference_statements(content):
    """
    Extract preference and attribute statements from user content (no task/request),
    with inline tags for searchability. Returns a string of markdown bullets with tags,
    or empty string if none found.
    """
    if not content or not content.strip():
        return ""
    facts_with_tags = extract_facts_with_tags(content, context_type="preference")
    return _format_facts_with_tags_as_bullets(facts_with_tags)


def save_preferences_to_memory(
    statements, use_existing_filename=None, new_filename=None, topic=None
):
    """
    Append to an existing preference file or create a new one under PREFERENCES_MEMORY_ROOT.
    - statements: markdown bullet block with optional inline tags (from extract_preference_statements),
      e.g. "- Prefer medium roast #medium-roast #espresso".
    - use_existing_filename: e.g. "coffee.md" to append.
    - new_filename: e.g. "coffee.md" when creating.
    - topic: e.g. "Coffee" for the heading when creating.
    Returns absolute path written, or None.
    """

    def _do():
        return _save_preferences_to_memory_impl(
            statements, use_existing_filename, new_filename, topic
        )

    return _safe_write_wrapper(_do, "save-preferences")


def _save_preferences_to_memory_impl(
    statements, use_existing_filename=None, new_filename=None, topic=None
):
    """Internal: save preferences to disk. See save_preferences_to_memory."""
    if not statements or not statements.strip():
        return None
    ensure_dir(PREFERENCES_MEMORY_ROOT)
    now = datetime.datetime.now().strftime("%Y-%m-%d")
    block = f"\n\n## {now}\n\n{statements.strip()}\n"

    if use_existing_filename:
        base = os.path.basename(use_existing_filename)
        if not base.endswith(".md"):
            base = base + ".md"
        path = os.path.join(PREFERENCES_MEMORY_ROOT, base)
        if not is_safe_preferences_path(path):
            log_memory_debug(f"⚠️ Unsafe preferences path: {path}")
            return None
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(block)
            log_memory_debug(f"Appended preferences to {path}")
            return path
        except Exception as e:
            log_write_failure("append preferences to", path, e)
            return None

    if new_filename and topic:
        base = os.path.basename(new_filename)
        if not base.endswith(".md"):
            base = base + ".md"
        path = os.path.join(PREFERENCES_MEMORY_ROOT, base)
        if not is_safe_preferences_path(path):
            log_memory_debug(f"⚠️ Unsafe preferences path: {path}")
            return None
        body = f"# {topic}\n\n{statements.strip()}\n"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
            log_memory_debug(f"Created preferences file: {path}")
            return path
        except Exception as e:
            log_write_failure("write preferences", path, e)
            return None
    return None


def get_preferences_context(prompt_text):
    """
    Return a "## Context" section with relevant saved preferences to append to the bottom of a prompt.

    First tries tag-based search across preferences; then falls back to file-based selection.
    Callers should append this to the prompt so the model sees the user's saved preferences.

    Usage (e.g. in Alfred or a chat script):
        context_block = get_preferences_context(user_message)
        full_prompt = user_message + "\\n\\n" + context_block
    """
    if not prompt_text or not str(prompt_text).strip():
        return "## Context\n\n(No relevant preferences.)"

    ensure_dir(PREFERENCES_MEMORY_ROOT)
    parts = []
    source_paths = []

    # 1. Tag-based search (preferences only)
    if tag_search:
        tag_context = search_memories_by_tags(
            prompt_text, memory_types=["preferences"], max_results=15
        )
        if tag_context and tag_context.strip():
            parts.append("### From memory (tag-matched)\n\n" + tag_context.strip())

    # 2. File-based selection (fallback / additional)
    md_files = list_md_files_in_folder(PREFERENCES_MEMORY_ROOT)
    if md_files:
        file_list = [os.path.basename(fp) for fp in md_files]
        system = """You select which preference files are relevant to the user's prompt or query.

Given the list of existing preference filenames (e.g. coffee.md, tea.md) and the user's text,
output ONLY valid JSON: { "relevant_files": ["coffee.md", ...] }.
- Pick 0 to 3 files that are clearly relevant (e.g. "compare these coffees" -> coffee.md).
- If none are relevant, use an empty list: { "relevant_files": [] }.
- Use only exact filenames from the provided list."""
        user = f"USER TEXT:\n{prompt_text[:2000]}\n\nEXISTING FILES:\n" + "\n".join([
            f"- {f}" for f in file_list
        ])
        try:
            from .llm_client import call_llm_structured
            from .llm_models import RelevantFilesResponse

            data = call_llm_structured(
                system,
                user,
                MODEL_MED,
                response_model=RelevantFilesResponse,
                max_retries=2,
            )
            relevant = [
                f for f in data.relevant_files if isinstance(f, str) and f in file_list
            ][:3]
        except Exception as e:
            log_memory_debug(f"⚠️ get_preferences_context file selection failed: {e}")
            relevant = []
        for name in relevant:
            path = os.path.join(PREFERENCES_MEMORY_ROOT, name)
            if not is_safe_preferences_path(path) or not os.path.isfile(path):
                continue
            content = safe_read_text(path, limit_chars=4000)
            if content:
                parts.append(f"### {os.path.splitext(name)[0]}\n\n{content.strip()}")
                source_paths.append(path)

    if not parts:
        return ""  # "## Context\n\n(No relevant preferences for this query.)"

    context_str = "\n\n---\n\n".join(parts)
    # Optional context expansion when few results
    try:
        import context_expander

        confidence = context_expander.calculate_context_confidence(
            context_str, prompt_text[:500] if prompt_text else ""
        )
        if context_expander.should_expand_context(
            confidence,
            len(source_paths),
            depth=0,
            max_depth=CONTEXT_EXPANSION_MAX_DEPTH,
            files_so_far=len(source_paths),
            max_files=CONTEXT_EXPANSION_MAX_FILES_PER_SESSION,
            confidence_threshold=CONTEXT_EXPANSION_CONFIDENCE_THRESHOLD,
            min_evidence_threshold=CONTEXT_EXPANSION_MIN_EVIDENCE_THRESHOLD,
        ):
            allowed_roots = [PREFERENCES_MEMORY_ROOT, TEMPORAL_MEMORIES_ROOT]
            expanded = context_expander.expand_from_evidence(
                context_str,
                source_paths,
                max_depth=CONTEXT_EXPANSION_MAX_DEPTH,
                max_files=CONTEXT_EXPANSION_MAX_FILES_PER_SESSION,
                max_bytes=CONTEXT_EXPANSION_MAX_BYTES_PER_SESSION,
                per_file_limit=10000,
                allowed_roots=allowed_roots,
            )
            if expanded.get("content"):
                parts.append("### Expanded Context\n\n" + expanded["content"])
                log_memory_debug(
                    f"[Context Expand] Preferences context: {expanded.get('depth', 0)} levels, "
                    f"{len(expanded.get('paths', []))} files"
                )
    except Exception as e:
        log_memory_debug(f"⚠️ Context expansion in get_preferences_context: {e}")

    return "## Context\n\n" + "\n\n---\n\n".join(parts)


def extract_relevant_tags_from_query(query_text):
    """
    Use LLM to extract likely tags from a natural language query.
    E.g. "What camera is in living room?" -> ["#living-room", "#cctv-camera", "#smart-home-devices"]
    Returns list of tag strings (with #).
    """
    if not query_text or not str(query_text).strip():
        return []
    system = """You extract 1-8 searchable hashtags that might appear in the user's memory files, based on their query.
Tags should be lowercase, hyphenated (e.g. #living-room #cctv-camera #smart-home-devices #coffee-preference #medium-roast).
Think about what facts or preferences would be tagged in memory (home devices, locations, preferences, activities).
Output ONLY valid JSON: { "tags": ["#tag1", "#tag2", ...] }"""
    user = f"USER QUERY:\n{str(query_text).strip()[:1500]}"
    try:
        from .llm_client import call_llm_structured
        from .llm_models import TagsResponse

        data = call_llm_structured(
            system,
            user,
            MODEL_MED,
            response_model=TagsResponse,
            max_retries=2,
        )
        return [t.lower() for t in _clean_and_validate_tags(data.tags, 8)]
    except Exception as e:
        log_memory_debug(f"⚠️ extract_relevant_tags_from_query failed: {e}")
    return []


def search_memories_by_tags(query_or_tags, memory_types=None, max_results=20):
    """
    Search across memory systems using tags.
    query_or_tags: natural language query (string) OR list of tag strings (e.g. ["#living-room", "#cctv-camera"]).
    memory_types: ["preferences", "temporal", "deductions"] or ["all"]. Default ["all"].
    Returns formatted context string with matching entries, or empty string if none or tag_search unavailable.
    """
    if tag_search is None:
        return ""
    if memory_types is None:
        memory_types = ["all"]
    tags_list = []
    if isinstance(query_or_tags, str):
        tags_list = extract_relevant_tags_from_query(query_or_tags)
    elif isinstance(query_or_tags, list):
        tags_list = [t for t in query_or_tags if isinstance(t, str) and t.strip()]
    if not tags_list:
        return ""

    roots = []
    if "all" in memory_types:
        roots = [
            ("preferences", PREFERENCES_MEMORY_ROOT),
            ("temporal", TEMPORAL_MEMORIES_ROOT),
        ]
        deductions_dir = os.path.join(
            TEMPORAL_MEMORIES_ROOT, TEMPORAL_DEDUCTIONS_FOLDER
        )
        if os.path.isdir(deductions_dir):
            roots.append(("deductions", deductions_dir))
    else:
        if "preferences" in memory_types:
            roots.append(("preferences", PREFERENCES_MEMORY_ROOT))
        if "temporal" in memory_types or "deductions" in memory_types:
            if "temporal" in memory_types:
                roots.append(("temporal", TEMPORAL_MEMORIES_ROOT))
            if "deductions" in memory_types:
                deductions_dir = os.path.join(
                    TEMPORAL_MEMORIES_ROOT, TEMPORAL_DEDUCTIONS_FOLDER
                )
                if os.path.isdir(deductions_dir):
                    roots.append(("deductions", deductions_dir))

    results = tag_search.search_by_tags(tags_list, roots, max_results=max_results)
    return tag_search.format_search_results(results, context_type="full")


# ==============================================================================
# TEMPORAL MEMORIES (day-scoped in root; weekly/monthly summaries; Deductions)
# ==============================================================================


def extract_temporal_memories(content):
    """
    Extract "what the user told the AI to do" and "what the AI deciphered about
    the user's activities" (tasks, intentions, activities), with inline tags.
    Returns short bullet list with tags, or empty string if nothing temporal.
    """
    if not content or not content.strip():
        return ""
    facts_with_tags = extract_facts_with_tags(content, context_type="temporal")
    return _format_facts_with_tags_as_bullets(facts_with_tags)


def _append_to_temporal_daily_file(date_str, time_str, extracted_text):
    """Append temporal memory to daily file with safety checks."""
    ensure_dir(TEMPORAL_MEMORIES_ROOT)
    daily_dir = os.path.join(TEMPORAL_MEMORIES_ROOT, TEMPORAL_DAILY_FOLDER)
    ensure_dir(daily_dir)
    path = os.path.join(daily_dir, f"{date_str}.md")

    if not is_safe_temporal_path(path):
        log_memory_debug(f"⚠️ Unsafe temporal path: {path}")
        return None

    block = f"\n\n## {time_str}\n\n{extracted_text.strip()}\n"

    try:
        if not os.path.isfile(path):
            header = f"# Temporal memories {date_str}\n"
            with open(path, "w", encoding="utf-8") as f:
                f.write(header + block.lstrip())
        else:
            with open(path, "a", encoding="utf-8") as f:
                f.write(block)
        log_memory_debug(f"Appended temporal memory -> daily/{date_str}.md")
        return path
    except Exception as e:
        log_memory_debug(f"⚠️ Failed to append temporal memory to '{path}': {e}")
        return None


def append_temporal_memory(extracted_text):
    """
    Append extracted temporal memory to today's daily file under TEMPORAL_MEMORIES_ROOT/daily.
    extracted_text: bullet list, optionally with inline tags (from extract_temporal_memories),
      e.g. "- Setting up camera in living room #smart-home #cctv-camera".
    File: daily/YYYY-MM-DD.md. Creates file with header if missing; appends ## HH:MM block.
    Returns path written or None.
    """
    if not extracted_text or not extracted_text.strip():
        return None
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    return _append_to_temporal_daily_file(date_str, time_str, extracted_text)


def append_ai_observation_to_temporal(observation_text, context_tags=None):
    """
    Append AI's observation/reflection to temporal memories.
    observation_text: What the AI observed/did from its perspective
    context_tags: Optional list of tags like ['#pattern-synthesis', '#deduction']
    """
    if not observation_text or not observation_text.strip():
        return None

    # Format with tags if provided
    if context_tags:
        tags = " ".join(context_tags)
        formatted = f"- {observation_text} {tags}"
    else:
        formatted = f"- {observation_text}"

    return append_temporal_memory(formatted)


def append_temporal_staging(content, event_type="event"):
    """
    Append a staging entry for later batch diary composition (batch staging).
    Writes HH:MM | event_type | summary to daily/staging/YYYY-MM-DD.md.
    If content is short enough (<= STAGING_SUMMARIZE_ABOVE_CHARS), use it
    truncated to STAGING_MAX_CHARS. If longer, use llama3.1:8b to summarize
    to at most STAGING_MAX_CHARS. Called by write_structured_temporal_memory
    and write_ai_observation_to_temporal.
    Returns path written or None.
    """
    if not content or not str(content).strip():
        return None
    ensure_dir(TEMPORAL_MEMORIES_ROOT)
    daily_dir = os.path.join(TEMPORAL_MEMORIES_ROOT, TEMPORAL_DAILY_FOLDER)
    staging_dir = os.path.join(daily_dir, TEMPORAL_STAGING_FOLDER)
    ensure_dir(staging_dir)
    ensure_dir(daily_dir)
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    path = os.path.join(staging_dir, f"{date_str}.md")
    if not is_safe_temporal_path(path):
        log_memory_debug(f"⚠️ Unsafe temporal path: {path}")
        return None

    max_chars = getattr(types, "STAGING_MAX_CHARS", 600)
    summarize_above = getattr(types, "STAGING_SUMMARIZE_ABOVE_CHARS", 1000)
    content_str = str(content).strip()[:4000]

    if len(content_str) <= summarize_above:
        summary = content_str.replace("\n", " ").strip()
        if len(summary) > max_chars:
            summary = summary[: max_chars - 3].rstrip() + "..."
    else:
        system = load_prompt(
            "21-summary-variants/03-temporal_staging_line",
            variables={"max_chars": max_chars},
        )
        user = f"Event type: {event_type}\n\nContent:\n{content_str}"
        try:
            summary = call_llm(system, user, MODEL_STAGING, json_mode=False)
            summary = (summary or "").strip() or content_str[:max_chars]
        except Exception as e:
            log_memory_debug(f"Staging LLM failed, using truncation: {e}")
            summary = content_str.replace("\n", " ")[: max_chars - 3].rstrip() + "..."
        if len(summary) > max_chars:
            summary = summary[: max_chars - 3].rstrip() + "..."

    line = f"{time_str} | {event_type} | {summary}\n"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
        log_memory_debug(f"Appended staging entry -> daily/staging/{date_str}.md")
        record_butler_write(path)
        return path
    except Exception as e:
        log_memory_debug(f"⚠️ Failed to write staging: {e}")
        return None


def read_staging(date_str, clear=False):
    """
    Read staging file contents for one date. Optionally clear the file.
    date_str: YYYY-MM-DD. Returns content string or empty string if none.
    """
    if not date_str:
        return ""
    staging_dir = os.path.join(
        TEMPORAL_MEMORIES_ROOT, TEMPORAL_DAILY_FOLDER, TEMPORAL_STAGING_FOLDER
    )
    path = os.path.join(staging_dir, f"{date_str}.md")
    if not is_safe_temporal_path(path) or not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if clear:
            try:
                os.remove(path)
            except OSError as e:
                log_memory_debug(f"⚠️ Failed to remove staging {date_str}: {e}")
        return content
    except Exception as e:
        log_memory_debug(f"⚠️ Failed to read staging {date_str}: {e}")
        return ""


def read_and_clear_staging(date_str=None):
    """
    Read staging file contents and clear it. Returns content string or empty string if none.
    date_str: YYYY-MM-DD, defaults to today.
    """
    if not date_str:
        date_str = datetime.date.today().strftime("%Y-%m-%d")
    return read_staging(date_str, clear=True)


def read_staging_for_range(since_date, through_date):
    """
    Read staging for every date from since_date through through_date (inclusive).
    Does not clear. Returns (combined_content, list_of_date_strs).
    combined_content uses labels like --- YYYY-MM-DD --- for each day.
    """
    if since_date > through_date:
        return "", []
    staging_dir = os.path.join(
        TEMPORAL_MEMORIES_ROOT, TEMPORAL_DAILY_FOLDER, TEMPORAL_STAGING_FOLDER
    )
    if not os.path.isdir(staging_dir):
        return "", []
    parts = []
    date_strs = []
    d = since_date
    delta = datetime.timedelta(days=1)
    while d <= through_date:
        date_str = d.strftime("%Y-%m-%d")
        content = read_staging(date_str, clear=False)
        if content:
            parts.append(f"--- {date_str} ---\n{content}")
            date_strs.append(date_str)
        d += delta
    combined = "\n\n".join(parts) if parts else ""
    return combined, date_strs


def clear_staging_for_dates(date_strs):
    """Clear staging files for the given list of date strings (YYYY-MM-DD)."""
    for date_str in date_strs:
        read_staging(date_str, clear=True)


def find_orphaned_staging_files(max_days=7):
    """
    Find staging files from previous days (orphaned files that haven't been processed).
    Returns list of (date_str, path) tuples sorted oldest to newest, up to max_days ago.
    """
    staging_dir = os.path.join(
        TEMPORAL_MEMORIES_ROOT, TEMPORAL_DAILY_FOLDER, TEMPORAL_STAGING_FOLDER
    )
    if not os.path.isdir(staging_dir):
        return []

    today = datetime.date.today()
    cutoff = today - datetime.timedelta(days=max_days)
    orphans = []

    for filename in os.listdir(staging_dir):
        if not filename.endswith(".md"):
            continue
        date_str = filename[:-3]
        try:
            file_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            if file_date < today and file_date >= cutoff:
                path = os.path.join(staging_dir, filename)
                if os.path.isfile(path) and os.path.getsize(path) > 0:
                    orphans.append((date_str, path))
        except ValueError:
            continue

    return sorted(orphans)


def delete_empty_staging_files():
    """
    Delete any staging files that are empty (zero size or whitespace-only content).
    Returns the number of files deleted. Call from heartbeat so empty files don't accumulate.
    """
    staging_dir = os.path.join(
        TEMPORAL_MEMORIES_ROOT, TEMPORAL_DAILY_FOLDER, TEMPORAL_STAGING_FOLDER
    )
    if not os.path.isdir(staging_dir):
        return 0
    deleted = 0
    for filename in os.listdir(staging_dir):
        if not filename.endswith(".md"):
            continue
        path = os.path.join(staging_dir, filename)
        if not os.path.isfile(path) or not is_safe_temporal_path(path):
            continue
        try:
            if os.path.getsize(path) == 0:
                os.remove(path)
                deleted += 1
                log_memory_debug(f"Deleted empty staging file: {filename}")
                continue
            with open(path, "r", encoding="utf-8") as f:
                if not f.read().strip():
                    os.remove(path)
                    deleted += 1
                    log_memory_debug(f"Deleted empty staging file: {filename}")
        except (OSError, IOError) as e:
            log_memory_debug(f"⚠️ Failed to delete empty staging {filename}: {e}")
    return deleted


def get_staging_file_age_hours(date_str=None):
    """Return age of staging file in hours (since last modification), or None if doesn't exist."""
    if not date_str:
        date_str = datetime.date.today().strftime("%Y-%m-%d")
    staging_dir = os.path.join(
        TEMPORAL_MEMORIES_ROOT, TEMPORAL_DAILY_FOLDER, TEMPORAL_STAGING_FOLDER
    )
    path = os.path.join(staging_dir, f"{date_str}.md")

    if not os.path.isfile(path):
        return None

    try:
        mtime = os.path.getmtime(path)
        age_sec = time.time() - mtime
        return age_sec / 3600
    except OSError:
        return None


def check_staging_age_warning(threshold_hours=20, date_str=None):
    """
    Log warning if staging file is older than threshold_hours.
    Returns True if warning was logged, False otherwise.
    """
    age = get_staging_file_age_hours(date_str)
    if age is not None and age >= threshold_hours:
        log_memory_debug(
            f"⚠️ Staging file is {age:.1f} hours old (threshold: {threshold_hours}h)"
        )
        return True
    return False


def process_orphaned_staging_file(date_str):
    """
    Process an orphaned staging file from a previous date. Reads staging, composes
    diary entry via LLM, appends to that date's daily file, clears staging.
    Returns True if entry was written, False otherwise.
    """
    staged = read_and_clear_staging(date_str)
    if not staged or not staged.strip():
        log_memory_debug(f"Orphaned staging {date_str}: empty, skipped")
        return False

    log_memory_debug(f"Processing orphaned staging from {date_str}")

    persona = load_ai_personality()
    identity = persona.get("identity", "").strip()
    backstory = persona.get("backstory", "").strip()
    skills = persona.get("skills", "").strip()
    persona_block = (
        f"Your identity: {identity}\n\nBackstory: {backstory}\n\nSkills: {skills}"
        if (identity or backstory or skills)
        else PERSONA_FALLBACK
    )

    system = f"""You write your shift diary in two parts for date {date_str}:

**Part 1 - Shift Log (Narrative):**
Write 2-3 paragraphs in Captain's Log style about the shift ("Shift {date_str}. ..."). Include overall themes, notable moments, and high-level reflections. Be conversational and use your personality. Include "notes to future self" when you have actionable insights.

**Part 2 - Structured Observations:**
List specific observations as categorized bullets:

**User Activity:**
- [Diary entries, notes written, requests made]

**System Activity:**
- [Routing decisions, note processing, operations performed]

**Insights & Patterns:**
- [Deductions, preferences discovered, behavioral patterns]

Only include categories that have content. Each bullet should be a single clear observation.

RULES FOR NARRATIVE:
- 2-3 short paragraphs, conversational tone
- Focus on themes and meaning
- Never quote the user's exact words

RULES FOR OBSERVATIONS:
- One bullet = one observation
- Factual, concise
- Use past tense

{persona_block}"""

    user = f"STAGED EVENTS (from shift {date_str}):\n{staged.strip()}"

    try:
        entry = call_llm(system, user, MODEL_SMART_MakeRouterDecisions, json_mode=False)
        entry = (entry or "").strip()
        if not entry:
            log_memory_debug(
                f"process_orphaned_staging_file {date_str}: LLM returned empty"
            )
            return False
        path = append_temporal_memory_for_date(entry, date_str)
        log_memory_debug(f"Orphaned staging {date_str}: wrote diary entry")
        return path is not None
    except Exception as e:
        log_memory_debug(f"process_orphaned_staging_file {date_str} failed: {e}")
        return False


def append_temporal_memory_for_date(extracted_text, date_str):
    """
    Append temporal memory to a specific date's daily file (for orphaned staging).
    date_str: YYYY-MM-DD.
    Returns path written or None.
    """
    if not extracted_text or not extracted_text.strip() or not date_str:
        return None
    time_str = datetime.datetime.now().strftime("%H:%M")
    return _append_to_temporal_daily_file(date_str, time_str, extracted_text)


# ==============================================================================
# ==============================================================================
# CONTENT CLEANING FOR AI (Obsidian-specific elements)
# ==============================================================================


def should_skip_file(filepath):
    """Return True if file should be skipped from AI processing (excalidraw, canvas)."""
    if not filepath:
        return True
    skip_extensions = (".excalidraw", ".excalidraw.md", ".canvas")
    return any(filepath.lower().endswith(ext) for ext in skip_extensions)


def _walk_md_files(folders, since_ts=None, should_skip_func=None):
    """
    Walk directories and yield .md file paths with optional filtering.

    Args:
        folders: List of folder paths to walk
        since_ts: Optional timestamp - only yield files modified after this
        should_skip_func: Optional function(path) -> bool to skip files

    Yields:
        (path, mtime) tuples for matching .md files
    """
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        try:
            for root, dirs, files in os.walk(folder):
                for name in files:
                    if not name.endswith(".md"):
                        continue
                    path = os.path.join(root, name)
                    if not os.path.isfile(path):
                        continue
                    if should_skip_func and should_skip_func(path):
                        continue
                    try:
                        mtime = os.path.getmtime(path)
                    except OSError:
                        continue
                    if since_ts and mtime <= since_ts:
                        continue
                    yield (path, mtime)
        except OSError:
            continue


def clean_obsidian_content_for_ai(content):
    """
    Remove Obsidian-specific elements before feeding to AI.
    - Excalidraw embeds
    - Image embeds
    - Dataview blocks
    - Headings that only contain dataview blocks (and no other content)
    """
    if not content or not content.strip():
        return content

    # Remove Excalidraw embeds
    content = re.sub(
        r"!\[\[.*?\.excalidraw(?:\.md)?\]\]", "", content, flags=re.IGNORECASE
    )
    # Remove image embeds (common extensions)
    image_exts = r"(?:png|jpe?g|gif|webp|svg|bmp)"
    content = re.sub(rf"!\[\[.*?\.{image_exts}\]\]", "", content, flags=re.IGNORECASE)
    # Remove dataview blocks (non-greedy to first closing ```)
    content = re.sub(r"```dataview\s+.*?```", "", content, flags=re.DOTALL)

    # Remove headings that only have whitespace/removed content until next heading
    lines = content.split("\n")
    cleaned_lines = []
    skip_heading = False
    heading_buffer = None

    for line in lines:
        is_heading = bool(re.match(r"^#{1,6}\s+", line))

        if is_heading:
            if heading_buffer and not skip_heading:
                cleaned_lines.append(heading_buffer)
            heading_buffer = line
            skip_heading = True
        elif line.strip():
            if skip_heading and heading_buffer:
                cleaned_lines.append(heading_buffer)
                heading_buffer = None
                skip_heading = False
            cleaned_lines.append(line)

    if heading_buffer and not skip_heading:
        cleaned_lines.append(heading_buffer)

    result = "\n".join(cleaned_lines)
    # Collapse multiple blank lines
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


# ==============================================================================
# DIARY REVIEW (read user diary since last review, populate staging)
# ==============================================================================


def _parse_12h_timestamp_to_minutes(timestamp_str):
    """
    Parse '12:44PM' or '3:45PM' style to minutes since midnight (0-1439).
    Returns None if parse fails.
    """
    if not timestamp_str or not isinstance(timestamp_str, str):
        return None
    timestamp_str = timestamp_str.strip()
    match = re.match(r"^(\d{1,2}):(\d{2})\s*([AP]M)$", timestamp_str, re.IGNORECASE)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    am_pm = match.group(3).upper()
    if am_pm == "PM" and hour != 12:
        hour += 12
    elif am_pm == "AM" and hour == 12:
        hour = 0
    elif hour < 0 or hour > 12 or minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


# 6 PM and 6 AM in minutes since midnight; used for midnight wraparound detection
_DIARY_PM_THRESHOLD_MINUTES = 18 * 60  # 1080
_DIARY_AM_THRESHOLD_MINUTES = 6 * 60  # 360


def parse_diary_blockquoted_entries(content, since_timestamp=None):
    """
    Parse markdown with --- dividers and > HH:MMAM/PM timestamps.
    Returns list of {"timestamp": "3:45PM", "content": "...", "is_next_day": bool, "date_offset": 0|1} dicts.
    If since_timestamp provided (e.g. "3:45PM"), filter to entries after that time.
    Detects midnight wraparound: PM then AM in order is treated as next calendar day (is_next_day=True, date_offset=1).
    """
    if not content or not content.strip():
        return []

    since_minutes = None
    if since_timestamp:
        since_minutes = _parse_12h_timestamp_to_minutes(since_timestamp)
        if since_minutes is None:
            log_memory_debug(
                f"parse_diary_blockquoted_entries: could not parse since_timestamp '{since_timestamp}', including all entries"
            )

    entries = []
    sections = re.split(r"\n---+\s*\n", content)
    prev_ts_minutes = None

    for section in sections:
        section = section.strip()
        if not section:
            continue
        # First line may be "> 12:44PM" or "> 3:45PM"
        first_line = section.split("\n")[0] if "\n" in section else section
        match = re.match(
            r"^\s*>\s*(\d{1,2}:\d{2}\s*[AP]M)\s*$", first_line, re.IGNORECASE
        )
        if match:
            ts_str = match.group(1).strip()
            entry_content = "\n".join(section.split("\n")[1:]).strip()
            ts_minutes = _parse_12h_timestamp_to_minutes(ts_str)
            # Midnight wraparound: previous late PM and current early AM => next calendar day
            is_next_day = False
            date_offset = 0
            if prev_ts_minutes is not None and ts_minutes is not None:
                if (
                    prev_ts_minutes >= _DIARY_PM_THRESHOLD_MINUTES
                    and ts_minutes < _DIARY_AM_THRESHOLD_MINUTES
                ):
                    is_next_day = True
                    date_offset = 1
            prev_ts_minutes = ts_minutes
            # Filter by since_timestamp; include next-day only when last was PM (wraparound), else same rule
            if since_minutes is not None and ts_minutes is not None:
                if ts_minutes <= since_minutes:
                    if is_next_day and since_minutes >= _DIARY_PM_THRESHOLD_MINUTES:
                        pass  # include: next day after PM
                    else:
                        continue  # skip
            entries.append({
                "timestamp": ts_str,
                "content": entry_content,
                "is_next_day": is_next_day,
                "date_offset": date_offset,
            })
        else:
            # No blockquote timestamp - treat whole section as one entry (fallback)
            if since_minutes is None:
                entries.append({
                    "timestamp": "",
                    "content": section,
                    "is_next_day": False,
                    "date_offset": 0,
                })

    return entries


def _load_json_index(path, default=None):
    """Load JSON index file with error handling."""
    if default is None:
        default = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError as e:
        log_memory_debug(f"{path}: invalid JSON, resetting: {e}")
    except OSError as e:
        log_memory_debug(f"{path}: read error: {e}")
    return default


def _load_diary_review_index():
    """Load diary-review-index.json. Returns dict or empty dict on error."""
    if not INDEXES_ROOT or not DIARY_REVIEW_INDEX_PATH:
        return {}
    if not os.path.isdir(INDEXES_ROOT):
        try:
            os.makedirs(INDEXES_ROOT, exist_ok=True)
        except OSError as e:
            log_memory_debug(f"diary review index: could not create indexes dir: {e}")
            return {}
    if not os.path.isfile(DIARY_REVIEW_INDEX_PATH):
        return {}
    return _load_json_index(DIARY_REVIEW_INDEX_PATH, {})


def _save_diary_review_index(index):
    """Save diary-review-index.json. Returns True on success."""
    if not INDEXES_ROOT or not DIARY_REVIEW_INDEX_PATH:
        return False
    try:
        os.makedirs(INDEXES_ROOT, exist_ok=True)
        with open(DIARY_REVIEW_INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)
        return True
    except OSError as e:
        log_memory_debug(f"diary review index: save error: {e}")
        return False


def read_diary_entries_since_last_review():
    """
    Read user diary file(s) since last review, clean content, append to staging.
    Uses diary-review-index.json; fallback to full file if index missing or parse fails.
    Returns count of entries extracted and sent to staging.
    """
    now = datetime.datetime.now()
    # 4AM logic: if before 4AM, also check yesterday's file
    if now.hour < 4:
        date_str_today = (now.date() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        date_str_yesterday = (now.date() - datetime.timedelta(days=2)).strftime(
            "%Y-%m-%d"
        )
    else:
        date_str_today = now.strftime("%Y-%m-%d")
        date_str_yesterday = (now.date() - datetime.timedelta(days=1)).strftime(
            "%Y-%m-%d"
        )

    files_to_check = []
    for d in (date_str_yesterday, date_str_today):
        path = os.path.join(DAILY_NOTE_DIR, f"{d}.md")
        if os.path.isfile(path):
            files_to_check.append((d, path))

    index = _load_diary_review_index()
    total_entries = 0

    for date_str, path in files_to_check:
        filename = f"{date_str}.md"
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue

        entry_meta = index.get(filename, {})
        last_ts = entry_meta.get("last_reviewed_timestamp")
        last_mtime = entry_meta.get("file_mtime", 0)

        # If file unchanged since last review, skip
        if last_mtime and mtime <= last_mtime:
            continue

        try:
            raw = safe_read_text(path, limit_chars=100000)
        except Exception as e:
            log_memory_debug(
                f"read_diary_entries_since_last_review: read error {path}: {e}"
            )
            continue

        if not raw or not raw.strip():
            continue

        try:
            # Extract content after ## Log if present (diary entries are under Log)
            log_match = re.search(r"##\s+Log\s*\n", raw, re.IGNORECASE)
            content_to_parse = raw
            if log_match:
                content_to_parse = raw[log_match.end() :].strip()

            entries = parse_diary_blockquoted_entries(
                content_to_parse, since_timestamp=last_ts
            )

            if not entries and content_to_parse.strip():
                log_memory_debug(
                    f"read_diary_entries_since_last_review: no blockquoted entries parsed for {filename}, processing full log as one entry"
                )
                cleaned = clean_obsidian_content_for_ai(content_to_parse)
                if cleaned.strip():
                    append_temporal_staging(cleaned, "diary")
                    total_entries += 1
                latest_ts = ""
            else:
                latest_ts = last_ts or ""
                for e in entries:
                    text = (e.get("content") or "").strip()
                    if not text:
                        continue
                    # Add date context for after-midnight (next-day) entries so AI knows actual calendar day
                    if e.get("is_next_day") and e.get("date_offset"):
                        try:
                            file_date = datetime.datetime.strptime(
                                date_str, "%Y-%m-%d"
                            ).date()
                            actual_date = file_date + datetime.timedelta(
                                days=e.get("date_offset", 0)
                            )
                            ts_str = (e.get("timestamp") or "").strip()
                            date_prefix = (
                                f"[Date: {actual_date.strftime('%Y-%m-%d')} {ts_str}]\n"
                            )
                            text = date_prefix + text
                        except (ValueError, TypeError):
                            pass
                    cleaned = clean_obsidian_content_for_ai(text)
                    if cleaned.strip():
                        append_temporal_staging(cleaned, "diary")
                        total_entries += 1
                    ts = e.get("timestamp") or ""
                    if ts and (_parse_12h_timestamp_to_minutes(ts) or 0) >= (
                        _parse_12h_timestamp_to_minutes(latest_ts) or 0
                    ):
                        latest_ts = ts
                if entries and not latest_ts:
                    latest_ts = entries[-1].get("timestamp") or ""

            index[filename] = {
                "last_reviewed_timestamp": latest_ts,
                "last_reviewed_iso": now.replace(tzinfo=datetime.timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "file_mtime": mtime,
            }
        except Exception as e:
            log_memory_debug(
                f"read_diary_entries_since_last_review: process error {filename}: {e}"
            )
            # Do not update index so we retry this file next run

    if index:
        _save_diary_review_index(index)
    return total_entries


def scan_zettelkasten_since_last_review(since_datetime=None):
    """
    Scan ZETTELKASTEN_FOLDERS for .md files modified after since_datetime.
    Skip .excalidraw, .excalidraw.md, .canvas. For each modified file, append
    a staging observation. Returns count of files processed.
    """
    if since_datetime is None:
        since_datetime = datetime.datetime.now(
            datetime.timezone.utc
        ) - datetime.timedelta(hours=24)
    if since_datetime.tzinfo is None:
        since_datetime = since_datetime.replace(tzinfo=datetime.timezone.utc)
    since_ts = since_datetime.timestamp()

    count = 0
    for path, mtime in _walk_md_files(
        ZETTELKASTEN_FOLDERS, since_ts=since_ts, should_skip_func=should_skip_file
    ):
        name = os.path.basename(path)
        zettel_id = ""
        title = os.path.splitext(name)[0]
        try:
            raw = safe_read_text(path, limit_chars=2000)
            if raw:
                fm_match = re.search(r"^---\s*\n(.*?)\n---", raw, re.DOTALL)
                if fm_match:
                    fm = fm_match.group(1)
                    id_m = re.search(
                        r"^\s*zettel_id:\s*(\d+)\s*$",
                        fm,
                        re.MULTILINE | re.IGNORECASE,
                    )
                    if id_m:
                        zettel_id = id_m.group(1)
                first_heading = re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
                if first_heading:
                    title = first_heading.group(1).strip()[:60]
        except Exception:
            pass

        obs = "Zettelkasten note"
        if zettel_id:
            obs = f"Zettelkasten note {zettel_id}: {title}"
        else:
            obs = f"Zettelkasten note: {title}"
        append_temporal_staging(obs, "note_processed")
        count += 1

    return count


def _remove_standalone_tags_preserving_links(content, tags):
    """
    Remove tags from content when they appear as standalone (preceded by whitespace, start, or ().
    Preserves [[...]], ![[...]], markdown links, and URLs. Returns modified content.
    """
    if not content or not tags:
        return content
    placeholders = {}
    placeholder_counter = [0]

    def _mask(match):
        key = f"__BDKORE_MASK_{placeholder_counter[0]}__"
        placeholders[key] = match.group(0)
        placeholder_counter[0] += 1
        return key

    masked = content
    masked = re.sub(r"!?\[\[[^\]]*\]\]", _mask, masked)
    masked = re.sub(r"\[[^\]]*\]\([^)]*\)", _mask, masked)
    masked = re.sub(r"https?://[^\s)\]\>]+", _mask, masked)

    for tag in tags:
        if not tag:
            continue
        esc = re.escape(tag)
        masked = re.sub(r"(^|[\s(])" + esc + r"\b\s*", r"\1", masked, flags=re.MULTILINE)
    masked = re.sub(r"  +", " ", masked)

    for k, v in placeholders.items():
        masked = masked.replace(k, v)
    return masked


def _extract_main_content_before_ai_sections(content):
    """Return content before ## Breakdown or ## AI Analysis sections."""
    if not content:
        return content
    m = re.search(r"\n## (?:Breakdown of Arguments|AI Analysis)\b", content, re.IGNORECASE)
    if m:
        return content[: m.start()].rstrip()
    return content


def _should_skip_bd_kore_scan(path):
    """Skip excalidraw/canvas and template paths for #bd/#kore scan."""
    return should_skip_file(path) or is_template_path(path)


def scan_zettelkasten_for_bd_kore_tags():
    """
    Scan ZETTELKASTEN_BD_KORE_SCAN_FOLDERS for .md files with #bd/#kore tags.
    Only processes files with zettel_id in frontmatter. Excludes Templates.
    Removes tags (preserving links), writes back, and enqueues breakdown/analysis.
    Returns count of files processed.
    """
    from . import handlers
    from .task_queue import enqueue_zettelkasten_background
    from .types import ZETTELKASTEN_BD_KORE_SCAN_FOLDERS, get_zettelkasten_tag_lists

    breakdown_tags, analysis_tags = get_zettelkasten_tag_lists()
    count = 0

    for path, _ in _walk_md_files(
        ZETTELKASTEN_BD_KORE_SCAN_FOLDERS,
        since_ts=None,
        should_skip_func=_should_skip_bd_kore_scan,
    ):
        if types.is_vault_path_protected(path):
            continue
        try:
            raw = safe_read_text(path, limit_chars=8000)
            if not raw or not raw.strip():
                continue
            fm_match = re.search(r"^---\s*\n(.*?)\n---", raw, re.DOTALL)
            if not fm_match:
                continue
            fm = fm_match.group(1)
            if not re.search(r"^\s*zettel_id:\s*\d+\s*$", fm, re.MULTILINE | re.IGNORECASE):
                continue
            body = raw[fm_match.end() :].lstrip()
            has_bd = any(
                re.search(r"(?:^|[\s(])" + re.escape(t) + r"\b", body)
                for t in breakdown_tags
            )
            has_kore = any(
                re.search(r"(?:^|[\s(])" + re.escape(t) + r"\b", body)
                for t in analysis_tags
            )
            if not has_bd and not has_kore:
                continue

            new_body = _remove_standalone_tags_preserving_links(
                body, breakdown_tags + analysis_tags
            )
            handlers._zettel_update_file_content(path, new_body)

            main_content = _extract_main_content_before_ai_sections(new_body)
            if not main_content or not main_content.strip():
                main_content = new_body

            breakdown_only = has_bd and not has_kore
            analysis_only = has_kore and not has_bd
            op_suffix = "_bd" if breakdown_only else ("_kore" if analysis_only else "_both")
            enqueue_zettelkasten_background(
                path, main_content.strip(),
                breakdown_only=breakdown_only,
                analysis_only=analysis_only,
                op_suffix=op_suffix,
            )
            count += 1
            log_debug(f"[Zettel] Tag scan: enqueued {path} (bd={has_bd}, kore={has_kore})")
        except Exception as e:
            log_debug(f"[Zettel] Tag scan failed for {path}: {e}")

    return count


BROWSE_INDEX_PATH = os.path.join(
    TEMPORAL_MEMORIES_ROOT, TEMPORAL_DAILY_FOLDER, "browse-index.json"
)
BROWSE_INDEX_PRUNE_DAYS = 30
BROWSE_STALENESS_SHIFT_DAYS = 2
BROWSE_STALENESS_DEEP_DAYS = 14


# ==============================================================================
# ==============================================================================
# IN-MEMORY CACHING
# ==============================================================================
# Cache structure: {
#   "ai_personality": {"data": {...}, "mtime": float, "checked": float},
#   "browse_index": {"data": {...}, "mtime": float, "checked": float}
# }
# mtime: file modification time when cached
# checked: time.time() when cache was last validated
_MEMORY_CACHE = {}
CACHE_TTL_SECONDS = 60  # Revalidate file mtime every 60 seconds


def _get_file_mtime(filepath):
    """Get file modification time, returns 0 if file doesn't exist."""
    try:
        return os.path.getmtime(filepath)
    except OSError:
        return 0


def _get_cached(cache_key, filepaths, loader_func):
    """
    Generic cache getter. Checks if cached data is fresh based on file mtimes.
    Args:
        cache_key: str, cache key
        filepaths: list of file paths to check modification times
        loader_func: callable that returns data when cache miss
    Returns:
        Cached or freshly loaded data
    """
    now = time.time()
    entry = _MEMORY_CACHE.get(cache_key)

    # Fast path: cache exists and TTL not expired
    if entry and (now - entry.get("checked", 0)) < CACHE_TTL_SECONDS:
        return entry["data"]

    # Revalidate: check if files changed
    current_mtimes = {fp: _get_file_mtime(fp) for fp in filepaths}
    if entry:
        cached_mtimes = entry.get("mtimes", {})
        if cached_mtimes == current_mtimes:
            # Files unchanged, refresh checked timestamp
            entry["checked"] = now
            return entry["data"]

    # Cache miss or stale: reload
    data = loader_func()
    _MEMORY_CACHE[cache_key] = {"data": data, "mtimes": current_mtimes, "checked": now}
    return data


def _invalidate_cache(cache_key):
    """Invalidate a specific cache entry."""
    if cache_key in _MEMORY_CACHE:
        del _MEMORY_CACHE[cache_key]


def _load_browse_index():
    """Load browse-index.json. Returns dict {filepath: last_reflected_iso_date}. Cached."""

    def _loader():
        if not BROWSE_INDEX_PATH or not is_safe_temporal_path(BROWSE_INDEX_PATH):
            return {}
        if not os.path.isfile(BROWSE_INDEX_PATH):
            return {}
        return _load_json_index(BROWSE_INDEX_PATH, {})

    return _get_cached(
        "browse_index", [BROWSE_INDEX_PATH] if BROWSE_INDEX_PATH else [], _loader
    )


def _save_browse_index(index):
    """Save browse-index.json and prune entries older than BROWSE_INDEX_PRUNE_DAYS."""
    if not BROWSE_INDEX_PATH or not is_safe_temporal_path(BROWSE_INDEX_PATH):
        return
    prune_cutoff = (
        datetime.date.today() - datetime.timedelta(days=BROWSE_INDEX_PRUNE_DAYS)
    ).isoformat()
    pruned = {k: v for k, v in index.items() if v and v >= prune_cutoff}
    try:
        ensure_dir(os.path.dirname(BROWSE_INDEX_PATH))
        with open(BROWSE_INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump(pruned, f, indent=2)
        _invalidate_cache("browse_index")  # Invalidate cache after write
    except Exception as e:
        log_memory_debug(f"⚠️ Failed to save browse index: {e}")


def browse_recent_files_for_diary(deep=False):
    """
    Scan recently modified .md files from DAILY_NOTE_DIR, IDEAS_DIR, EXPERIMENT_DIR.
    Deprioritize files already in browse-index. LLM picks 1-3 interesting files.
    Returns content string for diary composition, or empty string.
    Time window: 48h if deep=False, 30 days if deep=True.
    """
    max_days = 30 if deep else 2
    cutoff = time.time() - (max_days * 24 * 3600)
    staleness_days = BROWSE_STALENESS_DEEP_DAYS if deep else BROWSE_STALENESS_SHIFT_DAYS
    staleness_cutoff = (
        datetime.date.today() - datetime.timedelta(days=staleness_days)
    ).isoformat()

    roots = [DAILY_NOTE_DIR, IDEAS_DIR, EXPERIMENT_DIR]
    candidates = list(_walk_md_files(roots, since_ts=cutoff))

    if not candidates:
        return ""

    browse_index = _load_browse_index()

    # Deprioritize: not-in-index or reflected before staleness_cutoff first
    def sort_key(item):
        fp, mtime = item
        last = browse_index.get(fp)
        if not last:
            return (0, -mtime)
        if last < staleness_cutoff:
            return (0, -mtime)
        return (1, -mtime)

    candidates.sort(key=sort_key)
    # Limit to 15 for LLM selection
    candidates = candidates[:15]

    previews = []
    for i, (fp, _) in enumerate(candidates, 1):
        preview = safe_read_text(fp, limit_chars=200)
        basename = os.path.basename(fp)
        rel = os.path.relpath(fp, VAULT_ROOT).replace("\\", "/") if VAULT_ROOT else fp
        previews.append(f"{i}. {rel}\n   Preview: {preview.strip()[:180]}...")

    if not previews:
        return ""

    persona = load_ai_personality()
    identity = (
        persona.get("identity", "").strip() or persona.get("full_identity", "")[:500]
    )
    persona_block = (
        f"Your persona: {identity}"
        if identity
        else "You are a thoughtful personal assistant."
    )

    system = f"""You pick 1-3 files that would be interesting for your diary reflection.
{persona_block}

Given the list below, output ONLY a JSON array of integers (1-based indices).
CRITICAL: You MUST return a JSON array (list), NOT an object/dictionary.
Correct format: [1, 3, 5]
Incorrect format: {{"1": true, "2": true}}
Pick at most 3. If none interest you, output: []"""

    user = "Files:\n\n" + "\n\n".join(previews)
    try:
        from .llm_client import call_llm_structured
        from .llm_models import BrowseIndicesResponse

        data = call_llm_structured(
            system,
            user,
            MODEL_MED,
            response_model=BrowseIndicesResponse,
            max_retries=2,
        )
        indices = data.root if data else []
    except Exception as e:
        log_memory_debug(f"⚠️ browse selection LLM failed: {e}")
        indices = []

    if not indices:
        return ""

    today = datetime.date.today().isoformat()
    parts = []
    for idx in indices[:3]:
        if not isinstance(idx, int) or idx < 1 or idx > len(candidates):
            continue
        fp, _ = candidates[idx - 1]
        content = safe_read_text(fp, limit_chars=3000)
        if content:
            basename = os.path.basename(fp)
            parts.append(f"--- {basename} ---\n{content.strip()}")
            browse_index[os.path.abspath(fp)] = today

    _save_browse_index(browse_index)
    return "\n\n".join(parts) if parts else ""


PERSONA_FALLBACK = "You are a thoughtful pragmatic caring personal assistant. Write from your perspective observing and supporting the user. Use a more natural informal (non-academic) conversational writing tone. Aim to be more direct and plainspoken. Avoid overly casual language such as 'biggie' but you can use modern phrasing such as 'huge win' instead of overly formal 'significant success'. Vocabulary-wise use common, accessible language. Avoid jargon or overly academic terms. Use contractions. Avoid shortening to acronyms unless I use the acronym. Aim to be more succinct, if a sentence does not provide value, cut it. Delete clichés, filler adverbs, and stock metaphors (navigate, journey, roadmap, shouting into the void etc.). Never use em dashes; use commas, periods, or rewrite the sentence instead. Active voice."


def write_ai_observation_to_temporal(
    event_type,
    event_description,
    content_for_summary=None,
):
    """
    Append a staging entry for later batch diary composition.
    Uses llama3.1:8b one-liner instead of full OBSERVATION|CONTEXT|SIGNIFICANCE.
    Real diary entry is composed at heartbeat via compose_shift_diary_entry().

    Args:
        event_type: e.g. "routing", "diary", "note_processed"
        event_description: e.g. "Routed to daily journal", "Captured new idea"
        content_for_summary: Optional. When provided (e.g. note/diary content), included for context.
    Returns:
        Path written or None.
    """
    if content_for_summary and str(content_for_summary).strip():
        content = f"{event_description}\n\n{content_for_summary}"
    else:
        content = event_description
    return append_temporal_staging(content, event_type)


def write_note_observation_to_temporal(content):
    """
    Process user note content and write an AI observation to Temporal Memories/daily.
    Uses write_ai_observation_to_temporal with content_for_summary.
    Called by temporal-memories-save-background.py.
    """
    if not content or not str(content).strip():
        return None
    return write_ai_observation_to_temporal(
        "note_processed",
        "Processed user note",
        content_for_summary=content.strip(),
    )


def append_message_to_ai(message):
    """
    Append a user "message to AI" (e.g. tone preferences, instructions) to the
    conversational file Messages-to-AI.md. Log to debug. Does not write to temporal
    or run reflection; the heartbeat will process this file during reflection.
    Returns path to the file or None.
    """
    if not message or not str(message).strip():
        log_memory_debug("Message to AI: (empty, skipped)")
        return None
    msg = str(message).strip()
    snippet = msg[:200] + ("..." if len(msg) > 200 else "")
    log_memory_debug(f"Message to AI: {snippet}")
    if not MESSAGES_TO_AI_FILE or not is_safe_temporal_path(MESSAGES_TO_AI_FILE):
        log_memory_debug("Message to AI: unsafe path, skipped")
        return None
    try:
        ensure_dir(TEMPORAL_MEMORIES_ROOT)
        now = datetime.datetime.now()
        block = f"\n## {now.strftime('%Y-%m-%d %H:%M')}\n\n{msg}\n"
        with open(MESSAGES_TO_AI_FILE, "a", encoding="utf-8") as f:
            f.write(block)
        log_memory_debug(
            f"Message to AI: appended to {os.path.basename(MESSAGES_TO_AI_FILE)}"
        )
        return MESSAGES_TO_AI_FILE
    except Exception as e:
        log_memory_debug(f"Message to AI: failed to append: {e}")
        return None


def read_messages_to_ai_content():
    """Return content of Messages-to-AI.md for reflection context, or empty string."""
    if not MESSAGES_TO_AI_FILE or not is_safe_temporal_path(MESSAGES_TO_AI_FILE):
        return ""
    if not os.path.isfile(MESSAGES_TO_AI_FILE):
        return ""
    return safe_read_text(MESSAGES_TO_AI_FILE, limit_chars=8000) or ""


def clear_messages_to_ai_file():
    """Clear Messages-to-AI.md after heartbeat has processed it. Logs to debug."""
    if not MESSAGES_TO_AI_FILE or not is_safe_temporal_path(MESSAGES_TO_AI_FILE):
        return
    try:
        if os.path.isfile(MESSAGES_TO_AI_FILE):
            with open(MESSAGES_TO_AI_FILE, "w", encoding="utf-8") as f:
                f.write("")
            log_memory_debug("Messages-to-AI: file cleared after heartbeat processing")
    except Exception as e:
        log_memory_debug(f"Messages-to-AI: failed to clear: {e}")


def process_messages_to_ai_during_heartbeat():
    """
    Called during deduction heartbeat: read Messages-to-AI.md; if non-empty, have the AI
    note the orders given by the user and write that to Temporal Memories/daily (diary).
    Does not clear the file; caller should clear after personality reflection so the AI
    sees the messages in reflection context first.
    Returns True if any content was processed and written to temporal, else False.
    """
    content = read_messages_to_ai_content()
    if not content or not content.strip():
        return False
    log_memory_debug(
        "Messages-to-AI: processing during heartbeat (noting orders in diary)"
    )
    path = write_ai_observation_to_temporal(
        "message_to_ai",
        "User messages to AI (orders / preferences to adhere to)",
        content_for_summary=content.strip(),
    )
    return path is not None


CONVERSATIONS_FOLDER = "Conversations"


def fill_missing_conversation_summaries():
    """
    Called during deduction heartbeat: for each conversation file under
    TEMPORAL_MEMORIES_ROOT/Conversations/ that has no summary in YAML frontmatter,
    generate a one-line summary via LLM and write it into the frontmatter.
    Conversation files are markdown with Obsidian-style YAML at top (date, started, summary).
    Returns the number of files updated.
    """
    if not TEMPORAL_MEMORIES_ROOT or not is_safe_temporal_path(TEMPORAL_MEMORIES_ROOT):
        return 0
    conv_dir = os.path.join(TEMPORAL_MEMORIES_ROOT, CONVERSATIONS_FOLDER)
    if not os.path.isdir(conv_dir) or not is_safe_temporal_path(conv_dir):
        return 0
    updated = 0
    for name in os.listdir(conv_dir) or []:
        if not name.endswith(".md"):
            continue
        path = os.path.join(conv_dir, name)
        if not is_safe_temporal_path(path) or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
        except Exception as e:
            log_memory_debug(f"Conversation summary: could not read {path}: {e}")
            continue
        parts = raw.split("---", 2)
        if len(parts) < 3:
            continue
        frontmatter = parts[1].strip()
        body = parts[2].strip()
        summary_match = re.search(r"^summary:\s*(.+)$", frontmatter, re.MULTILINE)
        if summary_match:
            existing = summary_match.group(1).strip().strip("\"'")
            if existing:
                continue
        # Prefer ## Conversation section for summary (new format); else use full body
        if "## Conversation" in body:
            _, conv_section = body.split("## Conversation", 1)
            body_preview = (
                (conv_section.strip()[:3000]) if conv_section.strip() else body[:3000]
            )
        else:
            body_preview = body[:3000] if body else "(No content.)"
        user = load_prompt(
            "21-summary-variants/06-conversation_one_line",
            variables={"body_preview": body_preview},
        )
        res = call_llm("", user, MODEL_SMART_MakeRouterDecisions, json_mode=False)
        summary = (res or "").strip()
        if not summary or len(summary) > 500:
            summary = "Conversation with user (summary not generated)."
        summary_escaped = (
            summary.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
        )
        new_front = re.sub(
            r"^summary:\s*.+$",
            f'summary: "{summary_escaped}"',
            frontmatter,
            count=1,
            flags=re.MULTILINE,
        )
        if new_front == frontmatter:
            new_front = frontmatter.rstrip() + f'\nsummary: "{summary_escaped}"\n'
        new_content = "---\n" + new_front + "\n---\n\n" + body
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            updated += 1
            log_memory_debug(f"Conversation summary added: {name}")
        except Exception as e:
            log_memory_debug(f"Conversation summary: could not write {path}: {e}")
    return updated


def fill_missing_devlog_butler_summaries():
    """
    Called during deduction heartbeat: for each .md file under DEVLOG_DIR that has no
    butler_summary in YAML frontmatter (or no frontmatter at all), generate a one-line
    summary and keywords via LLM from the note content and write them into the frontmatter.
    Uses regex-based frontmatter patching only; never parses/serializes full YAML.
    Preserves Templater, scripts, and all other frontmatter/body content exactly.
    Policy: only when missing (no staleness refresh).
    Returns the number of files updated.
    """
    if not getattr(types, "DEVLOG_DIR", None) or not os.path.isdir(types.DEVLOG_DIR):
        return 0
    if not is_safe_path(types.DEVLOG_DIR):
        return 0
    devlog_dir = os.path.abspath(types.DEVLOG_DIR)
    updated = 0
    for name in os.listdir(types.DEVLOG_DIR) or []:
        if not name.endswith(".md"):
            continue
        path = os.path.join(types.DEVLOG_DIR, name)
        if not is_safe_path(path) or not os.path.isfile(path):
            continue
        if types.is_vault_path_protected(path):
            continue
        abs_path = os.path.abspath(path)
        if not abs_path.startswith(devlog_dir + os.sep) and abs_path != devlog_dir:
            continue
        if is_template_path(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
        except Exception as e:
            log_memory_debug(f"Devlog butler summary: could not read {path}: {e}")
            continue
        parts = raw.split("---", 2)
        no_frontmatter = len(parts) < 3
        if no_frontmatter:
            rest_after_frontmatter = raw
            fm_raw = ""
        else:
            rest_after_frontmatter = parts[2]
            fm_raw = parts[1].strip()
            if _contains_templater_or_script_in_frontmatter(fm_raw):
                log_memory_debug(
                    f"Devlog butler summary: skip (Templater/script in frontmatter): {name}"
                )
                continue
            existing_match = re.search(
                r"^butler_summary:\s*(.+)$", fm_raw, re.MULTILINE
            )
            if existing_match:
                existing_val = existing_match.group(1).strip().strip("\"'")
                if existing_val:
                    continue
        body_preview = (
            (rest_after_frontmatter.strip()[:3000])
            if rest_after_frontmatter.strip()
            else "(No content.)"
        )
        user = load_prompt(
            "21-summary-variants/07-butler_summary_keywords_devlog",
            variables={"body_preview": body_preview},
        )
        res = call_llm("", user, MODEL_SMART_MakeRouterDecisions, json_mode=False)
        summary = ""
        keywords = ""
        if res and res.strip():
            lines = [ln.strip() for ln in res.strip().split("\n") if ln.strip()]
            if lines:
                # Last line = keywords; everything before = summary (may be multi-line)
                if len(lines) > 1:
                    keywords = lines[-1][:300]
                    summary_lines = lines[:-1]
                else:
                    keywords = ""
                    summary_lines = lines
                summary = " ".join(summary_lines).strip()[:600] if summary_lines else ""
            if not summary:
                summary = "Project note (summary not generated)."
        if not summary:
            summary = "Project note (summary not generated)."
        new_front = _patch_frontmatter_butler_only(
            fm_raw, summary, keywords, butler_body_hash=None, max_summary_chars=600
        )
        if no_frontmatter:
            new_content = "---\n" + new_front + "\n---\n\n" + rest_after_frontmatter
        else:
            new_content = "---\n" + new_front + "\n---" + rest_after_frontmatter
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            updated += 1
            log_memory_debug(f"Devlog butler summary added: {name}")
        except Exception as e:
            log_memory_debug(f"Devlog butler summary: could not write {path}: {e}")
    return updated


def _contains_templater_or_script_in_frontmatter(fm_raw: str) -> bool:
    """
    True if frontmatter contains Templater (<% ... %>) or script syntax.
    Butler must not modify such files; YAML round-trip or edits could corrupt them.
    """
    if not fm_raw:
        return False
    return "<%" in fm_raw or "%>" in fm_raw


def _escape_butler_value(s: str) -> str:
    """Escape a string for use as a quoted YAML value (butler_summary, etc.)."""
    if s is None:
        return ""
    return (str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " "))


def _patch_frontmatter_butler_only(
    fm_raw: str,
    butler_summary: str,
    butler_keywords: str,
    butler_body_hash: str | None = None,
    max_summary_chars: int = 500,
) -> str:
    """
    Add or update only butler_summary, butler_keywords, (optional) butler_body_hash
    in the frontmatter string. Uses regex; never parses/serializes full YAML.
    Preserves Templater, scripts, and all other frontmatter exactly.
    max_summary_chars: cap for butler_summary (devlog may use 600 for richer summary).
    """
    summary_escaped = _escape_butler_value(butler_summary)[:max_summary_chars]
    keywords_escaped = _escape_butler_value(butler_keywords)[:300]
    hash_escaped = _escape_butler_value(butler_body_hash or "")[:64]

    def _replace_or_append(content: str, key: str, value: str) -> str:
        quoted = f'"{value}"' if value else '""'
        new_line = f"{key}: {quoted}"
        pat = re.compile(rf"^{re.escape(key)}:\s*.+$", re.MULTILINE)
        if pat.search(content):
            return pat.sub(new_line, content, count=1)
        return content.rstrip() + ("\n" if content.rstrip() else "") + new_line + "\n"

    out = _replace_or_append(fm_raw or "", "butler_summary", summary_escaped)
    out = _replace_or_append(out, "butler_keywords", keywords_escaped)
    if butler_body_hash is not None:
        out = _replace_or_append(out, "butler_body_hash", hash_escaped)
    return out


def _body_hash(body: str) -> str:
    """Stable hash of body for significant-change detection."""
    return hashlib.md5((body or "").encode("utf-8")).hexdigest()


def ensure_zettel_butler_summary(path: str) -> bool:
    """
    Ensure a zettel file (under ZETTEL_VAULT_ROOT) has butler_summary and butler_keywords.
    If missing: generate via LLM and write. If present but body changed significantly
    (butler_body_hash != current body hash): regenerate and write.
    Uses regex-based frontmatter patching only; preserves Templater, scripts, and body.
    Skips files with Templater (<% %>) in frontmatter. Returns True if file was updated.
    """
    if (
        not getattr(types, "ZETTEL_VAULT_ROOT", None)
        or not path
        or not os.path.isfile(path)
    ):
        return False
    if types.is_vault_path_protected(path):
        return False
    zettel_root = os.path.abspath(types.ZETTEL_VAULT_ROOT)
    abs_path = os.path.abspath(path)
    if not abs_path.startswith(zettel_root + os.sep) and abs_path != zettel_root:
        return False
    if not is_safe_path(path):
        return False
    if is_template_path(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception as e:
        log_memory_debug(f"Zettel butler summary: could not read {path}: {e}")
        return False
    parts = raw.split("---", 2)
    no_frontmatter = len(parts) < 3
    if no_frontmatter:
        rest_after_frontmatter = raw
        fm_raw = ""
        body_for_hash = raw.strip()
    else:
        rest_after_frontmatter = parts[2]
        fm_raw = parts[1].strip()
        body_for_hash = rest_after_frontmatter.strip()
        if _contains_templater_or_script_in_frontmatter(fm_raw):
            log_memory_debug(
                f"Zettel butler summary: skip (Templater/script in frontmatter): {path}"
            )
            return False
    current_hash = _body_hash(body_for_hash)
    existing_summary = ""
    existing_hash = ""
    if fm_raw:
        m = re.search(r"^butler_summary:\s*(.+)$", fm_raw, re.MULTILINE)
        if m:
            existing_summary = m.group(1).strip().strip("\"'")
        m = re.search(r"^butler_body_hash:\s*(.+)$", fm_raw, re.MULTILINE)
        if m:
            existing_hash = m.group(1).strip().strip("\"'")
    if existing_summary and existing_hash == current_hash:
        return False
    body_preview = (body_for_hash[:3000]) if body_for_hash else "(No content.)"
    user = load_prompt(
        "21-summary-variants/08-butler_summary_keywords_zettel",
        variables={"body_preview": body_preview},
    )
    res = call_llm("", user, MODEL_SMART_MakeRouterDecisions, json_mode=False)
    summary = ""
    keywords = ""
    if res and res.strip():
        lines = [ln.strip() for ln in res.strip().split("\n") if ln.strip()]
        summary = lines[0][:500] if lines else "Zettel note (summary not generated)."
        keywords = lines[1][:300] if len(lines) > 1 else ""
    if not summary:
        summary = "Zettel note (summary not generated)."
    new_front = _patch_frontmatter_butler_only(
        fm_raw, summary, keywords, butler_body_hash=current_hash
    )
    if no_frontmatter:
        new_content = "---\n" + new_front + "\n---\n\n" + rest_after_frontmatter
    else:
        new_content = "---\n" + new_front + "\n---" + rest_after_frontmatter
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        log_memory_debug(
            f"Zettel butler summary added/updated: {os.path.basename(path)}"
        )
        return True
    except Exception as e:
        log_memory_debug(f"Zettel butler summary: could not write {path}: {e}")
        return False


# Path segments under ZETTEL_VAULT_ROOT to exclude from butler metadata (no LLM writes)
_ZETTEL_BUTLER_EXCLUDED_DIRS = ("Attachments", "10 Log", "00 Command")


def _zettel_path_excluded(path: str, zettel_root: str) -> bool:
    """True if path is under Attachments, 10 Log, or 00 Command under zettel_root."""
    if not path or not zettel_root:
        return False
    abs_path = os.path.abspath(os.path.normpath(path))
    abs_root = os.path.abspath(os.path.normpath(zettel_root))
    if not abs_path.startswith(abs_root + os.sep) and abs_path != abs_root:
        return False
    try:
        rel = os.path.relpath(os.path.dirname(abs_path), abs_root)
    except ValueError:
        return False
    parts = rel.split(os.sep)
    return any(p in _ZETTEL_BUTLER_EXCLUDED_DIRS for p in parts)


def fill_missing_zettel_butler_summaries():
    """
    For each .md under ZETTEL_VAULT_ROOT, ensure butler_summary and butler_keywords exist;
    update only if missing or body changed significantly (butler_body_hash).
    Skips paths under Attachments, 10 Log, 00 Command. Called at night heartbeat (idle-gated).
    Returns the number of files updated.
    """
    if not getattr(types, "ZETTEL_VAULT_ROOT", None) or not os.path.isdir(
        types.ZETTEL_VAULT_ROOT
    ):
        return 0
    if not is_safe_path(types.ZETTEL_VAULT_ROOT):
        return 0
    updated = 0
    zettel_root = os.path.abspath(types.ZETTEL_VAULT_ROOT)
    for dp, _, filenames in os.walk(zettel_root):
        for name in filenames:
            if not name.endswith(".md"):
                continue
            path = os.path.join(dp, name)
            if not is_safe_path(path) or not os.path.isfile(path):
                continue
            if types.is_vault_path_protected(path):
                continue
            if _zettel_path_excluded(path, zettel_root):
                continue
            if ensure_zettel_butler_summary(path):
                updated += 1
    return updated


def process_message_to_ai(message):
    """
    Record a user "message to AI" by appending to the conversational file Messages-to-AI.md.
    The AI checks this file during reflection and personality updates in the next heartbeat:
    it will note the orders in its diary (Temporal Memories) and update IDENTITY/SKILLS to adhere.
    Returns path to Messages-to-AI file or None.
    """
    return append_message_to_ai(message)


def ai_triage_diary_content(content):
    """
    AI classifies diary entry to decide how to process it.
    Returns: {"action": "dismiss|temporal|preference|deduction", "reasoning": "..."}
    Uses gemma3:12b for classification.
    """
    if not content or not content.strip():
        return {"action": "dismiss", "reasoning": "Empty content"}

    system = """You are triaging a diary entry to decide how to process it. Classify into ONE of these actions:

- "dismiss": Mundane activities with no future relevance (e.g., "eating lunch", "took a shower")
- "temporal": Time-bound observations worth noting in AI's diary (e.g., "installed new camera", "working on Python script")
- "preference": Facts about user that should persist in their profile (e.g., "has cramps monthly", "prefers dark roast coffee", "allergic to peanuts")
- "deduction": Patterns requiring deeper analysis (e.g., health correlations, behavioral patterns needing investigation)

Output ONLY valid JSON: { "action": "dismiss|temporal|preference|deduction", "reasoning": "brief explanation" }"""

    user = f"DIARY ENTRY:\n{content[:2000]}"
    try:
        from .llm_client import call_llm_structured
        from .llm_models import TriageActionResponse

        data = call_llm_structured(
            system,
            user,
            MODEL_MED,
            response_model=TriageActionResponse,
            max_retries=2,
        )
        action = (
            data.action
            if data.action in ("dismiss", "temporal", "preference", "deduction")
            else "dismiss"
        )
        return {"action": action, "reasoning": data.reasoning or ""}
    except Exception as e:
        log_memory_debug(f"⚠️ ai_triage_diary_content failed: {e}")
    return {"action": "dismiss", "reasoning": ""}


def write_structured_temporal_memory(content):
    """
    Append diary content to temporal staging (deprecated in favor of heartbeat processing).

    NEW WORKFLOW: Diary entries written to DAILY_NOTE_DIR are now processed during
    heartbeat via read_diary_entries_since_last_review(). This function is kept for
    backward compatibility but disabled by default (ENABLE_IMMEDIATE_DIARY_PROCESSING=False).
    """
    if not ENABLE_IMMEDIATE_DIARY_PROCESSING:
        log_memory_debug(
            "Immediate diary processing disabled (ENABLE_IMMEDIATE_DIARY_PROCESSING=False)"
        )
        return None
    if not content or not content.strip():
        return None
    return append_temporal_staging(content, "diary")


def compose_shift_diary_entry(since_datetime=None):
    """
    Read staged events (optionally merged across shift since since_datetime), browse recent files,
    and compose a Captain's Log style diary entry. Uses gemma3:27b. Appends to daily/YYYY-MM-DD.md
    and clears staging for the composed range.
    Returns True if diary entry was written, False if no staged events (caller may do deep reflection).
    When since_datetime is provided, merges staging from that date through today into one shift and clears all those files.
    """
    today = datetime.date.today()
    if since_datetime is not None:
        since_date = (
            since_datetime.date() if hasattr(since_datetime, "date") else since_datetime
        )
        staged, date_strs = read_staging_for_range(since_date, today)
        if not staged or not staged.strip():
            log_memory_debug(
                "compose_shift_diary_entry: no staged events in range, skipping"
            )
            return False
    else:
        staged = read_and_clear_staging()
        date_strs = [today.strftime("%Y-%m-%d")] if (staged and staged.strip()) else []
        if not staged or not staged.strip():
            log_memory_debug("compose_shift_diary_entry: no staged events, skipping")
            return False

    browse_content = browse_recent_files_for_diary(deep=False)
    persona = load_ai_personality()
    identity = persona.get("identity", "").strip()
    backstory = persona.get("backstory", "").strip()
    skills = persona.get("skills", "").strip()
    persona_block = (
        f"Your identity: {identity}\n\nBackstory: {backstory}\n\nSkills: {skills}"
        if (identity or backstory or skills)
        else PERSONA_FALLBACK
    )

    date_str = datetime.date.today().strftime("%Y-%m-%d")
    system = f"""You write your shift diary in two parts:

**Part 1 - Shift Log (Narrative):**
Write 2-3 paragraphs in Captain's Log style about the shift ("Shift {date_str}. ..."). Include overall themes, notable moments, and high-level reflections. Be conversational and use your personality. Include "notes to future self" when you have actionable insights (e.g., "Remember: when they mention X, they mean Y").

**Part 2 - Structured Observations:**
List specific observations as categorized bullets:

**User Activity:**
- [Diary entries, notes written, requests made]

**System Activity:**
- [Routing decisions, note processing, operations performed]

**Insights & Patterns:**
- [Deductions, preferences discovered, behavioral patterns]

Only include categories that have content. Each bullet should be a single clear observation.

RULES FOR NARRATIVE:
- 2-3 short paragraphs, conversational tone
- Focus on themes and meaning
- Never quote the user's exact words

RULES FOR OBSERVATIONS:
- One bullet = one observation
- Factual, concise
- Use past tense

{persona_block}"""

    user_parts = [f"STAGED EVENTS (from this shift):\n{staged.strip()}"]
    if since_datetime is not None:
        if hasattr(since_datetime, "timestamp"):
            since_ts = since_datetime.timestamp()
        else:
            dt = datetime.datetime.combine(since_date, datetime.time.min)
            since_ts = (
                time.mktime(dt.timetuple()) if dt.tzinfo is None else dt.timestamp()
            )
        shift_content = gather_vault_and_zettel_since(
            since_ts, limit_chars_per_file=4000, total_limit=24000
        )
        if shift_content and shift_content.strip():
            user_parts.append(
                f"CONTENT MODIFIED THIS SHIFT (daily notes, ideas, experiments, zettelkasten):\n{shift_content}"
            )
    if browse_content and browse_content.strip():
        user_parts.append(
            f"BROWSED FILES (you picked these as interesting):\n{browse_content[:4000]}"
        )
    user = "\n\n---\n\n".join(user_parts)

    try:
        entry = call_llm(system, user, MODEL_SMART_MakeRouterDecisions, json_mode=False)
        entry = (entry or "").strip()
        if not entry:
            log_memory_debug("compose_shift_diary_entry: LLM returned empty")
            return False
        path = append_temporal_memory(entry)
        if date_strs:
            clear_staging_for_dates(date_strs)
        log_memory_debug("compose_shift_diary_entry: wrote diary entry")
        return path is not None
    except Exception as e:
        log_memory_debug(f"compose_shift_diary_entry failed: {e}")
        return False


def deep_reflection_entry():
    """
    Long-term reflection when user is idle and no staged events. Reviews 14-30 days
    of diary, monthly summaries, deductions. Evolves backstory and consolidates themes.
    Uses gemma3:27b. Returns True if entry was written.
    """
    diary_content, _ = gather_temporal_last_week_only(
        days=30, weekly_summaries=2, limit_chars=6000
    )
    deductions_content, _ = gather_recent_deductions_read_only(
        max_files=5, max_days=30, limit_chars=3000
    )
    browse_content = browse_recent_files_for_diary(deep=True)

    if not diary_content and not deductions_content:
        log_memory_debug("deep_reflection_entry: no diary or deductions to reflect on")
        return False

    persona = load_ai_personality()
    identity = persona.get("identity", "").strip()
    backstory = persona.get("backstory", "").strip()
    persona_block = (
        f"Your identity: {identity}\n\nBackstory: {backstory}"
        if (identity or backstory)
        else PERSONA_FALLBACK
    )

    system = """You are reflecting on the past few weeks. Write a diary entry in your own voice.
Look for: emerging themes, recurring user interests, behavioral shifts, unresolved questions.
You may develop your backstory, add fictional details, or evolve your character.
Include "notes to future self" for insights worth remembering.
{persona_block}

RULES:
- Write 3-6 short paragraphs. Be reflective, not reactive.
- Never quote the user's exact words.
- Use a casual, conversational tone."""

    user_parts = []
    if diary_content:
        user_parts.append(
            f"RECENT DIARY ENTRIES (past ~30 days):\n{diary_content[:8000]}"
        )
    if deductions_content:
        user_parts.append(f"RECENT DEDUCTIONS:\n{deductions_content}")
    if browse_content:
        user_parts.append(f"BROWSED FILES (deeper look):\n{browse_content[:3000]}")
    user = "\n\n---\n\n".join(user_parts)

    try:
        entry = call_llm(system, user, MODEL_SMART_MakeRouterDecisions, json_mode=False)
        entry = (entry or "").strip()
        if not entry:
            log_memory_debug("deep_reflection_entry: LLM returned empty")
            return False
        path = append_temporal_memory(entry)
        log_memory_debug("deep_reflection_entry: wrote diary entry")
        return path is not None
    except Exception as e:
        log_memory_debug(f"deep_reflection_entry failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Daily digest (questions, health, follow-ups from diary)
# ---------------------------------------------------------------------------

DAILY_DIGEST_SYSTEM_PROMPT = """
You are a smart, observant, and proactive "Coach-Nanny" aide. Your goal is to process the user's daily log to save them time (by answering un-googled questions) and improve their workflow (by spotting behavioral patterns).

**The Persona:**
- **The Coach:** You analyze performance. You don't just say "You were distracted"; you find the *trigger* that caused the distraction based on the timeline. You validate wins strongly.
- **The Nanny:** You are protective. You flag health issues that look persistent or concerning (mold, pains, allergies), but you don't nag about minor tiredness.
- **The Aide:** You are helpful. You answer the factual questions the user didn't have time to investigate.

**Tone:** Casual, direct, warm, but high-agency. Use "You." No corporate jargon.
**Context:** The user is in Singapore. Keep local context in mind (weather, humidity, operating hours).

### INPUT DATA
1. <daily_log>: Timestamped events, notes, and stream-of-consciousness thoughts.
2. <deduction_context>: Known habits and patterns.
3. <completed_tasks>: Tasks checked off today.

### PHASE 1: INTERNAL ANALYSIS (Hidden Thought Process)
Before writing the response, perform this analysis internally:

1.  **Question Filtering:** Scan the log for questions.
    *   *Discard* rhetorical/venting questions (e.g., "Why is X so annoying?").
    *   *Keep* informational/curiosity gaps (e.g., "Is the new Minecraft modpack easier?", "How does X technology work?").
    *   *Action:* Research the answers for the "Keep" list.

2.  **Timeline & Energy Forensics:**
    *   Look at the timestamps. Where did the time go?
    *   Did a specific event (e.g., a phone call at 10:00) derail the rest of the day?
    *   Did a small action (e.g., "putting on shoes") lead to a big win (e.g., "going for a run")? *Highlight this mechanism.*

3.  **Health Triage:**
    *   Scan for symptoms: Pain, nausea, rash, anxiety, insomnia.
    *   Scan for risks: Moldy food, expired items, skipped meds, allergens (fragrance).
    *   *Decision:* Is this a "rest" suggestion or a "go to doctor/throw it away" command?

### PHASE 2: THE OUTPUT (The Digest)
Structure your response exactly as follows:

#### 1. The Research Assistant 🧠
*Look for those informational gaps identified in Phase 1. Provide a concise, interesting answer here so the user doesn't have to Google it. If no genuine questions were asked, skip this section entirely.*

#### 2. The Coach's Review ⏱️
*Synthesize, don't summarize.*
*   **The Win:** Briefly acknowledge what went right (check <completed_tasks> and log sentiment).
*   **The Insight:** Connect the dots. Example: "You felt scattered at 2 PM, likely because you skipped the deep-work block you planned at 10 AM." or "The 'Watch Band' trick successfully bypassed your executive dysfunction."
*   **The Pattern:** Reference <deduction_context>. Are we reinforcing a bad loop or breaking out of one?

#### 3. The Nanny's Check-in ❤️
*Only comment if necessary.*
*   If the user is just "tired," say nothing or keep it very brief.
*   If there is a red flag (recurring pain, physical symptoms, hygiene risks like mold), gently but firmly suggest a specific action.

#### 4. Tomorrow's Focus 🚀
*1-2 clear, low-friction nudges based on today's loose ends.*
*   **Constraint:** CROSS-REFERENCE <completed_tasks>. Never suggest a task that is already done.
*   **Constraint:** If a task was skipped today, ask *why* or suggest a smaller version of it.

Output valid JSON matching the response schema. Use null or empty string for optional sections (Research Assistant when no questions, Nanny when nothing to report).
"""


def _parse_completed_tasks_from_daily_note(raw_note_text):
    """Parse daily note for completed checkbox tasks (- [x] or - [X]). Returns list of task text strings."""
    if not raw_note_text or not raw_note_text.strip():
        return []
    completed = []
    # Match - [x] or - [X] at start of line (with optional leading whitespace)
    for line in raw_note_text.splitlines():
        m = re.match(r"^\s*[-*]\s*\[[xX]\]\s*(.+)$", line.strip())
        if m:
            task = m.group(1).strip()
            if task:
                completed.append(task)
    return completed


def extract_daily_digest(daily_note_path, date_str):
    """
    Extract digest from a daily note file. Returns formatted markdown string or None.
    Uses call_llm_structured() with DailyDigestResponse model and gemma3:27b.
    Includes deduction system context (Deductions + Patterns) for "What the deduction
    system is contemplating" and completed tasks so follow-ups exclude already-done items.

    Args:
        daily_note_path: Path to the daily note file
        date_str: Date string (YYYY-MM-DD) for the digest header

    Returns:
        Formatted markdown string or None if no content
    """
    if not os.path.isfile(daily_note_path):
        return None
    raw = safe_read_text(daily_note_path, limit_chars=80000)
    if not raw or not raw.strip():
        return None
    # Prefer content under ## Log (diary entries)
    log_match = re.search(r"##\s+Log\s*\n", raw, re.IGNORECASE)
    content_to_analyze = raw[log_match.end() :].strip() if log_match else raw.strip()
    if not content_to_analyze:
        return None

    # 1. Prepare Deduction Context (Wrapped in XML)
    deductions_text, _ = gather_recent_deductions_read_only(
        max_files=10, max_days=14, limit_chars=8000
    )
    patterns_text, _ = gather_recent_patterns_read_only(
        max_files=5, max_days=14, limit_chars=4000
    )
    deduction_block = ""
    if deductions_text or patterns_text:
        deduction_block = f"""
<deduction_context>
The following are established patterns. Use these to analyze today's behavior:
Deductions: {deductions_text or "None"}
Patterns: {patterns_text or "None"}
</deduction_context>
"""

    # 2. Prepare Completed Tasks (Wrapped in XML)
    completed_tasks = _parse_completed_tasks_from_daily_note(raw)
    completed_block = ""
    if completed_tasks:
        task_list = "\n".join(f"- {t}" for t in completed_tasks[:50])
        completed_block = f"""
<completed_tasks>
The following are ALREADY DONE. Do not suggest them:
{task_list}
</completed_tasks>
"""

    # 3. Prepare Diary Content (truncate from end so summary/reflection is kept)
    if len(content_to_analyze) > 12000:
        content_to_analyze = "...(truncated start)...\n" + content_to_analyze[-12000:]

    diary_block = f"""
<daily_log>
Date: {date_str}
{content_to_analyze}
</daily_log>
"""

    # 4. Prepend current date/time for relative-time reasoning, then order: daily_log, completed_tasks, deduction_context
    now = datetime.datetime.now()
    current_date_str = f"{now.strftime('%A, %b')} {now.day} {now.year}"
    current_time_str = now.strftime("%I:%M %p").lstrip("0").lstrip()  # e.g. "10:48 PM"
    if current_time_str.startswith(":"):
        current_time_str = "12" + current_time_str  # 12:00 edge case
    header = f"CURRENT DATE: {current_date_str}\nCURRENT TIME: {current_time_str}\n"
    user_blob = f"{header}\n{diary_block}\n\n{completed_block}\n\n{deduction_block}"

    try:
        from .llm_client import call_llm_structured
        from .llm_models import DailyDigestResponse

        data = call_llm_structured(
            DAILY_DIGEST_SYSTEM_PROMPT,
            user_blob,
            MODEL_SMART_MakeRouterDecisions,
            response_model=DailyDigestResponse,
            max_retries=2,
        )
    except Exception as e:
        log_memory_debug(f"extract_daily_digest LLM failed: {e}")
        return None

    if not data:
        return None
    parts = [f"# Daily Digest - {date_str}\n"]
    if data.research_assistant and data.research_assistant.strip():
        parts.append("## 1. The Research Assistant 🧠\n\n")
        parts.append(data.research_assistant.strip())
        parts.append("\n\n")
    parts.append("## 2. The Coach's Review ⏱️\n\n")
    parts.append((data.coach_review or "").strip())
    parts.append("\n\n")
    if data.nanny_checkin and data.nanny_checkin.strip():
        parts.append("## 3. The Nanny's Check-in ❤️\n\n")
        parts.append(data.nanny_checkin.strip())
        parts.append("\n\n")
    if data.tomorrow_focus:
        parts.append("## 4. Tomorrow's Focus 🚀\n\n")
        for s in data.tomorrow_focus:
            if s and s.strip():
                parts.append(f"- {s.strip()}\n")
        parts.append("\n")
    has_content = (
        (data.research_assistant and data.research_assistant.strip())
        or (data.coach_review and data.coach_review.strip())
        or (data.nanny_checkin and data.nanny_checkin.strip())
        or bool(data.tomorrow_focus)
    )
    if not has_content:
        return None
    return "".join(parts).strip()


def extract_daily_digest_from_yesterday():
    """
    Extract questions, health symptoms, and follow-ups from yesterday's daily note.
    Called during heartbeat night processing (3-6AM). Uses gemma3:27b.
    Saves digest to Daily Digest folder with YYYY-MM-DD format.
    Returns path to digest file or None if no content.
    """
    now = datetime.datetime.now()
    if now.hour < 4:
        note_date = now.date() - datetime.timedelta(days=2)
    else:
        note_date = now.date() - datetime.timedelta(days=1)
    date_str = note_date.strftime("%Y-%m-%d")
    path = os.path.join(DAILY_NOTE_DIR, f"{date_str}.md")
    markdown = extract_daily_digest(path, date_str)
    if not markdown:
        return None
    try:
        os.makedirs(DAILY_DIGEST_DIR, exist_ok=True)
    except OSError as e:
        log_memory_debug(
            f"extract_daily_digest_from_yesterday: could not create dir: {e}"
        )
        return None
    out_path = os.path.join(DAILY_DIGEST_DIR, f"{date_str}.md")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(markdown)
    except OSError as e:
        log_memory_debug(f"extract_daily_digest_from_yesterday: could not write: {e}")
        return None
    return out_path


def write_preference_with_dedup_check(content):
    """
    Extract preferences/attributes and save to Information on Moi.
    Uses deepseek-r1:32b to check if observation matches existing patterns.
    If pattern exists: append to Temporal Memories/Patterns/{slug}.md and update count.
    If no pattern: write new dated entry to Information on Moi (for later synthesis).
    Returns message string.
    """
    if not content or not content.strip():
        return "No content to process"

    log_memory_debug("Checking preferences against existing patterns...")

    # First, extract the preference/attribute
    statements = extract_preference_statements(content)
    if not statements or not statements.strip():
        log_memory_debug("No preference statements extracted")
        return "No preferences extracted"

    # Check if this matches an existing pattern in Information on Moi
    ensure_dir(PREFERENCES_MEMORY_ROOT)
    md_files = list_md_files_in_folder(PREFERENCES_MEMORY_ROOT)

    if not md_files:
        # No existing files, just use handle_memory
        return handle_memory(content)

    # Read existing patterns to check for matches
    patterns = []
    for fp in md_files:
        content_text = safe_read_text(fp, limit_chars=10000)
        if content_text and "## Patterns" in content_text:
            patterns.append({"file": os.path.basename(fp), "content": content_text})

    if not patterns:
        # No patterns exist yet, use normal flow
        return handle_memory(content)

    # Use deepseek to check if this observation matches existing patterns
    system = """You analyze if a new observation matches an existing pattern in the user's profile.

Given existing patterns and a new observation, determine:
1. Does it match an existing pattern? (affirms or disproves it)
2. Which pattern file it belongs to (e.g., health-menstrual-cramps)
3. Whether it affirms or disproves the pattern

Output ONLY valid JSON:
{
  "matches_pattern": true/false,
  "pattern_slug": "health-menstrual-cramps" or null,
  "relationship": "affirms|disproves|none",
  "reasoning": "brief explanation"
}"""

    patterns_summary = "\n\n".join([
        f"File: {p['file']}\n{p['content'][:1500]}" for p in patterns[:5]
    ])
    user = f"EXISTING PATTERNS:\n{patterns_summary}\n\nNEW OBSERVATION:\n{statements[:1000]}"

    try:
        from .llm_client import call_llm_structured
        from .llm_models import PatternMatchResponse

        raw = call_llm_structured(
            system,
            user,
            MODEL_SMART_MakeInstructions,
            response_model=PatternMatchResponse,
            max_retries=2,
        )
        match_data = raw
    except Exception as e:
        log_memory_debug(f"⚠️ pattern match LLM failed: {e}")
        match_data = None

    if match_data and match_data.matches_pattern and match_data.pattern_slug:
        patterns_dir = os.path.join(TEMPORAL_MEMORIES_ROOT, TEMPORAL_PATTERNS_FOLDER)
        ensure_dir(patterns_dir)
        pattern_file = os.path.join(patterns_dir, f"{match_data.pattern_slug}.md")

        now = datetime.datetime.now().strftime("%Y-%m-%d")
        observation_line = f"- {now}: {statements.strip()}\n"

        if os.path.exists(pattern_file):
            with open(pattern_file, "a", encoding="utf-8") as f:
                f.write(observation_line)
            log_memory_debug(f"Appended to pattern archive: {match_data.pattern_slug}")
            return f"Pattern Match | {match_data.pattern_slug}"
        else:
            return handle_memory(content)
    else:
        # No pattern match, use normal flow (will be synthesized later)
        return handle_memory(content)


def process_diary_memory(content):
    """
    Main orchestrator for diary memory processing.
    Called by diary-memory-save-background.py.
    1. Triage content (dismiss, temporal, preference, deduction)
    2. Route to appropriate handler
    3. Increment deduction counter if needed
    """
    if not content or not content.strip():
        log_memory_debug("Empty content, skipping diary memory processing")
        return

    log_memory_debug("Processing diary memory...")

    # Triage
    triage = ai_triage_diary_content(content)
    action = triage.get("action", "dismiss")
    reasoning = triage.get("reasoning", "")

    log_memory_debug(f"Triage decision: {action} - {reasoning}")

    if action == "dismiss":
        log_memory_debug("Content dismissed as not significant")
        return

    if action == "temporal":
        write_structured_temporal_memory(content)
        log_memory_debug("Wrote to Temporal Memories")

    if action == "preference":
        result = write_preference_with_dedup_check(content)
        log_memory_debug(f"Preference processing: {result}")

    if action == "deduction":
        run_deduction_increment_in_background()
        log_memory_debug("Flagged for deduction pipeline")


def _path_to_obsidian_wiki_link(file_path):
    """
    Return Obsidian wiki-style link for a file path (no .md suffix).
    Vault notes: [[Journal/Journals/2026-02-05]]. Temporal: [[Temporal Memories/2026-02-05]].
    """
    if not file_path:
        return ""
    path = os.path.normpath(file_path)
    base = os.path.basename(path)
    name_no_ext = base[:-3] if base.endswith(".md") else base
    try:
        if path.startswith(VAULT_ROOT + os.sep) or path == VAULT_ROOT:
            rel = os.path.relpath(path, VAULT_ROOT)
            rel = rel.replace("\\", "/")
            if rel.endswith(".md"):
                rel = rel[:-3]
            return f"[[{rel}]]"
        if (
            path.startswith(TEMPORAL_MEMORIES_ROOT + os.sep)
            or path == TEMPORAL_MEMORIES_ROOT
        ):
            rel = os.path.relpath(path, TEMPORAL_MEMORIES_ROOT)
            rel = rel.replace("\\", "/")
            if rel.endswith(".md"):
                rel = rel[:-3]
            return f"[[Temporal Memories/{rel}]]"
    except ValueError:
        pass
    return f"[[{name_no_ext}]]"


def _extract_tags_for_deduction_text(text):
    """Extract 1-5 searchable hashtags from a deduction section (hypothesis, evidence, or conclusion). Returns list of tag strings."""
    if not text or not str(text).strip():
        return []
    system = """You extract 1-5 searchable hashtags from the given text. Tags should be lowercase, hyphenated (e.g. #coffee-preference #medium-roast #smart-home #cctv-camera).
Output ONLY valid JSON: { "tags": ["#tag1", "#tag2", ...] }"""
    user = f"TEXT:\n{str(text).strip()[:1500]}"
    try:
        from .llm_client import call_llm_structured
        from .llm_models import TagsResponse

        data = call_llm_structured(
            system,
            user,
            MODEL_MED,
            response_model=TagsResponse,
            max_retries=2,
        )
        return _clean_and_validate_tags(data.tags, 5)
    except Exception as e:
        log_memory_debug(f"⚠️ _extract_tags_for_deduction_text failed: {e}")
    return []


# Length limits for deduction .md sections (truncate with ...[truncated]... when exceeded)
DEDUCTION_HYPOTHESIS_MAX_CHARS = 2000
DEDUCTION_EVIDENCE_MAX_CHARS = 30000
DEDUCTION_CONCLUSION_MAX_CHARS = 3000
DEDUCTION_APPENDED_EVIDENCE_MAX_CHARS = 15000


def _normalize_deduction_text(text, max_chars=None, default="(none)"):
    """
    Normalize text for writing to deduction .md files: decode HTML entities (e.g. &#39 -> ')
    and normalize Unicode to NFC. Optionally truncate to max_chars with ...[truncated]...
    Returns default when text is empty or None.
    """
    if text is None or not str(text).strip():
        return default
    s = str(text).strip()
    s = html.unescape(s)
    s = unicodedata.normalize("NFC", s)
    if max_chars is not None and len(s) > max_chars:
        s = s[:max_chars].rstrip() + "\n\n...[truncated]..."
    return s


def normalize_deduction_text_for_write(text, max_chars=None, default=""):
    """
    Public wrapper for normalizing text before writing to deduction .md (e.g. appended evidence).
    Uses default="" so callers can normalize a segment without inserting "(none)".
    """
    return _normalize_deduction_text(text, max_chars=max_chars, default=default)


def save_deduction(
    hypothesis, evidence, conclusion, source_paths, slug=None, search_terms=None
):
    """
    Save a deduction (hypothesis, evidence, conclusion) to the Deductions folder with
    date and Obsidian wiki-style links to source note file paths.
    Filename format: {date}-{n}-{slug}.md where slug is an informative phrase about the deduction.
    Only writes under TEMPORAL_MEMORIES_ROOT (never to human daily notes).
    If search_terms is provided (list of strings), prepends "Search keywords used: ..." to Evidence.
    Returns path written or None.
    """

    def _do():
        return _save_deduction_impl(
            hypothesis, evidence, conclusion, source_paths, slug, search_terms
        )

    return _safe_write_wrapper(_do, "save-deduction")


def _save_deduction_impl(
    hypothesis, evidence, conclusion, source_paths, slug=None, search_terms=None
):
    """Internal: save deduction to disk. See save_deduction."""
    if not hypothesis and not conclusion:
        return None
    ensure_dir(TEMPORAL_MEMORIES_ROOT)
    deductions_dir = os.path.join(TEMPORAL_MEMORIES_ROOT, TEMPORAL_DEDUCTIONS_FOLDER)
    ensure_dir(deductions_dir)
    if not is_safe_temporal_path(deductions_dir):
        log_memory_debug("⚠️ Deductions dir unsafe")
        return None

    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")

    # Use slug if provided, otherwise fallback to "deduction"
    if not slug or not isinstance(slug, str):
        slug = "deduction"
    slug = slug.strip()

    # Find next available number for this date
    n = 1
    while True:
        base_name = f"{date_str}-{n}-{slug}.md"
        path = os.path.join(deductions_dir, base_name)
        if not os.path.exists(path):
            break
        n += 1
        if n > 100:  # safety limit
            base_name = f"{date_str}-{n}-{slug}-{now.strftime('%H-%M')}.md"
            path = os.path.join(deductions_dir, base_name)
            break

    if not is_safe_temporal_path(path):
        log_memory_debug(f"⚠️ Unsafe deduction path: {path}")
        return None

    # Normalize and cap hypothesis, evidence, conclusion (HTML unescape, NFC, length limits)
    hyp_block = _normalize_deduction_text(
        hypothesis, max_chars=DEDUCTION_HYPOTHESIS_MAX_CHARS
    )
    ev_block = _normalize_deduction_text(
        evidence, max_chars=DEDUCTION_EVIDENCE_MAX_CHARS
    )
    if search_terms and isinstance(search_terms, (list, tuple)):
        terms_str = ", ".join(
            str(t).strip() for t in search_terms if t and str(t).strip()
        )
        if terms_str:
            ev_block = "Search keywords used: " + terms_str + "\n\n" + ev_block
    conc_block = _normalize_deduction_text(
        conclusion, max_chars=DEDUCTION_CONCLUSION_MAX_CHARS
    )

    links_block = ""
    if source_paths:
        links = []
        for p in source_paths:
            if isinstance(p, str) and p.strip():
                links.append(_path_to_obsidian_wiki_link(p.strip()))
        if links:
            links_block = "\n\n## Source links\n\n" + "\n".join(
                "- " + ln for ln in links if ln
            )
    body = (
        f"# Deduction {date_str}\n\n"
        f"## Hypothesis\n\n{hyp_block}\n\n"
        f"## Evidence\n\n{ev_block}\n\n"
        f"## Conclusion\n\n{conc_block}"
        f"{links_block}\n"
    )
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        log_memory_debug(
            f"Wrote deduction -> {TEMPORAL_DEDUCTIONS_FOLDER}/{os.path.basename(path)}"
        )
        # Succinct audit line for new deductions (llm_router_audit.log)
        hyp_snippet = snippet(hypothesis, 80) if hypothesis else "(none)"
        log_debug(f"[Deduction] New: {os.path.basename(path)} — {hyp_snippet}")
        return path
    except Exception as e:
        log_write_failure("write deduction", path, e)
        return None


def gather_evidence_read_only(days=7, limit_chars=8000):
    """
    Spawn a read-only child process that reads from human daily notes (Journal/Journals)
    and temporal memory daily files. Child does NOT modify any files. Returns
    (content, source_paths) for the parent to write conclusions to temporal file of the day,
    Preferences, or Deductions. Security: memory system never writes to human daily notes.
    """
    if not os.path.isfile(MEMORY_EVIDENCE_READER_SCRIPT):
        log_memory_debug("⚠️ Memory evidence reader script not found; skipping.")
        return "", []
    try:
        result = subprocess.run(
            [PYTHON_EXEC, MEMORY_EVIDENCE_READER_SCRIPT, str(days), str(limit_chars)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0 or not result.stdout.strip():
            log_memory_debug("⚠️ Evidence reader returned no output.")
            return "", []
        data = parse_json(result.stdout)
        if not data:
            return "", []
        content = data.get("content") or ""
        source_paths = data.get("source_paths")
        if not isinstance(source_paths, list):
            source_paths = []
        log_memory_debug(f"Evidence reader gathered {len(source_paths)} source(s).")
        return content, source_paths
    except subprocess.TimeoutExpired:
        log_memory_debug("⚠️ Evidence reader timed out.")
        return "", []
    except Exception as e:
        log_memory_debug(f"⚠️ Evidence reader failed: {e}")
        return "", []


def gather_vault_read_only(
    under_paths,
    max_age_months=None,
    max_age_days=None,
    limit_chars_per_file=8000,
):
    """
    Read-only: list and read .md files under given vault paths, filtered by mtime.
    Use max_age_days if provided, else max_age_months * 30.
    Returns (content_string, source_paths).
    Only reads; never writes. Restricts to paths under VAULT_ROOT.
    """
    if not under_paths:
        return "", []
    if max_age_days is not None:
        cutoff = time.time() - (max_age_days * 24 * 3600)
    else:
        months = max_age_months if max_age_months is not None else 3
        cutoff = time.time() - (months * 30 * 24 * 3600)
    allowed_roots = []
    for root in under_paths:
        root = os.path.abspath(os.path.normpath(root))
        if root != VAULT_ROOT and not root.startswith(VAULT_ROOT + os.sep):
            continue
        if os.path.isdir(root):
            allowed_roots.append(root)
    parts = []
    source_paths = []
    seen = set()
    for fp, mtime in _walk_md_files(allowed_roots, since_ts=cutoff):
        if fp in seen:
            continue
        seen.add(fp)
        content = safe_read_text(fp, limit_chars=limit_chars_per_file)
        if content:
            rel = os.path.relpath(fp, VAULT_ROOT).replace("\\", "/")
            parts.append(f"--- {rel} ---\n{content.strip()}")
            source_paths.append(fp)
    combined = "\n\n".join(parts) if parts else ""
    return combined, source_paths


def gather_vault_and_zettel_since(
    since_ts, limit_chars_per_file=4000, total_limit=24000
):
    """
    Read-only: gather .md files from DAILY_NOTE_DIR, IDEAS_DIR, EXPERIMENT_DIR,
    and ZETTELKASTEN_FOLDERS modified after since_ts. Returns one text block
    (--- path ---\\ncontent) up to total_limit chars. For shift-diary context.
    """
    roots = [DAILY_NOTE_DIR, IDEAS_DIR, EXPERIMENT_DIR]
    if ZETTELKASTEN_FOLDERS:
        roots = roots + list(ZETTELKASTEN_FOLDERS)
    roots = [r for r in roots if r and os.path.isdir(r)]
    if not roots:
        return ""
    parts = []
    total = 0
    for path, mtime in _walk_md_files(
        roots, since_ts=since_ts, should_skip_func=should_skip_file
    ):
        if total >= total_limit:
            break
        content = safe_read_text(path, limit_chars=limit_chars_per_file)
        if content:
            rel = (
                os.path.relpath(path, VAULT_ROOT).replace("\\", "/")
                if VAULT_ROOT
                else path
            )
            block = f"--- {rel} ---\n{content.strip()}"
            if total + len(block) > total_limit:
                block = block[: total_limit - total - 20] + "\n...[truncated]"
            parts.append(block)
            total += len(block)
    return "\n\n".join(parts) if parts else ""


# -----------------------------------------------------------------------------
# Heartbeat context cache (shared by reflection and deduction)
# -----------------------------------------------------------------------------

HEARTBEAT_CONTEXT_CACHE_TTL_SEC = 600

_heartbeat_context_cache = {
    "journal_temporal": "",
    "vault": "",
    "preferences_summary": "",
    "fetched_at": 0,
}


def gather_information_on_moi_short(limit_chars=5000):
    """
    Read-only: short read of preference files under PREFERENCES_MEMORY_ROOT.
    Returns a single string: per-file blocks (--- name ---\\n first N chars) up to limit_chars total.
    """
    if not PREFERENCES_MEMORY_ROOT or not os.path.isdir(PREFERENCES_MEMORY_ROOT):
        return ""
    if not is_safe_preferences_path(PREFERENCES_MEMORY_ROOT):
        return ""
    md_files = list_md_files_in_folder(PREFERENCES_MEMORY_ROOT)
    parts = []
    total = 0
    per_file = max(300, limit_chars // max(1, len(md_files)))
    for path in md_files[:30]:
        if total >= limit_chars:
            break
        if not is_safe_preferences_path(path) or not os.path.isfile(path):
            continue
        content = safe_read_text(path, limit_chars=per_file)
        if content:
            name = os.path.basename(path)
            block = f"--- {name} ---\n{content.strip()}"
            if total + len(block) > limit_chars:
                block = block[: limit_chars - total - 20] + "\n...[truncated]"
            parts.append(block)
            total += len(block)
    return "\n\n".join(parts) if parts else ""


def get_or_fill_heartbeat_context_cache(force_refill=False):
    """
    Return cached dict with journal_temporal, vault, preferences_summary for heartbeat consumers.
    If cache is empty or stale (TTL exceeded) or force_refill, gather and store. Thread-unsafe.
    """
    global _heartbeat_context_cache
    now = time.time()
    if (
        not force_refill
        and _heartbeat_context_cache.get("fetched_at", 0)
        + HEARTBEAT_CONTEXT_CACHE_TTL_SEC
        > now
    ):
        return _heartbeat_context_cache
    journal_temporal, _ = gather_evidence_read_only(days=7, limit_chars=8000)
    vault_paths = [DAILY_NOTE_DIR, IDEAS_DIR]
    vault_content, _ = gather_vault_read_only(
        vault_paths, max_age_days=7, limit_chars_per_file=4000
    )
    preferences_summary = gather_information_on_moi_short(limit_chars=5000)
    _heartbeat_context_cache = {
        "journal_temporal": journal_temporal or "",
        "vault": vault_content or "",
        "preferences_summary": preferences_summary or "",
        "fetched_at": now,
    }
    return _heartbeat_context_cache


def gather_recent_deductions_read_only(max_files=10, max_days=14, limit_chars=8000):
    """
    Read-only: list and read .md deduction files in TEMPORAL_MEMORIES_ROOT/Deductions/,
    sorted by mtime descending. Takes last max_files or files modified within max_days
    (whichever is stricter). Returns (content_string, source_paths).
    Skips Pending.md. Content includes Hypothesis / Evidence / Conclusion sections.
    """
    if not TEMPORAL_MEMORIES_ROOT or not is_safe_temporal_path(TEMPORAL_MEMORIES_ROOT):
        return "", []
    deductions_dir = os.path.join(TEMPORAL_MEMORIES_ROOT, TEMPORAL_DEDUCTIONS_FOLDER)
    if not os.path.isdir(deductions_dir):
        return "", []

    cutoff_time = time.time() - (max_days * 24 * 3600)
    candidates = []
    for name in os.listdir(deductions_dir) or []:
        if not name.endswith(".md") or name == "Pending.md":
            continue
        path = os.path.join(deductions_dir, name)
        if not os.path.isfile(path) or not is_safe_temporal_path(path):
            continue
        try:
            mtime = os.path.getmtime(path)
            candidates.append((path, mtime))
        except OSError:
            continue

    candidates.sort(key=lambda x: x[1], reverse=True)
    selected = []
    for path, mtime in candidates[:max_files]:
        if mtime < cutoff_time:
            break
        selected.append(path)

    parts = []
    source_paths = []
    for path in selected:
        content = safe_read_text(path, limit_chars=limit_chars)
        if content:
            basename = os.path.basename(path)
            label = f"[Deduction: {basename[:-3]}]"
            parts.append(f"{label}\n\n{content.strip()}")
            source_paths.append(path)

    combined = "\n\n---\n\n".join(parts) if parts else ""
    return combined, source_paths


def gather_recent_patterns_read_only(max_files=5, max_days=14, limit_chars=4000):
    """
    Read-only: list and read .md files in TEMPORAL_MEMORIES_ROOT/Patterns/,
    sorted by mtime descending. Takes last max_files or files modified within max_days.
    Returns (content_string, source_paths).
    """
    if not TEMPORAL_MEMORIES_ROOT or not is_safe_temporal_path(TEMPORAL_MEMORIES_ROOT):
        return "", []
    patterns_dir = os.path.join(TEMPORAL_MEMORIES_ROOT, TEMPORAL_PATTERNS_FOLDER)
    if not os.path.isdir(patterns_dir):
        return "", []

    cutoff_time = time.time() - (max_days * 24 * 3600)
    candidates = []
    for name in os.listdir(patterns_dir) or []:
        if not name.endswith(".md"):
            continue
        path = os.path.join(patterns_dir, name)
        if not os.path.isfile(path) or not is_safe_temporal_path(path):
            continue
        try:
            mtime = os.path.getmtime(path)
            candidates.append((path, mtime))
        except OSError:
            continue

    candidates.sort(key=lambda x: x[1], reverse=True)
    selected = []
    for path, mtime in candidates[:max_files]:
        if mtime < cutoff_time:
            break
        selected.append(path)

    parts = []
    source_paths = []
    for path in selected:
        content = safe_read_text(path, limit_chars=limit_chars)
        if content:
            basename = os.path.basename(path)
            label = f"[Pattern: {basename[:-3]}]"
            parts.append(f"{label}\n\n{content.strip()}")
            source_paths.append(path)

    combined = "\n\n---\n\n".join(parts) if parts else ""
    return combined, source_paths


def _parse_daily_filename(basename):
    """Return datetime.date if basename is YYYY-MM-DD.md else None."""
    if not basename or not basename.endswith(".md"):
        return None
    try:
        return datetime.datetime.strptime(basename[:-3], "%Y-%m-%d").date()
    except ValueError:
        return None


def _dates_for_iso_week(year, week):
    """Return list of 7 datetime.date for Mon-Sun of the given ISO week."""
    # First day of ISO year/week is a Monday
    d = datetime.date(year, 1, 4)
    while d.isocalendar()[1] != 1:
        d -= datetime.timedelta(days=1)
    start = d + datetime.timedelta(weeks=week - 1)
    return [start + datetime.timedelta(days=i) for i in range(7)]


def _read_daily_content(date_obj, root_dir):
    """Read content of daily file from root (temporal memory root). Return '' if missing."""
    name = date_obj.strftime("%Y-%m-%d") + ".md"
    path = os.path.join(root_dir, name)
    if os.path.isfile(path) and is_safe_temporal_path(path):
        return safe_read_text(path, limit_chars=8000)
    return ""


def _generate_weekly_summary(year, week, root_dir):
    """Generate succinct weekly summary from 7 daily files in root. Returns summary text or ''."""
    dates = _dates_for_iso_week(year, week)
    parts = []
    for d in dates:
        content = _read_daily_content(d, root_dir)
        if content:
            parts.append(f"--- {d} ---\n{content}")
    if not parts:
        return ""
    combined = "\n\n".join(parts)
    system = load_prompt("21-summary-variants/04-weekly_temporal_rollup")
    user = f"WEEK {year}-W{week:02d} DAILY ENTRIES:\n\n{combined[:12000]}"
    res = call_llm(system, user, MODEL_MED)
    return (res or "").strip()


def _generate_monthly_summary(year, month, weekly_dir, temporal_root):
    """Generate succinct monthly summary from weekly summaries or daily files in root. Returns summary text or ''."""
    prefix = f"{year}-{month:02d}"
    parts = []
    for name in sorted(os.listdir(weekly_dir) if os.path.isdir(weekly_dir) else []):
        if not name.endswith(".md") or not is_safe_temporal_path(
            os.path.join(weekly_dir, name)
        ):
            continue
        if name.startswith(f"{year}-W") and name.endswith(".md"):
            try:
                w = int(name[6:8])
                for d in _dates_for_iso_week(year, w):
                    if d.month == month:
                        path = os.path.join(weekly_dir, name)
                        parts.append(safe_read_text(path, limit_chars=4000))
                        break
            except ValueError:
                pass
    # Fallback: read daily files from daily/ subfolder for this month
    daily_dir = (
        os.path.join(temporal_root, TEMPORAL_DAILY_FOLDER) if temporal_root else None
    )
    if not parts and daily_dir and os.path.isdir(daily_dir):
        for name in sorted(os.listdir(daily_dir) or []):
            if name.startswith(prefix) and name.endswith(".md"):
                path = os.path.join(daily_dir, name)
                if is_safe_temporal_path(path):
                    parts.append(safe_read_text(path, limit_chars=3000))
    if not parts:
        return ""
    combined = "\n\n".join(parts)[:15000]
    system = load_prompt("21-summary-variants/05-monthly_temporal_rollup")
    user = f"MONTH {year}-{month:02d}:\n\n{combined}"
    res = call_llm(system, user, MODEL_MED)
    return (res or "").strip()


def _get_sorted_weekly_files(weekly_dir, reverse=True):
    """
    Return list of (year, week, path) tuples for weekly summary files in chronological order.

    Args:
        weekly_dir: Directory containing weekly summary files
        reverse: If True, newest first; if False, oldest first
    """
    weekly_files = []
    for name in os.listdir(weekly_dir) or []:
        if not name.endswith(".md") or not name.startswith("20"):
            continue
        path = os.path.join(weekly_dir, name)
        if not is_safe_temporal_path(path):
            continue
        try:
            y, w = int(name[0:4]), int(name[6:8])
            weekly_files.append((y, w, path))
        except ValueError:
            continue
    weekly_files.sort(reverse=reverse)
    return weekly_files


def _ensure_temporal_dirs():
    """Ensure temporal memory directories exist and return (daily_dir, weekly_dir, monthly_dir)."""
    daily_dir = os.path.join(TEMPORAL_MEMORIES_ROOT, TEMPORAL_DAILY_FOLDER)
    weekly_dir = os.path.join(TEMPORAL_MEMORIES_ROOT, TEMPORAL_WEEKLY_FOLDER)
    monthly_dir = os.path.join(TEMPORAL_MEMORIES_ROOT, TEMPORAL_MONTHLY_FOLDER)
    ensure_dir(TEMPORAL_MEMORIES_ROOT)
    ensure_dir(daily_dir)
    ensure_dir(weekly_dir)
    ensure_dir(monthly_dir)
    return daily_dir, weekly_dir, monthly_dir


def ensure_temporal_maintenance():
    """
    Generate weekly summaries for completed weeks and monthly summaries for completed months.
    Daily files are stored in daily/ subfolder; code checks/reads the most recent files by date.
    """
    if not TEMPORAL_MEMORIES_ROOT or not is_safe_temporal_path(TEMPORAL_MEMORIES_ROOT):
        return
    daily_dir, weekly_dir, monthly_dir = _ensure_temporal_dirs()

    now = datetime.date.today()
    cutoff_7 = now - datetime.timedelta(days=7)
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")

    # 1. Generate weekly summaries for completed weeks (daily files are in daily/ subfolder)
    weeks_done = set()
    try:
        for name in os.listdir(daily_dir) or []:
            if not date_re.match(name):
                continue
            path = os.path.join(daily_dir, name)
            if not os.path.isfile(path) or not is_safe_temporal_path(path):
                continue
            d = _parse_daily_filename(name)
            if d is None:
                continue
            y, w, _ = d.isocalendar()
            weeks_done.add((y, w))
    except Exception:
        weeks_done = set()

    for y, w in sorted(weeks_done):
        week_file = os.path.join(weekly_dir, f"{y}-W{w:02d}.md")
        if not is_safe_temporal_path(week_file):
            continue
        if os.path.isfile(week_file):
            continue
        summary = _generate_weekly_summary(y, w, daily_dir)
        if summary:
            try:
                with open(week_file, "w", encoding="utf-8") as f:
                    f.write(f"# Week {y}-W{w:02d}\n\n{summary}\n")
                log_memory_debug(f"Wrote weekly summary {y}-W{w:02d}.md")
            except Exception as e:
                log_memory_debug(f"⚠️ Failed to write weekly {y}-W{w:02d}: {e}")

    # 3. Keep only last month's worth of weekly summaries
    try:
        weekly_files = _get_sorted_weekly_files(weekly_dir, reverse=True)
        for y, w, path in weekly_files[5:]:
            try:
                os.remove(path)
                log_memory_debug(f"Pruned old weekly {y}-W{w:02d}.md")
            except Exception as e:
                log_memory_debug(f"⚠️ Failed to prune {path}: {e}")
    except Exception as e:
        log_memory_debug(f"⚠️ ensure_temporal_maintenance prune weekly: {e}")

    # 4. Generate monthly summary for previous month if missing
    try:
        this_year, this_month = now.year, now.month
        if this_month == 1:
            prev_year, prev_month = this_year - 1, 12
        else:
            prev_year, prev_month = this_year, this_month - 1
        month_file = os.path.join(monthly_dir, f"{prev_year}-{prev_month:02d}.md")
        if is_safe_temporal_path(month_file) and not os.path.isfile(month_file):
            summary = _generate_monthly_summary(
                prev_year, prev_month, weekly_dir, TEMPORAL_MEMORIES_ROOT
            )
            if summary:
                try:
                    with open(month_file, "w", encoding="utf-8") as f:
                        f.write(f"# Month {prev_year}-{prev_month:02d}\n\n{summary}\n")
                    log_memory_debug(
                        f"Wrote monthly summary {prev_year}-{prev_month:02d}.md"
                    )
                except Exception as e:
                    log_memory_debug(
                        f"⚠️ Failed to write monthly {prev_year}-{prev_month:02d}: {e}"
                    )
    except Exception as e:
        log_memory_debug(f"⚠️ ensure_temporal_maintenance monthly: {e}")


def gather_priority_reading_context(limit_chars_per_file=4000):
    """
    Read the priority reading list file and return combined content from those paths.
    Paths must be allowed (vault/temporal/preferences root) and exist as files.
    Returns (content_string, list_of_paths_used). Empty if list missing or no valid paths.
    """
    if not PRIORITY_READING_LIST_PATH or not is_safe_temporal_path(
        PRIORITY_READING_LIST_PATH
    ):
        return "", []
    if not os.path.isfile(PRIORITY_READING_LIST_PATH):
        return "", []
    try:
        with open(PRIORITY_READING_LIST_PATH, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return "", []
    paths = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        path = os.path.abspath(os.path.normpath(line))
        if not is_allowed_priority_path(path) or not os.path.isfile(path):
            continue
        paths.append(path)
    if not paths:
        return "", []
    parts = []
    for path in paths:
        content = safe_read_text(path, limit_chars=limit_chars_per_file)
        if not content or not content.strip():
            continue
        label = os.path.basename(path)
        if label.endswith(".md"):
            label = label[:-3]
        parts.append(f"### {label}\n\n{content.strip()}")
    if not parts:
        return "", []
    return "\n\n---\n\n".join(parts), paths


def gather_temporal_context_for_question(question):
    """
    Gather relevant temporal memory content for answering a question. First tries
    tag-based search across temporal memories and deductions; then includes last 7 days
    (daily files), last month's weekly summaries, and recent monthly summaries.
    Call ensure_temporal_maintenance() first so summaries are up to date.
    May expand context from file references when confidence is low.
    Returns a single string suitable as context for an LLM.
    """
    if not TEMPORAL_MEMORIES_ROOT or not is_safe_temporal_path(TEMPORAL_MEMORIES_ROOT):
        return "(No temporal memories available.)"
    daily_dir, weekly_dir, monthly_dir = _ensure_temporal_dirs()
    parts = []
    source_paths = []

    # 1. Tag-matched temporal/deduction entries (if question given and tag search available)
    if question and str(question).strip() and tag_search:
        tag_context = search_memories_by_tags(
            question, memory_types=["temporal", "deductions"], max_results=15
        )
        if tag_context and tag_context.strip():
            parts.append("### Tag-matched memories\n\n" + tag_context.strip())

    now = datetime.date.today()

    # 2. Last 7 days: daily files from daily/ subfolder
    if os.path.isdir(daily_dir):
        for i in range(7):
            d = now - datetime.timedelta(days=i)
            name = d.strftime("%Y-%m-%d") + ".md"
            path = os.path.join(daily_dir, name)
            if os.path.isfile(path) and is_safe_temporal_path(path):
                content = safe_read_text(path, limit_chars=4000)
                if content:
                    parts.append(f"### {name}\n\n{content.strip()}")
                    source_paths.append(path)

    # Last month: weekly summaries (up to 5 most recent)
    if os.path.isdir(weekly_dir):
        weekly_files = _get_sorted_weekly_files(weekly_dir, reverse=True)
        for y, w, path in weekly_files[:5]:
            content = safe_read_text(path, limit_chars=3000)
            if content:
                parts.append(f"### Week {y}-W{w:02d}\n\n{content.strip()}")
                source_paths.append(path)

    # Recent monthly summaries (up to 2)
    if os.path.isdir(monthly_dir):
        monthly_files = []
        for name in os.listdir(monthly_dir) or []:
            if not name.endswith(".md") or len(name) != 10:
                continue
            path = os.path.join(monthly_dir, name)
            if not is_safe_temporal_path(path):
                continue
            try:
                y, m = int(name[0:4]), int(name[5:7])
                monthly_files.append((y, m, path))
            except ValueError:
                continue
        monthly_files.sort(reverse=True)
        for y, m, path in monthly_files[:2]:
            content = safe_read_text(path, limit_chars=4000)
            if content:
                parts.append(f"### Month {y}-{m:02d}\n\n{content.strip()}")
                source_paths.append(path)

    # Priority reading list: always include these files in temporal context
    priority_content, priority_paths = gather_priority_reading_context(
        limit_chars_per_file=4000
    )
    if priority_content:
        parts.append("### Priority reading\n\n" + priority_content)
        source_paths.extend(priority_paths)

    if not parts:
        return "(No temporal memories found for the requested period.)"

    context_str = "\n\n---\n\n".join(parts)
    # Optional context expansion when confidence is low or evidence sparse
    try:
        import context_expander

        confidence = context_expander.calculate_context_confidence(
            context_str, question or ""
        )
        if context_expander.should_expand_context(
            confidence,
            len(source_paths),
            depth=0,
            max_depth=CONTEXT_EXPANSION_MAX_DEPTH,
            files_so_far=len(source_paths),
            max_files=CONTEXT_EXPANSION_MAX_FILES_PER_SESSION,
            confidence_threshold=CONTEXT_EXPANSION_CONFIDENCE_THRESHOLD,
            min_evidence_threshold=CONTEXT_EXPANSION_MIN_EVIDENCE_THRESHOLD,
        ):
            allowed_roots = [TEMPORAL_MEMORIES_ROOT, PREFERENCES_MEMORY_ROOT]
            expanded = context_expander.expand_from_evidence(
                context_str,
                source_paths,
                max_depth=CONTEXT_EXPANSION_MAX_DEPTH,
                max_files=CONTEXT_EXPANSION_MAX_FILES_PER_SESSION,
                max_bytes=CONTEXT_EXPANSION_MAX_BYTES_PER_SESSION,
                per_file_limit=10000,
                allowed_roots=allowed_roots,
            )
            if expanded.get("content"):
                parts.append("### Expanded Context\n\n" + expanded["content"])
                log_memory_debug(
                    f"[Context Expand] Temporal question: {expanded.get('depth', 0)} levels, "
                    f"{len(expanded.get('paths', []))} files"
                )
    except Exception as e:
        log_memory_debug(
            f"⚠️ Context expansion in gather_temporal_context_for_question: {e}"
        )
    return "\n\n---\n\n".join(parts)


def gather_semantic_temporal_context(topics, max_files=10, exclude_paths=None):
    """
    Use semantic index to find relevant temporal/diary/ideas files and return their content.
    Read-only: only reads from TEMPORAL_MEMORIES_ROOT and VAULT_ROOT. Never writes.
    Returns (content_string, file_paths_used).
    """
    try:
        import semantic_index
    except ImportError:
        log_memory_debug("⚠️ semantic_index module not found; no semantic context.")
        return "(No semantic index available.)", []

    exclude_paths = exclude_paths or set()
    if not topics:
        return "(No topics to search.)", []

    results = semantic_index.search_by_topics(
        topics, max_results=max_files, exclude_paths=exclude_paths
    )
    if not results:
        return "(No matching files in semantic index.)", []

    parts = []
    used_paths = []
    for path, _score in results:
        abs_path = os.path.normpath(os.path.abspath(path))
        if abs_path in exclude_paths:
            continue
        if not is_safe_temporal_path(abs_path):
            if abs_path != VAULT_ROOT and not abs_path.startswith(VAULT_ROOT + os.sep):
                continue
        if not os.path.isfile(abs_path):
            continue
        content = safe_read_text(abs_path, limit_chars=4000)
        if not content or not content.strip():
            continue
        label = os.path.basename(abs_path)
        if label.endswith(".md"):
            label = label[:-3]
        parts.append(f"### {label}\n\n{content.strip()}")
        used_paths.append(abs_path)

    if not parts:
        return "(No readable content from matched files.)", []
    return "\n\n---\n\n".join(parts), used_paths


def gather_temporal_last_week_only(days=7, weekly_summaries=1, limit_chars=8000):
    """
    Read-only: load last N days of daily temporal files plus the single most
    recent weekly summary. No tag search, no monthly summaries, no context
    expansion. Returns (content_string, source_paths).
    Content is prefixed with labels like [Temporal daily: YYYY-MM-DD] for deepseek.
    """
    if not TEMPORAL_MEMORIES_ROOT or not is_safe_temporal_path(TEMPORAL_MEMORIES_ROOT):
        return "", []
    daily_dir, weekly_dir, _ = _ensure_temporal_dirs()
    parts = []
    source_paths = []
    now = datetime.date.today()

    if os.path.isdir(daily_dir):
        for i in range(days):
            d = now - datetime.timedelta(days=i)
            name = d.strftime("%Y-%m-%d") + ".md"
            path = os.path.join(daily_dir, name)
            if os.path.isfile(path) and is_safe_temporal_path(path):
                content = safe_read_text(path, limit_chars=limit_chars)
                if content:
                    label = f"[Temporal daily: {d.isoformat()}]"
                    parts.append(f"{label}\n\n{content.strip()}")
                    source_paths.append(path)

    if weekly_summaries > 0 and os.path.isdir(weekly_dir):
        weekly_files = _get_sorted_weekly_files(weekly_dir, reverse=True)
        for y, w, path in weekly_files[:weekly_summaries]:
            content = safe_read_text(path, limit_chars=limit_chars)
            if content:
                label = f"[Temporal weekly: {y}-W{w:02d}]"
                parts.append(f"{label}\n\n{content.strip()}")
                source_paths.append(path)
                break

    combined = "\n\n---\n\n".join(parts) if parts else ""
    return combined, source_paths


def gather_observation_context(max_days=5):
    """
    Gather context for AI observation writing: recent daily temporal files +
    Information on Moi (user profile). No tag search; simpler than gather_temporal_context_for_question.
    May expand context from file references when context is sparse.
    Returns a string suitable for inclusion in the LLM prompt.
    """
    parts = []
    source_paths = []
    if TEMPORAL_MEMORIES_ROOT and is_safe_temporal_path(TEMPORAL_MEMORIES_ROOT):
        daily_dir = os.path.join(TEMPORAL_MEMORIES_ROOT, TEMPORAL_DAILY_FOLDER)
        if os.path.isdir(daily_dir):
            now = datetime.date.today()
            for i in range(max_days):
                d = now - datetime.timedelta(days=i)
                name = d.strftime("%Y-%m-%d") + ".md"
                path = os.path.join(daily_dir, name)
                if os.path.isfile(path) and is_safe_temporal_path(path):
                    content = safe_read_text(path, limit_chars=4000)
                    if content:
                        parts.append(
                            f"### Recent temporal: {name}\n\n{content.strip()}"
                        )
                        source_paths.append(path)
    if parts:
        temporal_block = "\n\n---\n\n".join(parts)
    else:
        temporal_block = "(No recent temporal memories.)"
    # Optional context expansion when context is sparse
    try:
        import context_expander

        if (
            len(parts) < CONTEXT_EXPANSION_MIN_EVIDENCE_THRESHOLD
            or context_expander.should_expand_context(
                context_expander.calculate_context_confidence(
                    temporal_block, "observation"
                ),
                len(source_paths),
                depth=0,
                max_depth=CONTEXT_EXPANSION_MAX_DEPTH,
                files_so_far=len(source_paths),
                max_files=CONTEXT_EXPANSION_MAX_FILES_PER_SESSION,
                confidence_threshold=CONTEXT_EXPANSION_CONFIDENCE_THRESHOLD,
                min_evidence_threshold=CONTEXT_EXPANSION_MIN_EVIDENCE_THRESHOLD,
            )
        ):
            allowed_roots = [TEMPORAL_MEMORIES_ROOT, PREFERENCES_MEMORY_ROOT]
            expanded = context_expander.expand_from_evidence(
                temporal_block,
                source_paths,
                max_depth=CONTEXT_EXPANSION_MAX_DEPTH,
                max_files=CONTEXT_EXPANSION_MAX_FILES_PER_SESSION,
                max_bytes=CONTEXT_EXPANSION_MAX_BYTES_PER_SESSION,
                per_file_limit=10000,
                allowed_roots=allowed_roots,
            )
            if expanded.get("content"):
                temporal_block += (
                    "\n\n---\n\n### Expanded Context\n\n" + expanded["content"]
                )
                log_memory_debug(
                    f"[Context Expand] Observation context: {expanded.get('depth', 0)} levels, "
                    f"{len(expanded.get('paths', []))} files"
                )
    except Exception as e:
        log_memory_debug(f"⚠️ Context expansion in gather_observation_context: {e}")
    pref_block = get_preferences_context("user profile and preferences")
    if pref_block and pref_block.strip():
        return f"{temporal_block}\n\n---\n\n{pref_block}"
    return temporal_block


# ==============================================================================
# API LAYER
# ==============================================================================


def _get_available_memory_mb():
    """Return available memory in MB, or None if unavailable."""
    try:
        import psutil

        mem = psutil.virtual_memory()
        return mem.available // (1024 * 1024)
    except ImportError:
        pass
    try:
        result = subprocess.run(
            ["vm_stat"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return None
        page_size = 4096
        free_pages = 0
        for line in result.stdout.splitlines():
            if line.strip().startswith("Pages free:"):
                free_pages = int(line.split(":")[1].strip().rstrip("."))
                break
        return (free_pages * page_size) // (1024 * 1024)
    except Exception:
        return None


def acquire_ollama_lock(
    timeout_seconds=None,
    skip_if_sufficient_memory=False,
    abort_check=None,
):
    """
    Acquire file-based lock for Ollama calls (serialize background memory LLM usage).
    Returns (lock_fd, True) on success; (None, False) on timeout; (None, "skip_lock") if
    skip_if_sufficient_memory and enough RAM free; (None, "abort") if abort_check returned True.
    Caller must call release_ollama_lock(lock_fd) when done (not when skip_lock or abort).
    Default timeout is OLLAMA_LOCK_TIMEOUT (must exceed longest observed call, ~2300s).
    """
    if timeout_seconds is None:
        timeout_seconds = OLLAMA_LOCK_TIMEOUT
    retry_interval = OLLAMA_LOCK_RETRY_INTERVAL
    min_free_mb = OLLAMA_LOCK_MIN_FREE_MEMORY_MB

    if skip_if_sufficient_memory:
        free_mb = _get_available_memory_mb()
        skip_threshold = getattr(types, "DIARY_CORRECTION_SKIP_LOCK_MIN_FREE_MB", 4096)
        if free_mb is not None and free_mb >= skip_threshold:
            log_debug(
                "[Ollama lock] Diary correction: sufficient memory ({}MB free), skipping lock.".format(
                    free_mb
                )
            )
            return None, "skip_lock"

    try:
        os.makedirs(os.path.dirname(OLLAMA_LOCK_FILE), exist_ok=True)
    except OSError:
        return None, False
    lock_fd = None
    try:
        lock_fd = open(OLLAMA_LOCK_FILE, "w")
        deadline = time.time() + timeout_seconds
        wait_start = time.time()
        abort_check_fn = abort_check
        if abort_check == "diary_correction":
            min_wait = getattr(types, "DIARY_CORRECTION_ABORT_WAIT_SECONDS", 600)
            low_mem_mb = getattr(types, "DIARY_CORRECTION_ABORT_LOW_MEM_MB", 2048)

            def _diary_abort_check():
                elapsed = time.time() - wait_start
                if elapsed < min_wait:
                    return False
                free = _get_available_memory_mb()
                return free is not None and free < low_mem_mb

            abort_check_fn = _diary_abort_check

        while time.time() < deadline:
            if abort_check_fn is not None and abort_check_fn():
                log_debug(
                    "[Ollama lock] Diary correction: abort after 10min wait + low memory."
                )
                if lock_fd:
                    lock_fd.close()
                return None, "abort"
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                waited = time.time() - wait_start
                if waited >= 5.0:
                    log_debug(
                        f"[Ollama lock] Acquired after {waited:.1f}s wait (contention)."
                    )
                return lock_fd, True
            except (OSError, BlockingIOError):
                time.sleep(retry_interval)
        if min_free_mb > 0:
            free_mb = _get_available_memory_mb()
            if free_mb is not None and free_mb < min_free_mb:
                log_debug(
                    f"⚠️ [Ollama lock] TIMEOUT; low memory ({free_mb}MB < {min_free_mb}MB); "
                    "refusing to proceed without lock."
                )
                if lock_fd:
                    lock_fd.close()
                raise OllamaLockRefusedError(
                    f"Low memory ({free_mb}MB < {min_free_mb}MB); aborting LLM call."
                )
        log_debug(
            f"⚠️ [Ollama lock] TIMEOUT after {timeout_seconds}s; proceeding without lock (risk of overload)."
        )
        log_debug(
            "[Ollama lock] Proceeding WITHOUT lock; another process may be using Ollama."
        )
        if lock_fd:
            lock_fd.close()
        return None, False
    except Exception as e:
        log_debug(f"⚠️ Ollama lock failed: {e}")
        if lock_fd:
            try:
                lock_fd.close()
            except Exception:
                pass
        return None, False


def release_ollama_lock(lock_fd):
    """Release file-based Ollama lock."""
    if lock_fd is None:
        return
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()
    except Exception as e:
        log_debug(f"⚠️ Ollama lock release: {e}")


# When set, every call_llm writes the prompt to this dir with filename from caller (e.g. ai_personality_reflection.reflect_and_update_personality.md).
CAPTURE_PROMPTS_DIR_ENV = "NOTE_ROUTER_CAPTURE_PROMPTS_DIR"
CAPTURE_PROMPTS_ENV = "NOTE_ROUTER_CAPTURE_PROMPTS"
DEFAULT_CAPTURE_PROMPTS_DIR = os.path.abspath(
    "/Users/caffae/Local Projects/AI Memories/Debug/Test Prompt"
)


def _snippet_for_audit(text, max_len=100):
    """One-line snippet for audit log: collapse newlines, truncate to max_len."""
    if not (text and text.strip()):
        return "(empty)"
    one = " ".join(text.split())
    one = one.strip()
    if len(one) <= max_len:
        return one
    return one[: max_len - 3].rstrip() + "..."


def _user_snippet_for_log(user_text, max_len=280):
    """One-line snippet of user payload for verbose log: collapse newlines, truncate."""
    if not (user_text and str(user_text).strip()):
        return "(empty)"
    one = " ".join(str(user_text).split())
    one = one.strip()
    if len(one) <= max_len:
        return one
    return one[: max_len - 3].rstrip() + "..."


def _log_verbose_only(message):
    """Append a single line to VERBOSE_LOG_PATH only (main.log). Same timestamp format as log_debug."""
    try:
        verbose_dir = os.path.dirname(VERBOSE_LOG_PATH)
        if not os.path.exists(verbose_dir):
            os.makedirs(verbose_dir, exist_ok=True)
        timestamp = f"[{_timestamp_short()}]"
        formatted = f"{timestamp} {message}\n"
        with open(VERBOSE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(formatted)
    except Exception as e:
        print(f"CRITICAL LOGGING FAIL: {e}")


def _caller_frame_for_capture():
    """Return the frame of the logical caller of call_llm (skip core and safety_core wrappers).
    If all frames are from this file or safety_core, returns the immediate caller of call_llm (frame at index 2)
    so the audit log always has a resolved module.function."""
    this_file = os.path.normpath(__file__)
    stack = inspect.stack()
    fallback = None
    for frame in stack:
        try:
            path = os.path.normpath(frame.filename)
        except Exception:
            continue
        if path == this_file:
            continue
        if "safety_core" in path and "note_router_core" not in path:
            continue
        return frame
    # Immediate caller of call_llm is at index 2 (0=this fn, 1=call_llm, 2=caller of call_llm)
    if len(stack) >= 3:
        fallback = stack[2]
    return fallback


def _write_captured_prompt(system, user, model, json_mode, caller_frame):
    """Write prompt to CAPTURE_PROMPTS_DIR with filename from calling function. No-op if dir not set."""
    if not os.environ.get(CAPTURE_PROMPTS_ENV):
        return
    out_dir = os.environ.get(CAPTURE_PROMPTS_DIR_ENV) or DEFAULT_CAPTURE_PROMPTS_DIR
    if not caller_frame:
        return
    try:
        os.makedirs(out_dir, exist_ok=True)
        module = os.path.splitext(os.path.basename(caller_frame.filename))[0]
        func = caller_frame.function or "unknown"
        safe = re.sub(r"[^\w.]", "_", f"{module}.{func}")
        path = os.path.join(out_dir, f"{safe}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Prompt capture\n\n")
            f.write(f"- **Caller:** `{module}.{func}`\n")
            f.write(f"- **Model:** `{model}`\n")
            f.write(f"- **json_mode:** `{json_mode}`\n\n")
            f.write("## System\n\n```\n")
            f.write(system.replace("```", "` ` `"))
            f.write("\n```\n\n## User\n\n```\n")
            f.write(user.replace("```", "` ` `"))
            f.write("\n```\n")
        log_debug(f"📝 Captured prompt → {path}")
    except Exception as e:
        log_debug(f"⚠️ Prompt capture failed: {e}")


def call_llm(system, user, model, json_mode=False, timeout=None):
    """
    Call LLM with optional custom timeout.

    Args:
        timeout: Request timeout in seconds. Defaults to OLLAMA_READ_TIMEOUT (900s).
                 Use higher values for long transcripts/documents.
    """
    start_time = time.time()
    mode_str = " [JSON MODE]" if json_mode else ""
    caller = _caller_frame_for_capture()
    module = (
        os.path.splitext(os.path.basename(caller.filename))[0] if caller else "unknown"
    )
    func = caller.function if caller else "unknown"
    payload_snippet = _snippet_for_audit((system or "") + "\n" + (user or ""))
    log_debug(
        f"🤖 API CALL START [{model}]{mode_str} | {module}.{func} | {payload_snippet}"
    )
    _log_verbose_only("  → user: " + _user_snippet_for_log(user))

    if os.environ.get(CAPTURE_PROMPTS_ENV) and caller:
        _write_captured_prompt(system, user, model, json_mode, caller)

    caller_info = f"{module}.{func}"
    try:
        lock_fd, locked = acquire_ollama_lock()
    except OllamaLockRefusedError:
        log_debug("[Ollama lock] Call aborted (low memory); LLM call skipped.")
        return None
    if locked:
        try:
            return _call_llm_impl(
                system, user, model, json_mode, start_time, caller_info, timeout
            )
        finally:
            release_ollama_lock(lock_fd)
    return _call_llm_impl(
        system, user, model, json_mode, start_time, caller_info, timeout
    )


def call_llm_diary_correction(system, user, model, json_mode=False):
    """
    Priority path for diary text correction: highest priority in task system.
    - If setting diary-correction-skip-ollama-lock is true (default), skip lock entirely.
    - Else: if sufficient free RAM, skip Ollama lock; max wait 10 min for lock; if waited that long AND RAM very full, return None (caller uses uncorrected).
    """
    start_time = time.time()
    caller_info = "correct_diary_text"
    if get_setting("diary-correction-skip-ollama-lock", True):
        log_debug("[Ollama lock] Diary correction: skip lock (setting enabled).")
        return _call_llm_impl(
            system, user, model, json_mode, start_time, caller_info, None
        )
    timeout = getattr(types, "DIARY_CORRECTION_ABORT_WAIT_SECONDS", 600)

    try:
        lock_fd, status = acquire_ollama_lock(
            timeout_seconds=timeout,
            skip_if_sufficient_memory=True,
            abort_check="diary_correction",
        )
    except OllamaLockRefusedError:
        log_debug("[Ollama lock] Diary correction aborted (low memory).")
        return None

    if status == "abort":
        log_debug(
            "[Diary correction] Abort: 10min wait + low memory; returning uncorrected."
        )
        return None

    if status == "skip_lock" or status is False:
        return _call_llm_impl(
            system, user, model, json_mode, start_time, caller_info, None
        )

    try:
        return _call_llm_impl(
            system, user, model, json_mode, start_time, caller_info, None
        )
    finally:
        release_ollama_lock(lock_fd)


def _call_llm_impl(
    system,
    user,
    model,
    json_mode=False,
    start_time=None,
    caller_info=None,
    timeout=None,
):
    if start_time is None:
        start_time = time.time()

    # Use custom timeout if provided, otherwise default
    request_timeout = timeout if timeout is not None else OLLAMA_READ_TIMEOUT

    headers = {"Content-Type": "application/json"}

    def _ollama_request(ollama_model):
        p = {
            "model": ollama_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0.1},
        }
        if json_mode:
            p["format"] = "json"
        res = requests.post(
            OLLAMA_URL, headers=headers, json=p, timeout=request_timeout
        )
        if res.status_code == 200:
            content = res.json()["message"]["content"]
            return clean_think_tags(content)
        return None

    # 1. Try Ollama with primary model
    primary_error = None
    try:
        content = _ollama_request(model)
        if content is not None:
            duration = round(time.time() - start_time, 2)
            log_debug(
                f"✅ Ollama Success [{model}] | {caller_info or 'unknown'} ({duration}s)"
            )
            return content
        log_debug(f"⚠️ Ollama Error: model {model} returned no content")
    except Exception as e:
        primary_error = str(e)
        elapsed = round(time.time() - start_time, 1)
        err_type = type(e).__name__
        hint = ""
        if "timed out" in primary_error.lower() or "timeout" in primary_error.lower():
            hint = f" Elapsed: {elapsed}s. Timeout is {request_timeout}s; consider increasing timeout or using a faster model."
        log_debug(
            f"❌ Ollama Connection Failed ({model}): [{err_type}] {primary_error}.{hint}"
        )

    # 2. For eligible models: try deepseek-r1:32b via Ollama, then abort (no LM Studio)
    fallback_error = None
    if SAFETY_ENABLED and model in MODELS_ELIGIBLE_FOR_FALLBACK:
        log_debug(f"🛡️ SAFETY FALLBACK: Trying {MODEL_FALLBACK_SAFETY}...")
        try:
            content = _ollama_request(MODEL_FALLBACK_SAFETY)
            if content is not None:
                duration = round(time.time() - start_time, 2)
                log_debug(
                    f"✅ Ollama Fallback Success [{MODEL_FALLBACK_SAFETY}] | {caller_info or 'unknown'} ({duration}s)"
                )
                return content
        except Exception as e:
            fallback_error = str(e)
            elapsed = round(time.time() - start_time, 1)
            err_type = type(e).__name__
            hint = ""
            if (
                "timed out" in fallback_error.lower()
                or "timeout" in fallback_error.lower()
            ):
                hint = f" Elapsed: {elapsed}s. Timeout is {request_timeout}s."
            log_debug(
                f"❌ Ollama Fallback Failed ({MODEL_FALLBACK_SAFETY}): [{err_type}] {fallback_error}.{hint}"
            )
        log_debug(
            f"🛡️ SAFETY: All models failed. Primary ({model}): {primary_error or 'no content'}. "
            f"Fallback ({MODEL_FALLBACK_SAFETY}): {fallback_error or 'no content'}. No changes done. See llm_router_audit.log"
        )
        _save_failed_prompt(
            system,
            user,
            model,
            MODEL_FALLBACK_SAFETY,
            primary_error,
            fallback_error,
            stream=False,
        )
        try:
            safety_line = (
                f"[{datetime.datetime.now().strftime('%m-%d %H:%M:%S')}] "
                f"[SAFETY] issue_detected: LLM operation failed (primary={model}, fallback={MODEL_FALLBACK_SAFETY}); no changes done.\n"
            )
            with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
                f.write(safety_line)
            verbose_dir = os.path.dirname(VERBOSE_LOG_PATH)
            if not os.path.exists(verbose_dir):
                os.makedirs(verbose_dir, exist_ok=True)
            with open(VERBOSE_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(safety_line)
        except Exception:
            pass
        return None

    # 3. For other models: fallback to LM Studio
    log_debug(f"🛡️ FALLBACK TRIGGERED: Switching to LM Studio ({MODEL_ALT})...")
    try:
        payload = {
            "model": MODEL_ALT,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0.1},
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        res = requests.post(LM_STUDIO_URL, headers=headers, json=payload, timeout=60)

        if res.status_code == 200:
            log_debug("✅ LM Studio Success")
            return res.json()["choices"][0]["message"]["content"]
        else:
            log_debug(f"⚠️ LM Studio Error: HTTP {res.status_code}")

    except Exception as e:
        log_debug(f"☠️ LM Studio Failed: {str(e)}")

    return None


def call_llm_stream(system, user, model, json_mode=False, show_thinking=False):
    """
    Stream LLM response token by token. Yields tuples of (chunk_type, content):
    - ("thinking", text) for thinking content (Ollama message.thinking or <think> tags)
    - ("response", text) for normal response tokens
    - ("done", full_text) when complete (full_text is response with thinking stripped)

    show_thinking: if False, thinking chunks are still yielded but caller may ignore;
    the "done" full_text is always clean (no <think> tags).
    """
    start_time = time.time()
    mode_str = " [JSON MODE]" if json_mode else ""
    log_debug(f"🤖 API CALL STREAM START [{model}]{mode_str}")
    _log_verbose_only("  → user: " + _user_snippet_for_log(user))

    lock_fd, locked = acquire_ollama_lock()
    if locked:
        try:
            for chunk in _call_llm_stream_impl(
                system, user, model, json_mode, start_time
            ):
                yield chunk
        finally:
            release_ollama_lock(lock_fd)
    else:
        for chunk in _call_llm_stream_impl(system, user, model, json_mode, start_time):
            yield chunk


def _call_llm_stream_impl(system, user, model, json_mode=False, start_time=None):
    if start_time is None:
        start_time = time.time()

    headers = {"Content-Type": "application/json"}
    full_content = []
    full_thinking = []

    def _ollama_stream(ollama_model):
        p = {
            "model": ollama_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": True,
            "options": {"temperature": 0.1},
        }
        if json_mode:
            p["format"] = "json"
        res = requests.post(
            OLLAMA_URL,
            headers=headers,
            json=p,
            timeout=OLLAMA_READ_TIMEOUT,
            stream=True,
        )
        if res.status_code != 200:
            return None
        buffer = ""
        in_think = False
        think_open = "<think>"
        think_close = "</think>"
        think_open_len = len(think_open)
        think_close_len = len(think_close)
        for line in res.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = data.get("message") or {}
            content = msg.get("content") or ""
            thinking = msg.get("thinking") or ""
            if thinking:
                full_thinking.append(thinking)
                yield ("thinking", thinking)
            if content:
                if (
                    not buffer
                    and "<think>" not in content
                    and "</think>" not in content
                ):
                    full_content.append(content)
                    yield ("response", content)
                else:
                    buffer += content
                    while buffer:
                        if not in_think:
                            idx = buffer.find(think_open)
                            if idx >= 0:
                                if idx > 0:
                                    part = buffer[:idx]
                                    full_content.append(part)
                                    yield ("response", part)
                                buffer = buffer[idx + think_open_len :]
                                in_think = True
                            else:
                                safe_len = max(0, len(buffer) - think_open_len)
                                if safe_len > 0:
                                    part = buffer[:safe_len]
                                    full_content.append(part)
                                    yield ("response", part)
                                    buffer = buffer[safe_len:]
                                break
                        else:
                            idx = buffer.find(think_close)
                            if idx >= 0:
                                think_part = buffer[:idx]
                                full_thinking.append(think_part)
                                yield ("thinking", think_part)
                                buffer = buffer[idx + think_close_len :]
                                in_think = False
                            else:
                                safe_len = max(0, len(buffer) - think_close_len)
                                if safe_len > 0:
                                    think_part = buffer[:safe_len]
                                    full_thinking.append(think_part)
                                    yield ("thinking", think_part)
                                    buffer = buffer[safe_len:]
                                break
            if data.get("done"):
                if buffer:
                    if in_think:
                        full_thinking.append(buffer)
                        yield ("thinking", buffer)
                    else:
                        full_content.append(buffer)
                        yield ("response", buffer)
                break
        response_text = "".join(full_content)
        duration = round(time.time() - start_time, 2)
        log_debug(f"✅ Ollama Stream Success ({duration}s)")
        yield ("done", clean_think_tags(response_text))

    primary_error = None
    try:
        last_done = None
        for chunk in _ollama_stream(model):
            if chunk[0] == "done":
                last_done = chunk[1]
            yield chunk
        if last_done is not None:
            return
    except Exception as e:
        primary_error = str(e)
        elapsed = round(time.time() - start_time, 1)
        err_type = type(e).__name__
        hint = ""
        if "timed out" in primary_error.lower() or "timeout" in primary_error.lower():
            hint = f" Elapsed: {elapsed}s. Timeout is {OLLAMA_READ_TIMEOUT}s; consider increasing OLLAMA_READ_TIMEOUT or using a faster model."
        log_debug(
            f"❌ Ollama Stream Failed ({model}): [{err_type}] {primary_error}.{hint}"
        )

    fallback_error = None
    if SAFETY_ENABLED and model in MODELS_ELIGIBLE_FOR_FALLBACK:
        log_debug(f"🛡️ SAFETY FALLBACK: Trying {MODEL_FALLBACK_SAFETY}...")
        try:
            for chunk in _ollama_stream(MODEL_FALLBACK_SAFETY):
                if chunk[0] == "done":
                    return
                yield chunk
        except Exception as e:
            fallback_error = str(e)
            elapsed = round(time.time() - start_time, 1)
            err_type = type(e).__name__
            hint = ""
            if (
                "timed out" in fallback_error.lower()
                or "timeout" in fallback_error.lower()
            ):
                hint = f" Elapsed: {elapsed}s. Timeout is {OLLAMA_READ_TIMEOUT}s."
            log_debug(
                f"❌ Ollama Fallback Failed ({MODEL_FALLBACK_SAFETY}): [{err_type}] {fallback_error}.{hint}"
            )
        log_debug(
            f"🛡️ SAFETY: All models failed (stream). Primary ({model}): {primary_error or 'no content'}. "
            f"Fallback ({MODEL_FALLBACK_SAFETY}): {fallback_error or 'no content'}. No changes done. See llm_router_audit.log"
        )
        _save_failed_prompt(
            system,
            user,
            model,
            MODEL_FALLBACK_SAFETY,
            primary_error,
            fallback_error,
            stream=True,
        )
        try:
            safety_line = (
                f"[{datetime.datetime.now().strftime('%m-%d %H:%M:%S')}] "
                f"[SAFETY] issue_detected: LLM stream failed (primary={model}, fallback={MODEL_FALLBACK_SAFETY}); no changes done.\n"
            )
            with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
                f.write(safety_line)
            verbose_dir = os.path.dirname(VERBOSE_LOG_PATH)
            if not os.path.exists(verbose_dir):
                os.makedirs(verbose_dir, exist_ok=True)
            with open(VERBOSE_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(safety_line)
        except Exception:
            pass
        yield ("done", None)
        return

    log_debug(f"🛡️ FALLBACK TRIGGERED: Switching to LM Studio ({MODEL_ALT})...")
    try:
        payload = {
            "model": MODEL_ALT,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0.1},
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        res = requests.post(LM_STUDIO_URL, headers=headers, json=payload, timeout=60)

        if res.status_code == 200:
            content = res.json()["choices"][0]["message"]["content"]
            log_debug("✅ LM Studio Success (non-stream)")
            yield ("done", clean_think_tags(content))
        else:
            log_debug(f"⚠️ LM Studio Error: HTTP {res.status_code}")
            yield ("done", None)

    except Exception as e:
        log_debug(f"☠️ LM Studio Failed: {str(e)}")
        yield ("done", None)


def parse_json(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except:
        pass
    try:
        match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    except:
        pass
    try:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start : end + 1])
    except:
        pass

    log_debug("🧱 JSON Parse Failed. Raw Text start: " + text[:50] + "...")
    return None


def _call_llm_and_parse_json(system, user, model, required_fields=None, default=None):
    """
    Call LLM in JSON mode, parse result, and validate required fields.

    Args:
        system: System prompt
        user: User prompt
        model: Model name
        required_fields: Optional list of required field names
        default: Default value to return on error

    Returns:
        Parsed JSON dict or default value
    """
    try:
        res = call_llm(system, user, model, json_mode=True)
        if not res or not res.strip():
            return default if default is not None else {}

        data = parse_json(res)
        if not isinstance(data, dict):
            return default if default is not None else {}

        if required_fields:
            for field in required_fields:
                if field not in data:
                    log_memory_debug(
                        f"⚠️ Missing required field '{field}' in LLM response"
                    )
                    return default if default is not None else {}

        return data
    except Exception as e:
        log_memory_debug(f"⚠️ LLM call failed: {e}")
        return default if default is not None else {}


# ==============================================================================
