"""
Huey task handlers for the note router queue.
Each task runs in the worker process and calls into memory/handlers.
"""

import concurrent.futures
import os
import re
import subprocess
import sys
from functools import wraps

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from prompt_loader import load_prompt

from . import handlers
from . import memory as _memory
from .butler_writes_cache import record_butler_write
from .memory import (
    call_llm,
    gather_information_on_moi_short,
    log_debug,
    log_memory_debug,
    write_ai_observation_to_temporal,
)
from .task_queue import huey
from .types import (
    DEDUCTION_HEARTBEAT_SCRIPT,
    MODEL_FAST,
    MODEL_MED,
    PYTHON_EXEC,
    get_setting,
    get_zettelkasten_tag_lists,
)

# --- Task Timeout Support ---
# Thread-safe timeout using ThreadPoolExecutor (works in Huey worker threads)


class TaskTimeout(Exception):
    """Raised when a task exceeds its time limit."""

    pass


def with_timeout(seconds):
    """
    Thread-safe timeout decorator using ThreadPoolExecutor.
    Works in any thread context (required for Huey worker threads).
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(func, *args, **kwargs)
                try:
                    return future.result(timeout=seconds)
                except concurrent.futures.TimeoutError:
                    raise TaskTimeout(f"Task exceeded {seconds}s time limit")

        return wrapper

    return decorator


# Task timeout constants (in seconds)
YOUTUBE_TASK_TIMEOUT = 1200  # 20 minutes (long transcripts need more time)


def log_youtube(message):
    """Log with [YouTube] prefix for filtering."""
    log_debug(f"[YouTube] {message}")


@huey.task(retries=3, retry_delay=10, priority=6)
def task_ai_observation(event_description, content=None):
    """AI observation to temporal memories (from handle_daily, handle_idea, etc.)."""
    try:
        write_ai_observation_to_temporal(
            "routing", event_description, content_for_summary=content
        )
        return f"✓ AI observation saved: {event_description[:50]}"
    except Exception as e:
        log_memory_debug(f"⚠️ AI observation failed: {e}")
        raise


@huey.task(retries=2, retry_delay=20, priority=5)
def task_context_aware_report_summary(
    op_type, original_text, path, source_datetime=None, event_description=""
):
    """
    Gather context from Information on Moi, send to LLM with prompt from prompts/,
    write diary entry. Output type (original improved / summary / one-liner-summary)
    is controlled by report-notes-save-to-diary-mode.
    """
    import datetime

    try:
        mode_str = (
            get_setting("zettel-notes-save-to-diary-mode")
            or get_setting("report-notes-save-to-diary-mode", "summary")
            if op_type == "use_zettel_script"
            else get_setting("report-notes-save-to-diary-mode", "summary")
        )
        diary_primary, _, report_also_mode = handlers._parse_diary_mode(mode_str)
        report_mode = (
            report_also_mode if diary_primary == "project-mention" else diary_primary
        )
        skip_diary_write = not report_mode
        if diary_primary == "project-mention" and not report_also_mode:
            if op_type == "use_zettel_script":
                main_chain = get_setting(
                    "zettel-notes-save-to-main-file"
                ) or get_setting("report-notes-save-to-main-file", "original")
            elif op_type == "use_experiment_log":
                main_chain = get_setting(
                    "experiment-notes-save-to-main-file"
                ) or get_setting("report-notes-save-to-main-file", "original")
            elif op_type == "use_dev_log":
                main_chain = get_setting(
                    "devlog-notes-save-to-main-file"
                ) or get_setting("report-notes-save-to-main-file", "original")
            else:
                main_chain = get_setting("report-notes-save-to-main-file", "original")
            main_chain = main_chain or ""
            if not any(
                t in main_chain.lower()
                for t in ("one-liner-summary", "summary", "context-boosted-text")
            ):
                return "✓ Context-aware report skipped (project-mention, main file original only)"

        if report_mode == "original":
            output_instruction = "rewrite this note to improve clarity. Strictly maintain the original perspective (use I, me, my). Output the full improved text."
        else:
            output_instruction = "produce a one-line summary that references the context where relevant. Use natural, plain English and avoid overly formal or academic phrasing. Return only the summarized text."

        context = gather_information_on_moi_short(limit_chars=5000)
        user_note = (original_text or "")[:4000]

        prompt = load_prompt(
            "04-report-context/01-context_aware_report",
            variables={
                "output_instruction": output_instruction,
                "context": context,
                "user_note": user_note,
            },
        )
        result = call_llm("", prompt, MODEL_MED, json_mode=False)
        if not result or not str(result).strip():
            if report_mode == "original":
                result = (original_text or "").strip() or "(no content)"
            else:
                result = (original_text or "")[:200].strip() or "(no summary)"
        else:
            result = str(result).strip()

        if not skip_diary_write and report_mode:
            if source_datetime and len(source_datetime) >= 2:
                date_str = (
                    handlers._note_date_from_datetime(source_datetime[2])
                    if len(source_datetime) > 2
                    else source_datetime[0]
                )
                time_12h = source_datetime[1]
            else:
                now = datetime.datetime.now()
                date_str = handlers._note_date_from_datetime(now)
                time_12h = handlers._format_time_12h(now)

            if op_type == "use_zettel_script":
                file_note = f"Zettel: {handlers.vault_relative_link(path)}"
            else:
                file_note = f"Updated {handlers.vault_relative_link(path)}"

            handlers._append_report_note_to_human_diary(
                report_mode, date_str, time_12h, file_note, result, project_path=path
            )

        if get_setting("summarize-logs-for-ai", False):
            write_ai_observation_to_temporal(
                "routing",
                event_description or "Report note",
                content_for_summary=result,
            )
        return f"✓ Context-aware report saved: {(event_description or '')[:50]}"
    except Exception as e:
        log_memory_debug(f"⚠️ Context-aware report summary failed: {e}")
        raise


@huey.task(retries=2, retry_delay=15, priority=7)
def task_preference_extract(content):
    """Extract preferences/attributes in background."""
    try:
        handlers.handle_memory(content)
        return "✓ Preferences extracted"
    except Exception as e:
        log_memory_debug(f"⚠️ Preference extraction failed: {e}")
        raise


@huey.task(retries=1, priority=6)
def task_deduction_increment():
    """Increment deduction counter."""
    try:
        handlers._increment_deduction_counter()
        return "✓ Deduction counter incremented"
    except Exception as e:
        log_memory_debug(f"⚠️ Deduction increment failed: {e}")
        raise


def _has_standalone_tag(text, tag):
    """True if tag appears as standalone (preceded by whitespace, start, or (). Word boundary after tag."""
    if not text or not tag:
        return False
    escaped = re.escape(tag)
    pat = r"(?:^|[\s(])" + escaped + r"\b"
    return bool(re.search(pat, text))


def _has_any_standalone_tag(text, tags):
    """True if any tag in tags appears as standalone in text."""
    return any(_has_standalone_tag(text, t) for t in tags)


def should_skip_analysis(cleaned_text):
    """
    Return (skip, run_breakdown, run_analysis).
    skip=True: do not run breakdown/analysis.
    run_breakdown/run_analysis: when skip=False, which parts to run.
    """
    breakdown_tags, analysis_tags = get_zettelkasten_tag_lists()
    has_bd = _has_any_standalone_tag(cleaned_text, breakdown_tags)
    has_kore = _has_any_standalone_tag(cleaned_text, analysis_tags)
    if has_bd or has_kore:
        return (False, has_bd, has_kore)

    text = (cleaned_text or "").strip()
    if not text:
        return (True, False, False)

    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    n_sentences = len(sentences)
    has_url = bool(re.search(r"https?://\S+", text))

    if n_sentences <= 1:
        return (True, False, False)
    if has_url and n_sentences < 2:
        return (True, False, False)

    return (False, True, True)


@huey.task(retries=2, retry_delay=20, priority=10)
def task_zettelkasten_cleanup(raw_content, file_path, original_content=None):
    """Clean raw text via pre-LLM (dictionary + mechanical) then LLM, update file, enqueue breakdown.
    When original_content is provided, only that portion is cleaned; header/summary preserved."""
    try:
        from .transcript_cleanup import code_based_cleanup, pre_llm_transcript_cleanup

        use_code_based = get_setting("code-based-text-cleaning", False)

        # Determine what to clean: only original portion if provided and present in body
        if (
            original_content
            and original_content.strip()
            and original_content in raw_content
        ):
            if use_code_based:
                cleaned_original = code_based_cleanup(
                    original_content
                ).strip() or pre_llm_transcript_cleanup(original_content)
                cleaned_text = raw_content.replace(
                    original_content, cleaned_original, 1
                )
            else:
                pre_cleaned = pre_llm_transcript_cleanup(original_content)
                llm_cleaned = call_llm(
                    load_prompt("12-voice-cleanup/01-cleanup_voice_transcript"),
                    pre_cleaned,
                    MODEL_FAST,
                )
                cleaned_original = (
                    handlers._strip_explanatory_paragraphs(
                        (llm_cleaned or pre_cleaned).strip() or pre_cleaned
                    )
                    or pre_cleaned
                )
                cleaned_text = raw_content.replace(
                    original_content, cleaned_original, 1
                )
        else:
            if use_code_based:
                cleaned_text = code_based_cleanup(raw_content)
                if not cleaned_text or not str(cleaned_text).strip():
                    cleaned_text = pre_llm_transcript_cleanup(raw_content)
            else:
                pre_cleaned = pre_llm_transcript_cleanup(raw_content)
                llm_cleaned = call_llm(
                    load_prompt("12-voice-cleanup/01-cleanup_voice_transcript"),
                    pre_cleaned,
                    MODEL_FAST,
                )
                cleaned_text = (
                    handlers._strip_explanatory_paragraphs((llm_cleaned or "").strip())
                    if llm_cleaned
                    else None
                )
                if not cleaned_text:
                    cleaned_text = pre_cleaned
        if not cleaned_text or not str(cleaned_text).strip():
            cleaned_text = raw_content
        handlers._zettel_update_file_content(file_path, cleaned_text)

        skip, run_breakdown, run_analysis = should_skip_analysis(cleaned_text)
        if skip:
            log_debug("[Zettel] Skipping breakdown/analysis (content too short)")
            return f"✓ Zettelkasten cleanup done; breakdown skipped for {file_path}"

        breakdown_only = run_breakdown and not run_analysis
        analysis_only = run_analysis and not run_breakdown
        task_zettelkasten_background(
            file_path,
            cleaned_text,
            breakdown_only=breakdown_only,
            analysis_only=analysis_only,
        )
        return f"✓ Zettelkasten cleanup done; breakdown enqueued for {file_path}"
    except Exception as e:
        log_memory_debug(f"⚠️ Zettelkasten cleanup failed: {e}")
        raise


@huey.task(retries=2, retry_delay=20, priority=2)
def task_zettelkasten_background(
    created_file_path,
    cleaned_text,
    breakdown_only=False,
    analysis_only=False,
):
    """Append Breakdown and/or Analysis to zettelkasten note."""
    try:
        handlers._append_zettelkasten_ai_sections(
            created_file_path,
            cleaned_text,
            breakdown_only=breakdown_only,
            analysis_only=analysis_only,
        )
        return f"✓ Zettelkasten AI sections added to {created_file_path}"
    except Exception as e:
        log_memory_debug(f"⚠️ Zettelkasten background processing failed: {e}")
        raise


@huey.task(retries=2, retry_delay=15, priority=9)
def task_diary_memory(content):
    """Process diary entries through AI memory system. Priority 9."""
    try:
        if not _memory.acquire_memory_lock(timeout=30):
            log_memory_debug(
                "⚠️ Failed to acquire memory lock, skipping diary memory processing"
            )
            return "✓ Diary memory skipped (lock)"
        try:
            _memory.process_diary_memory(content)
            return "✓ Diary memory processed"
        finally:
            _memory.release_memory_lock()
    except Exception as e:
        log_memory_debug(f"⚠️ Diary memory processing failed: {e}")
        raise


@huey.task(retries=1, retry_delay=60, priority=1)
def task_deduction_heartbeat():
    """Run deduction heartbeat (with idle check). Used when scheduled via --enqueue-only; revokable on force run."""
    try:
        script_dir = os.path.dirname(DEDUCTION_HEARTBEAT_SCRIPT)
        if not os.path.isfile(DEDUCTION_HEARTBEAT_SCRIPT):
            log_memory_debug("⚠️ Deduction heartbeat script not found; skipping.")
            return "✓ Deduction heartbeat skipped (script not found)"
        subprocess.run(
            [PYTHON_EXEC, DEDUCTION_HEARTBEAT_SCRIPT],
            cwd=script_dir,
            timeout=3600,
        )
        return "✓ Deduction heartbeat complete"
    except subprocess.TimeoutExpired:
        log_memory_debug("⚠️ Deduction heartbeat task timed out")
        raise
    except Exception as e:
        log_memory_debug(f"⚠️ Deduction heartbeat task failed: {e}")
        raise


@huey.task(retries=3, retry_delay=120, priority=8)
def task_youtube_reference(raw_transcript, uploader, title, video_id, url):
    """
    Process YouTube transcript: LLM cleanup, LLM summary, write Reference Note.
    Runs in background to avoid Ollama contention with heartbeat tasks.

    Timeout: 10 minutes (YOUTUBE_TASK_TIMEOUT) to prevent worker hangs.
    Uses retry_delay=120 to give Ollama time to recover between retries.
    """
    # Delegate to inner function with timeout protection
    try:
        return _youtube_reference_impl(raw_transcript, uploader, title, video_id, url)
    except TaskTimeout:
        log_youtube(
            f"❌ YouTube Reference task TIMED OUT after {YOUTUBE_TASK_TIMEOUT}s: {video_id}"
        )
        raise


@with_timeout(YOUTUBE_TASK_TIMEOUT)
def _youtube_reference_impl(raw_transcript, uploader, title, video_id, url):
    """Inner implementation with timeout protection."""
    import json
    import re

    # Import prompt_loader from parent directory
    import sys
    import unicodedata
    from datetime import datetime
    from pathlib import Path

    from .memory import call_llm, call_llm_stream

    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    from prompt_loader import load_prompt

    MODEL = "gemma3:27b"  # For summary generation
    MODEL_CLEANUP = "gemma3:12b"  # For transcript cleanup (faster, preserves words)
    MODEL_NAME_SHORTENER = "llama3.1:8b"
    MODEL_TITLE_SHORTENER = "gemma3:12b"
    REFERENCE_NOTES_DIR = Path(
        "/Users/caffae/Notes/ZettelPublish (Content Creator V2 April 2025)/02 Reference Notes"
    )
    SHORTCUT_PATH = Path(script_dir) / "References" / "youtuber_name_shortcut.json"
    AUDIT_LOG_PATH = Path.home() / "Desktop" / "llm_router_audit.log"

    # Chunking constants for long transcripts
    CHUNK_SIZE = 10000  # target chars per chunk (split at sentence boundary)
    CHUNK_MAX_SIZE = 15000  # hard max before forcing split
    STREAMING_THRESHOLD = 20000  # use streaming above this size

    # Filename constraints
    MAX_FILENAME_LEN = 150
    PREFIX_LEN = len("Reference - .md")  # 15 chars
    UPLOADER_THRESHOLD = 30  # Shorten uploader names longer than this

    def log_audit(message: str):
        """One-liner to audit log."""
        try:
            ts = datetime.now().strftime("%m-%d %H:%M:%S")
            with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] [YouTube] {message}\n")
        except Exception:
            pass

    def load_shortcuts() -> dict:
        """Load uploader name shortcuts from JSON."""
        if SHORTCUT_PATH.exists():
            try:
                with open(SHORTCUT_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_shortcuts(shortcuts: dict):
        """Save uploader name shortcuts to JSON."""
        SHORTCUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SHORTCUT_PATH, "w", encoding="utf-8") as f:
            json.dump(shortcuts, f, indent=2, ensure_ascii=False)

    def aggressive_sanitize(text: str) -> str:
        """Full sanitization: transliterate accents, strip emojis, normalize quotes."""
        if not text:
            return text
        # Normalize to NFD, remove combining characters (accents)
        text = unicodedata.normalize("NFD", text)
        text = "".join(c for c in text if unicodedata.category(c) != "Mn")
        # Normalize smart quotes to ASCII
        replacements = {
            "\u2018": "'",
            "\u2019": "'",
            "\u201c": '"',
            "\u201d": '"',
            "\u2013": "-",
            "\u2014": "-",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        # Remove emojis and other symbols (keep letters, numbers, punctuation, spaces)
        text = "".join(
            c
            for c in text
            if unicodedata.category(c)[0] in ("L", "N", "P", "Z") or c in "'-"
        )
        return text.strip()

    def cleanup_for_obsidian(name: str) -> str:
        """Title case unless acronym, remove invalid chars, transliterate."""
        name = aggressive_sanitize(name)
        # Remove invalid characters for Obsidian/filesystem
        name = re.sub(r'[/\\:*?"<>|]', "", name).strip()
        # Replace multiple spaces with single space
        name = re.sub(r"\s+", " ", name).strip()
        # Keep acronyms as-is (all caps, short)
        if name.isupper() and len(name) <= 6:
            return name
        return name.title()

    def get_short_uploader(uploader_name: str) -> str:
        """Get shortened uploader name (cached or LLM-generated)."""
        if len(uploader_name) <= UPLOADER_THRESHOLD:
            return uploader_name

        shortcuts = load_shortcuts()
        if uploader_name in shortcuts:
            log_youtube(f"  Using cached short name for: {uploader_name[:30]}")
            return shortcuts[uploader_name]

        # Generate with llama3.1:8b
        log_youtube(f"  → Generating short name for: {uploader_name[:40]}...")
        prompt = f"Shorten this YouTuber/channel name to under 25 characters while keeping it recognizable. Output ONLY the shortened name, nothing else:\n{uploader_name}"
        short = call_llm("", prompt, MODEL_NAME_SHORTENER)
        short = cleanup_for_obsidian(short.strip() if short else uploader_name[:25])

        # Ensure uniqueness among existing shortcuts
        existing = set(shortcuts.values())
        if short in existing:
            short = f"{short} ({uploader_name[:10]})"

        shortcuts[uploader_name] = short
        save_shortcuts(shortcuts)
        log_youtube(f"  ✓ Saved short name: {uploader_name[:30]} -> {short}")
        return short

    def sanitize_filename(text: str, max_len: int = 150) -> str:
        """Remove invalid characters for Obsidian/filesystem."""
        text = aggressive_sanitize(text)
        invalid_chars = r'[/\\:*?"<>|]'
        cleaned = re.sub(invalid_chars, "", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len].rsplit(" ", 1)[0]
        return cleaned

    def get_final_title(video_title: str, short_uploader: str) -> str:
        """Get title, shortened via LLM if too long for filename."""
        available = (
            MAX_FILENAME_LEN - PREFIX_LEN - len(short_uploader) - 1
        )  # -1 for space

        if len(video_title) <= available:
            return video_title

        # Generate concise title with gemma3:12b
        log_youtube(f"  → Title too long ({len(video_title)} chars), shortening...")
        prompt = f"Rewrite this YouTube video title as a concise factual description under {available} characters. Output ONLY the new title, nothing else:\n{video_title}"
        short_title = call_llm("", prompt, MODEL_TITLE_SHORTENER)

        if short_title:
            short_title = sanitize_filename(short_title.strip(), available)
            log_youtube(f"  ✓ Shortened title: {short_title[:50]}...")
            return short_title

        # Fallback: truncate original
        return video_title[:available].rsplit(" ", 1)[0]

    def demote_h2_to_h3(text: str) -> str:
        """Convert second-level headings (##) to third-level (###) to preserve document hierarchy."""
        if not text:
            return text
        # Match ## at start of line that is NOT already ### or deeper
        # Pattern: start of line, exactly two #, followed by space
        return re.sub(r"^(##)(?!#)", r"###", text, flags=re.MULTILINE)

    def chunk_transcript_at_sentences(text: str) -> list:
        """
        Split long transcript into chunks at sentence boundaries.

        Strategy:
        1. Target ~CHUNK_SIZE chars per chunk
        2. Always split at sentence end (. ! ? followed by space/newline)
        3. If no sentence boundary found within range, split at word boundary
        4. No overlap needed since we split at natural boundaries
        """
        if len(text) <= CHUNK_SIZE:
            return [text]

        # Sentence-ending pattern: . ! ? followed by space, newline, or end
        sentence_end_pattern = re.compile(r"[.!?](?=\s|$)")

        chunks = []
        start = 0

        while start < len(text):
            # If remaining text fits in one chunk, take it all
            if len(text) - start <= CHUNK_SIZE:
                chunks.append(text[start:].strip())
                break

            # Look for sentence boundary near target size
            search_start = start + int(
                CHUNK_SIZE * 0.7
            )  # Start looking at 70% of target
            search_end = min(start + CHUNK_MAX_SIZE, len(text))
            search_region = text[search_start:search_end]

            # Find sentence boundaries in search region
            matches = list(sentence_end_pattern.finditer(search_region))

            if matches:
                # Use the first sentence boundary found (closest to target)
                best_match = matches[0]
                split_pos = search_start + best_match.end()
            else:
                # No sentence boundary found, split at last space before max
                fallback_region = text[start : start + CHUNK_MAX_SIZE]
                last_space = fallback_region.rfind(" ")
                if last_space > CHUNK_SIZE * 0.5:  # Found reasonable split point
                    split_pos = start + last_space
                else:
                    # Force split at max (rare edge case)
                    split_pos = start + CHUNK_MAX_SIZE

            chunk = text[start:split_pos].strip()
            if chunk:
                chunks.append(chunk)
            start = split_pos

        return chunks

    def process_with_streaming(prompt: str, model: str) -> str:
        """Process LLM call with streaming for long content."""
        result_text = None
        for chunk_type, content in call_llm_stream("", prompt, model):
            if chunk_type == "done":
                result_text = content
                break
        return result_text

    log_youtube(f"🎬 YouTube Reference task started: {video_id}")
    log_youtube(f"  Title: {title[:60]}...")
    log_youtube(f"  Uploader: {uploader[:40]}...")
    log_youtube(f"  URL: {url}")
    log_youtube(f"  Transcript length: {len(raw_transcript)} chars")

    try:
        # Step 1: Clean transcript
        log_youtube(
            f"  [Step 1/3] Transcript cleanup started ({len(raw_transcript)} chars)"
        )

        # Decide processing strategy based on transcript length
        if len(raw_transcript) > CHUNK_SIZE:
            # Chunk processing for very long transcripts (sentence-boundary split)
            log_youtube(
                f"  → Chunking transcript ({len(raw_transcript)} chars > {CHUNK_SIZE})"
            )
            chunks = chunk_transcript_at_sentences(raw_transcript)
            log_youtube(f"  → Processing {len(chunks)} chunks...")
            cleaned_chunks = []
            for i, chunk in enumerate(chunks):
                log_youtube(
                    f"  → Cleaning chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)..."
                )
                cleanup_prompt = load_prompt(
                    "09-youtube-reference/01-transcript_cleanup",
                    {"transcript": chunk},
                )
                if len(chunk) > STREAMING_THRESHOLD:
                    cleaned = process_with_streaming(cleanup_prompt, MODEL_CLEANUP)
                else:
                    cleaned = call_llm("", cleanup_prompt, MODEL_CLEANUP)
                cleaned_chunks.append(cleaned if cleaned else chunk)
            cleaned_transcript = "\n\n".join(cleaned_chunks)
        elif len(raw_transcript) > STREAMING_THRESHOLD:
            # Streaming for medium-long transcripts
            log_youtube(
                f"  → Using streaming for cleanup ({len(raw_transcript)} chars)"
            )
            cleanup_prompt = load_prompt(
                "09-youtube-reference/01-transcript_cleanup",
                {"transcript": raw_transcript},
            )
            cleaned_transcript = process_with_streaming(cleanup_prompt, MODEL_CLEANUP)
        else:
            # Standard processing for shorter transcripts
            cleanup_prompt = load_prompt(
                "09-youtube-reference/01-transcript_cleanup",
                {"transcript": raw_transcript},
            )
            cleaned_transcript = call_llm("", cleanup_prompt, MODEL_CLEANUP)

        if not cleaned_transcript:
            log_youtube("⚠️ Transcript cleanup failed, using raw transcript")
            cleaned_transcript = raw_transcript
        else:
            log_youtube(f"  ✓ Cleanup complete: {len(cleaned_transcript)} chars")

        # Step 2: Generate summary
        log_youtube(
            f"  [Step 2/3] Summary generation started ({len(cleaned_transcript)} chars)"
        )
        summary_prompt = load_prompt(
            "09-youtube-reference/02-summary_notes",
            {"transcript": cleaned_transcript},
        )

        if len(cleaned_transcript) > STREAMING_THRESHOLD:
            log_youtube("  → Using streaming for summary")
            summary_notes = process_with_streaming(summary_prompt, MODEL)
        else:
            summary_notes = call_llm("", summary_prompt, MODEL)

        if not summary_notes:
            log_youtube("⚠️ Summary generation failed")
            summary_notes = "(Summary generation failed)"
        else:
            log_youtube(f"  ✓ Summary complete: {len(summary_notes)} chars")

        # Demote any ## headings to ### (preserve document hierarchy)
        cleaned_transcript = demote_h2_to_h3(cleaned_transcript)
        summary_notes = demote_h2_to_h3(summary_notes)

        # Step 3: Get short uploader name (if needed) and final title
        log_youtube("  [Step 3/3] Writing file...")
        short_uploader = get_short_uploader(uploader)
        safe_uploader = sanitize_filename(short_uploader, 50)
        final_title = get_final_title(title, safe_uploader)
        safe_title = sanitize_filename(final_title, 100)
        filename = f"Reference - {safe_uploader} {safe_title}.md"

        log_youtube(f"  Final filename: {filename[:60]}...")

        # Write file with source URL
        today = datetime.now().strftime("%Y-%m-%d")
        file_content = f"""---
date_created: {today}
---

> source:: {url}

## AI Summary
{summary_notes}

## Transcript
{cleaned_transcript}
"""

        output_path = REFERENCE_NOTES_DIR / filename
        REFERENCE_NOTES_DIR.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(file_content)

        record_butler_write(str(output_path))
        log_youtube(f"✅ YouTube Reference note created: {filename}")
        log_audit(f"✓ COMPLETE: {filename[:60]}")

        # macOS notification
        subprocess.run(
            [
                "osascript",
                "-e",
                'display notification "Reference note created" with title "YouTube Transcription Complete"',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        return f"✓ YouTube Reference note created: {filename}"

    except TaskTimeout:
        # Re-raise timeout to be handled by outer function
        raise
    except Exception as e:
        log_youtube(f"❌ YouTube Reference task failed: {e}")
        log_audit(f"❌ TASK FAILED: {title[:40]} - {str(e)[:30]}")
        raise
