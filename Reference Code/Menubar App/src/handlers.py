"""Handler functions: handle_daily, handle_experiment, handle_zettel, etc."""

import datetime
import os
import re
import subprocess
import sys
import time
import traceback

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from prompt_loader import load_prompt

from .butler_writes_cache import is_template_path, record_butler_write
from .llm_client import call_llm_structured
from .llm_models import TodoClassification
from .memory import *
from .routing_keywords_cache import apply_category_limits, match_keywords_in_content
from .transcript_cleanup import code_based_cleanup
from .types import *

# Daily note template (Checklist -> Tasks -> Log). Used when creating a new daily file.
_DAILY_NOTE_TEMPLATE = (
    "#Source/Journal\n\n"
    "## Checklist\n\n"
    "- [ ] Eat Metformin\n"
    "- [ ] Eat Jardiance\n"
    "- [ ] Sunscreen\n"
    "- [ ] Read something interesting\n\n"
    "## Tasks\n\n"
    "## Log"
)

# 4AM cutoff hour for "which day" the note belongs to
_DAILY_NOTE_4AM_CUTOFF_HOUR = 4

# Regex for Format A: 20260213 051206-....txt (YYYYMMDD space HHMMSS)
_FILENAME_DATETIME_PATTERN_A = re.compile(r"^(\d{8})\s*(\d{6})")
# Regex for Format B: VoiceMemo_2026-02-13_05-12-06.m4a (YYYY-MM-DD_HH-MM-SS)
_FILENAME_DATETIME_PATTERN_B = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})"
)


def _format_time_12h(dt):
    """Format datetime as 12h AM/PM, e.g. '5:12 AM'. Strips leading zero on hour."""
    s = dt.strftime("%I:%M %p")
    if s.startswith("0") and len(s) > 1 and s[1] != ":":
        s = s[1:]
    return s


def _note_date_from_datetime(dt):
    """Apply 4AM cutoff: if time < 4AM, return previous calendar day as YYYY-MM-DD."""
    if dt.hour < _DAILY_NOTE_4AM_CUTOFF_HOUR:
        d = dt.date() - datetime.timedelta(days=1)
    else:
        d = dt.date()
    return d.strftime("%Y-%m-%d")


BACKUP_JOURNAL_ROOT = "/Users/caffae/Backups/Backup Journal"


def append_to_backup_journal(text, source_datetime=None):
    """
    Append raw text to the Backup Journal (dated file, > HH:MM style). No routing.
    source_datetime: optional (date_str, time_12h, dt) e.g. from filename; else use now with 4AM cutoff.
    Swallows errors so main flow is unaffected.
    """
    if not text or not str(text).strip():
        return
    try:
        if source_datetime is not None and len(source_datetime) >= 3:
            _, time_12h, dt = source_datetime[0], source_datetime[1], source_datetime[2]
            date_str = _note_date_from_datetime(dt)
        else:
            now = datetime.datetime.now()
            date_str = _note_date_from_datetime(now)
            time_12h = _format_time_12h(now)
        path = os.path.join(BACKUP_JOURNAL_ROOT, f"{date_str}.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        block = f"\n\n> {time_12h}\n\n{text.strip()}\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(block)
    except Exception as e:
        log_debug(f"⚠️ Backup journal write failed: {e}")


def parse_source_datetime_from_filename(basename):
    """
    Parse date and time from voice-memo filename. Two formats supported:
    - Format A: 20260213 051206-E054C50E.txt (YYYYMMDD HHMMSS at start of name)
    - Format B: YYYY-MM-DD_HH-MM-SS anywhere in name, e.g. VoiceMemo_2026-02-13_05-12-06.m4a
      or VoiceMemo_2026-02-15_00-35-33.txt (any extension)
    Returns (date_str, time_12h_str, dt) or (None, None, None) when no match or invalid.
    """
    if not basename or not isinstance(basename, str):
        return (None, None, None)
    basename = basename.strip()

    # Format A: ^(\d{8})\s*(\d{6})
    m = _FILENAME_DATETIME_PATTERN_A.match(basename)
    if m:
        ymd, hms = m.group(1), m.group(2)
        try:
            y, mo, d = int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])
            h, mi, s = int(hms[:2]), int(hms[2:4]), int(hms[4:6])
            if (
                1 <= mo <= 12
                and 1 <= d <= 31
                and 0 <= h <= 23
                and 0 <= mi <= 59
                and 0 <= s <= 59
            ):
                dt = datetime.datetime(y, mo, d, h, mi, s)
                date_str = dt.strftime("%Y-%m-%d")
                return (date_str, _format_time_12h(dt), dt)
        except (ValueError, TypeError):
            pass
        return (None, None, None)

    # Format B: YYYY-MM-DD_HH-MM-SS anywhere in basename
    m = _FILENAME_DATETIME_PATTERN_B.search(basename)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        h, mi, s = int(m.group(4)), int(m.group(5)), int(m.group(6))
        try:
            if (
                1 <= mo <= 12
                and 1 <= d <= 31
                and 0 <= h <= 23
                and 0 <= mi <= 59
                and 0 <= s <= 59
            ):
                dt = datetime.datetime(y, mo, d, h, mi, s)
                date_str = dt.strftime("%Y-%m-%d")
                return (date_str, _format_time_12h(dt), dt)
        except (ValueError, TypeError):
            pass
        return (None, None, None)

    return (None, None, None)


def _get_daily_note_path_for_offset(day_offset: int):
    """
    Return (path, note_date) for the daily note at the given day offset.
    Uses 4AM cutoff: before 4AM counts as previous day for offset 0.
    day_offset=0 -> today's note (or yesterday's if before 4AM)
    day_offset=1 -> tomorrow's note
    """
    now = datetime.datetime.now()
    if now.hour < 4:
        base_date = now - datetime.timedelta(days=1)
    else:
        base_date = now
    note_date = base_date + datetime.timedelta(days=day_offset)
    path = os.path.join(DAILY_NOTE_DIR, f"{note_date.strftime('%Y-%m-%d')}.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path, note_date


def _get_daily_note_path(for_dt=None):
    """
    Return (path, now, note_date). If for_dt is provided (from parsed filename), apply 4AM cutoff
    to choose the note date. Else use current time with 4AM cutoff (before 4AM = previous day).
    note_date is a datetime.date-like (has .strftime) for the chosen day.
    """
    if for_dt is not None:
        note_date_str = _note_date_from_datetime(for_dt)
        path = os.path.join(DAILY_NOTE_DIR, f"{note_date_str}.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        note_date = (
            for_dt.date()
            if for_dt.hour >= _DAILY_NOTE_4AM_CUTOFF_HOUR
            else (for_dt.date() - datetime.timedelta(days=1))
        )
        return path, for_dt, note_date
    path, note_date = _get_daily_note_path_for_offset(0)
    return path, datetime.datetime.now(), note_date


def _ensure_daily_note_exists(path):
    """Create daily note file with template if it doesn't exist. No-op for template/excalidraw paths."""
    if not path or is_vault_path_protected(path):
        return
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(_DAILY_NOTE_TEMPLATE)


def vault_relative_link(abs_path):
    """Return diary-style link string: VaultName: [[path/in/vault]]."""
    try:
        if not abs_path:
            return "Unknown"
        rel = os.path.relpath(os.path.abspath(abs_path), VAULT_ROOT).replace("\\", "/")
        parts = rel.split("/", 1)
        vault_name = parts[0]
        path_in_vault = parts[1] if len(parts) > 1 else ""
        return f"{vault_name}: [[{path_in_vault}]]"
    except Exception:
        return "Unknown"


def _vault_display_name(vault_name):
    """Return user-facing vault name (e.g. Zettelkasten for ZettelPublish)."""
    return VAULT_DISPLAY_NAMES.get(vault_name, vault_name)


def vault_relative_link_display(abs_path):
    """Like vault_relative_link but uses display name for vault (e.g. Zettelkasten)."""
    try:
        if not abs_path:
            return "Unknown"
        rel = os.path.relpath(os.path.abspath(abs_path), VAULT_ROOT).replace("\\", "/")
        parts = rel.split("/", 1)
        vault_name = parts[0]
        path_in_vault = parts[1] if len(parts) > 1 else ""
        display = _vault_display_name(vault_name)
        return f"{display}: [[{path_in_vault}]]"
    except Exception:
        return "Unknown"


def _file_note_line_to_display(file_note_line):
    """Substitute vault name with display name in file_note_line (e.g. for declaration in Project Log)."""
    if not file_note_line:
        return file_note_line
    result = file_note_line
    for vault_name, display_name in VAULT_DISPLAY_NAMES.items():
        result = result.replace(vault_name, display_name)
    return result


# --- Group diary by project: section/block parsing and project key/label ---
_RE_PROJECT_LOG_HEADER = re.compile(
    r"^##\s+Project\s+Log\s*$", re.IGNORECASE | re.MULTILINE
)
_RE_LOG_HEADER = re.compile(r"^##\s+Log\s*$", re.IGNORECASE | re.MULTILINE)
_RE_TIMESTAMP_LINE = re.compile(
    r"^\s*>\s*\d{1,2}:\d{2}\s*[AP]M\s*$", re.IGNORECASE | re.MULTILINE
)
# Declaration: "> Updated Vault: [[path]]" or "> Zettel: Vault: [[path]]" (vault may be display name)
_RE_DECLARATION_LINE = re.compile(
    r"^\s*>\s*(?:Updated\s+)?(?:Zettel:\s+)?([^:]+):\s*\[\[([^\]]+)\]\]\s*$",
    re.MULTILINE,
)
_RE_ACTIVE_PROJECTS_HEADER = re.compile(
    r"^##\s+Active\s+Projects\s*$", re.IGNORECASE | re.MULTILINE
)
# Bullet in Active Projects: "- Short Vault Name: [[path]]"
_RE_ACTIVE_PROJECTS_BULLET = re.compile(
    r"^\s*-\s+[^:]+:\s*\[\[([^\]]+)\]\]\s*$", re.MULTILINE
)


def _path_in_vault_and_display(abs_path):
    """Return (path_in_vault, display_name) for Active Projects bullet. path_in_vault excludes vault folder."""
    try:
        if not abs_path:
            return ("", "Unknown")
        rel = (
            os.path.relpath(os.path.abspath(abs_path), VAULT_ROOT)
            .replace("\\", "/")
            .strip()
        )
        parts = rel.split("/", 1)
        path_in_vault = parts[1] if len(parts) > 1 else (parts[0] or "")
        vault_name = parts[0] if parts else ""
        display = _vault_display_name(vault_name) if vault_name else "Unknown"
        return (path_in_vault, display)
    except Exception:
        return ("", "Unknown")


def _split_daily_sections(content):
    """
    Split daily file content into: before_project_log, project_log_content (or None), log_content.
    Section headers matched with optional trailing space. Returns (before, project_log, log).
    """
    if not content:
        return ("", None, "")
    project_log_pos = _RE_PROJECT_LOG_HEADER.search(content)
    log_pos = _RE_LOG_HEADER.search(content)
    if log_pos is None:
        return (content.rstrip(), None, "")
    log_start = log_pos.start()
    log_header_len = log_pos.end() - log_start
    after_log = content[log_start + log_header_len :].lstrip("\n")
    before_log = content[:log_start].rstrip()
    if project_log_pos is None or project_log_pos.start() >= log_start:
        return (before_log, None, after_log)
    pl_start = project_log_pos.start()
    pl_header_len = project_log_pos.end() - pl_start
    before_pl = content[:pl_start].rstrip()
    project_log_content = content[pl_start + pl_header_len : log_start].lstrip("\n")
    return (before_pl, project_log_content, after_log)


def _parse_blocks_with_delimiters(section_content):
    """
    Split section content into blocks. Use \\n---\\n or timestamp line (> H:MM AM/PM) as block start.
    Returns list of block strings.
    """
    if not section_content or not section_content.strip():
        return []
    blocks = []
    parts = re.split(r"\n---+\s*\n", section_content)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        lines = part.split("\n")
        current_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and _RE_TIMESTAMP_LINE.match(stripped):
                if current_lines:
                    blocks.append("\n".join(current_lines))
                    current_lines = []
            current_lines.append(line)
        if current_lines:
            blocks.append("\n".join(current_lines))
    return blocks


def _declaration_line_from_block(block):
    """If block ends with a declaration line (> Vault: [[path]]), return (vault_prefix, path_in_vault); else None."""
    lines = block.strip().split("\n")
    if not lines:
        return None
    last = lines[-1].strip()
    if not last.startswith(">"):
        return None
    m = _RE_DECLARATION_LINE.match(last)
    if not m:
        return None
    return (m.group(1).strip(), m.group(2).strip())


def _project_key_from_abs_path(abs_path):
    """Normalized project key from absolute file path (for grouping)."""
    try:
        rel = (
            os.path.relpath(os.path.abspath(abs_path), VAULT_ROOT)
            .replace("\\", "/")
            .strip()
        )
        return rel
    except Exception:
        return ""


def _project_key_from_declaration_line(declaration_line):
    """
    Extract project key from a declaration line. Resolve display vault name to real vault.
    declaration_line is the full line e.g. "> Zettelkasten: [[07 Projects/Devlog/Smart Butler.md]]"
    """
    m = _RE_DECLARATION_LINE.match(declaration_line.strip())
    if not m:
        return None
    vault_part = m.group(1).strip()
    path_in_link = m.group(2).strip().replace("\\", "/")
    real_vault = VAULT_DISPLAY_NAMES_REVERSE.get(vault_part, vault_part)
    return f"{real_vault}/{path_in_link}"


def _project_label_from_path(abs_path):
    """Human-readable project label from path (e.g. Zettelkasten (Smart Butler) Devlog). Uses display name for vault."""
    try:
        rel = os.path.relpath(os.path.abspath(abs_path), VAULT_ROOT).replace("\\", "/")
        parts = rel.split("/")
        vault_name = parts[0] if parts else ""
        display = _vault_display_name(vault_name)
        stem = os.path.splitext(parts[-1] if parts else "")[0] if parts else ""
        parent = parts[-2] if len(parts) >= 2 else ""
        if parent == "Devlog":
            return f"{display} ({stem}) Devlog"
        if parent == "80 Experiment" or "Experiment" in rel:
            return f"{display} ({stem}) Experiment"
        return f"{display}: {stem or rel}"
    except Exception:
        return ""


def _read_merge_write_daily_note(
    path, build_new_content_fn, max_rounds=2, retries_per_round=6
):
    """
    Read daily file, build new content via build_new_content_fn(current_content), then write
    only if file was not modified since read. If modified: wait 10s, re-read, re-build, retry.
    Retries up to retries_per_round times, then notifies and runs another round. Then aborts.
    build_new_content_fn: (content: str) -> str
    Returns True if write succeeded, False if aborted after conflicts.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        log_debug(f"❌ _read_merge_write_daily_note: read error {path}: {e}")
        return False
    read_mtime = os.path.getmtime(path)
    new_content = build_new_content_fn(content)
    for round_no in range(max_rounds):
        for attempt in range(retries_per_round):
            try:
                current_mtime = os.path.getmtime(path)
                if current_mtime == read_mtime:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    return True
            except OSError as e:
                log_debug(f"❌ _read_merge_write_daily_note: write error {path}: {e}")
                return False
            log_debug(
                "📋 Daily note was modified while saving; waiting 10s then retrying..."
            )
            time.sleep(10)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except OSError as e:
                log_debug(f"❌ _read_merge_write_daily_note: re-read error {path}: {e}")
                return False
            read_mtime = os.path.getmtime(path)
            new_content = build_new_content_fn(content)
        log_debug(
            "📋 Daily note still modified after retries; notifying and running another round..."
        )
    log_debug(
        "❌ _read_merge_write_daily_note: aborted after conflicts (daily note modified while saving)"
    )
    return False


def _parse_project_log_to_entries(project_log_content):
    """
    Parse ## Project Log section into project_entries: dict project_key -> {"heading": "### ...", "declaration": "> ...", "blocks": [str, ...]}.
    Preserves user's ### heading. Blocks are stored without the declaration line (we emit declaration once).
    """
    project_entries = {}
    if not project_log_content or not project_log_content.strip():
        return project_entries
    sections = re.split(r"\n(?=###\s+)", project_log_content)
    for section in sections:
        section = section.strip()
        if not section or not section.startswith("###"):
            continue
        lines = section.split("\n")
        heading = lines[0].strip()
        rest = "\n".join(lines[1:]).strip()
        blocks = _parse_blocks_with_delimiters(rest)
        declaration = None
        project_key = None
        clean_blocks = []
        for block in blocks:
            decl = _declaration_line_from_block(block)
            if decl is not None and project_key is None:
                project_key = _project_key_from_declaration_line(
                    "> " + decl[0] + ": [[" + decl[1] + "]]"
                )
                if project_key is None:
                    project_key = (decl[0] + "/" + decl[1]).replace("\\", "/")
                declaration = block.strip().split("\n")[-1]
                body = "\n".join(block.strip().split("\n")[:-1]).strip()
                if body:
                    clean_blocks.append(body)
            elif decl is not None and project_key is not None:
                body = "\n".join(block.strip().split("\n")[:-1]).strip()
                if body:
                    clean_blocks.append(body)
            else:
                clean_blocks.append(block)
        if project_key:
            if project_key not in project_entries:
                project_entries[project_key] = {
                    "heading": heading,
                    "declaration": declaration or "",
                    "blocks": clean_blocks,
                }
            else:
                project_entries[project_key]["blocks"].extend(clean_blocks)
    return project_entries


def _parse_log_section_to_general_blocks(log_content):
    """Parse ## Log section into list of blocks (all are general / non-project)."""
    if not log_content or not log_content.strip():
        return []
    return _parse_blocks_with_delimiters(log_content)


def _rebuild_daily_content(before_project_log, project_entries, general_blocks):
    """Rebuild full daily file content from before_project_log, project_entries dict, and general_blocks list."""
    parts = [before_project_log.rstrip()]
    parts.append("\n\n## Project Log\n\n")
    for project_key, data in sorted(project_entries.items()):
        parts.append(data["heading"] + "\n\n")
        if data["declaration"]:
            decl = data["declaration"].strip()
            if not decl.startswith(">"):
                decl = "> " + decl
            parts.append(decl + "\n\n")
        for i, block in enumerate(data["blocks"]):
            if i > 0:
                parts.append("---\n")
            parts.append(block + "\n\n")
    parts.append("## Log\n\n")
    if general_blocks:
        for i, block in enumerate(general_blocks):
            if i > 0:
                parts.append("---\n")
            parts.append(block + "\n\n")
    return "".join(parts).rstrip() + "\n"


def _update_active_projects_section(before_pl, file_path):
    """
    If file_path is not already listed in ## Active Projects, add a bullet.
    Returns new before_pl content (with or without change). Bullet format: - Short Vault Name: [[path_in_vault]].
    """
    path_in_vault, display = _path_in_vault_and_display(file_path)
    if not path_in_vault:
        return before_pl
    bullet = f"- {display}: [[{path_in_vault}]]"
    norm = lambda p: (p or "").strip().replace("\\", "/")

    match = _RE_ACTIVE_PROJECTS_HEADER.search(before_pl)
    if not match:
        return before_pl.rstrip() + "\n\n## Active Projects\n\n" + bullet + "\n"

    start = match.start()
    end_header = match.end()
    next_hr = before_pl.find("\n## ", end_header)
    section_end = next_hr if next_hr != -1 else len(before_pl)
    body = before_pl[end_header:section_end].lstrip()
    tail = before_pl[section_end:].lstrip() if section_end < len(before_pl) else ""

    existing = set()
    for m in _RE_ACTIVE_PROJECTS_BULLET.finditer(body):
        existing.add(norm(m.group(1)))
    if norm(path_in_vault) in existing:
        return before_pl

    new_body = body.rstrip() + "\n" + bullet + "\n"
    head = before_pl[:start].rstrip()
    new_before_pl = head + "\n\n## Active Projects\n\n" + new_body
    if tail:
        new_before_pl += "\n" + tail
    return new_before_pl


def _append_active_projects_bullet_if_needed(for_date, file_path):
    """
    Ensure daily note has ## Active Projects and add a bullet for file_path if not already listed.
    for_date: YYYY-MM-DD or None for today (4AM cutoff). Uses read-merge-write; does not write report text.
    Writes to human diary (DAILY_NOTE_DIR = vault Journal/Journals), not AI temporal memories.
    """
    if for_date is not None:
        path_today = os.path.join(DAILY_NOTE_DIR, f"{for_date}.md")
        os.makedirs(os.path.dirname(path_today), exist_ok=True)
    else:
        path_today, _, _ = _get_daily_note_path()
    if is_vault_path_protected(path_today):
        log_debug(
            f"❌ Skip Active Projects: protected path (template/excalidraw) {path_today}"
        )
        return
    _ensure_daily_note_exists(path_today)

    def build_new_content(current_content):
        before_pl, _, log_content = _split_daily_sections(current_content)
        new_before_pl = _update_active_projects_section(before_pl, file_path)
        if new_before_pl == before_pl:
            return current_content
        general_blocks = _parse_log_section_to_general_blocks(log_content)
        # project-mention mode: never emit ## Project Log; only ## Active Projects and ## Log
        log_part = "\n\n## Log\n\n"
        if general_blocks:
            for i, block in enumerate(general_blocks):
                if i > 0:
                    log_part += "---\n"
                log_part += block + "\n\n"
        return new_before_pl.rstrip() + log_part.rstrip() + "\n"

    if _read_merge_write_daily_note(path_today, build_new_content):
        log_report_diary(
            f"Active Projects bullet saved -> {path_today} (project-mention)"
        )
    else:
        log_debug("❌ Active Projects save aborted (daily note conflict)")


def append_blockquote_to_human_diary(line, for_date=None):
    """Append a one-liner blockquote to the human diary (daily note). If for_date (YYYY-MM-DD) is set, use that day's note; else use today (4AM cutoff)."""
    if for_date is not None:
        path_today = os.path.join(DAILY_NOTE_DIR, f"{for_date}.md")
        os.makedirs(os.path.dirname(path_today), exist_ok=True)
    else:
        path_today, _, _ = _get_daily_note_path()
    if is_vault_path_protected(path_today):
        log_debug(
            f"❌ Skip diary write: protected path (template/excalidraw) {path_today}"
        )
        return
    _ensure_daily_note_exists(path_today)
    with open(path_today, "a", encoding="utf-8") as f:
        f.write(f"\n\n> {line}\n")
    log_debug(f"💾 Diary one-liner: > {line[:60]}...")


def _append_report_note_to_human_diary(
    mode, for_date, time_12h, file_note_line, body_text, project_path=None
):
    """
    Append a report-note diary entry (experiment/devlog/zettel) in the configured format.
    Writes to human diary (DAILY_NOTE_DIR = vault Journal/Journals), not AI temporal memories.
    mode: "original" | "summary" | "one-liner-summary"
    for_date: YYYY-MM-DD or None for today (4AM cutoff).
    time_12h: e.g. "5:12 AM"
    file_note_line: e.g. "Updated Vault: [[path]]" (used for original/summary block only).
    body_text: full original text (original), or one-line summary (summary / one-liner-summary).
    project_path: optional abs path for grouping when group-diary-by-project is true.
    Uses ReportDiary logging (prepend + emoji) for both main.log and llm_router_audit.log.
    """
    if for_date is not None:
        path_today = os.path.join(DAILY_NOTE_DIR, f"{for_date}.md")
        os.makedirs(os.path.dirname(path_today), exist_ok=True)
    else:
        path_today, _, _ = _get_daily_note_path()
    if is_vault_path_protected(path_today):
        log_debug(
            f"❌ Skip report note: protected path (template/excalidraw) {path_today}"
        )
        return
    _ensure_daily_note_exists(path_today)

    if get_setting("group-diary-by-project", False) and (
        project_path or file_note_line
    ):

        def build_new_content(current_content):
            before_pl, project_log_content, log_content = _split_daily_sections(
                current_content
            )
            project_entries = _parse_project_log_to_entries(project_log_content or "")
            general_blocks = _parse_log_section_to_general_blocks(log_content)
            project_key = (
                _project_key_from_abs_path(project_path) if project_path else None
            )
            if not project_key and file_note_line:
                line_for_parse = (
                    file_note_line
                    if file_note_line.strip().startswith(">")
                    else "> " + file_note_line.strip()
                )
                project_key = _project_key_from_declaration_line(line_for_parse)
            if not project_key:
                project_key = "unknown"
            declaration_display = _file_note_line_to_display(file_note_line)
            if mode == "one-liner-summary":
                new_block = f"- {time_12h} file updated - {body_text}\n"
            else:
                # Report notes: fixed format (diary-save-format applies only to direct diary entries)
                new_block = _format_diary_entry(
                    time_12h, body_text, "default", file_note_line
                )
            if project_key not in project_entries:
                label = (
                    _project_label_from_path(project_path)
                    if project_path
                    else project_key
                )
                project_entries[project_key] = {
                    "heading": "### " + label,
                    "declaration": declaration_display,
                    "blocks": [new_block],
                }
            else:
                project_entries[project_key]["blocks"].append(new_block)
            return _rebuild_daily_content(before_pl, project_entries, general_blocks)

        if _read_merge_write_daily_note(path_today, build_new_content):
            log_report_diary(f"Report note saved -> {path_today} ({mode}, grouped)")
        else:
            log_debug("❌ Report note save aborted (daily note conflict)")
        return

    if mode == "one-liner-summary":
        line = f"- {time_12h} file updated - {body_text}"
        with open(path_today, "a", encoding="utf-8") as f:
            f.write(f"\n\n{line}\n")
    else:
        # Report notes: fixed format (diary-save-format applies only to direct diary entries)
        formatted = _format_diary_entry(
            time_12h, body_text, "default", file_note_line
        )
        block = f"\n\n---\n{formatted}"
        with open(path_today, "a", encoding="utf-8") as f:
            f.write(block)
    log_report_diary(f"Report note saved -> {path_today} ({mode})")


# If summary is shorter than this fraction of original length, we use original text instead.
_SUMMARY_MIN_RATIO = 0.3


def _to_one_line_for_diary(text, max_chars=200):
    """Reduce text to a single line for diary one-liner: first sentence or truncate. Normalizes newlines to space."""
    if not text or not str(text).strip():
        return (text or "").strip()
    s = str(text).replace("\n", " ").strip()
    # First sentence (split on .  or ?  or !  followed by space or end)
    for sep in (". ", "? ", "! "):
        idx = s.find(sep)
        if idx != -1:
            first = s[: idx + 1].strip()
            if len(first) <= max_chars:
                return first
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 3].rstrip().rsplit(" ", 1)[0] + "..."


def _generate_fast_summary(content, op_type=None, style="full"):
    """
    When the router did not provide a summary, call a fast LLM to generate one.
    style: "full" = all main points, organized (01-user_perspective_diary); "one_line" = single sentence (09-one_line_report).
    op_type reserved for future per-type prompts (experiment vs devlog vs zettel).
    Returns summary string, or empty string on failure / when LLM output is significantly shorter
    than original (full style only; one_line has no min-length check).
    """
    if not content or not str(content).strip():
        return ""
    content_str = str(content).strip()
    content_len = len(content_str)
    try:
        if style == "one_line":
            user = load_prompt(
                "21-summary-variants/09-one_line_report",
                variables={"content": content_str},
            )
        else:
            user = load_prompt(
                "21-summary-variants/01-user_perspective_diary",
                variables={"content": content_str},
            )
        res = call_llm("", user, MODEL_STAGING, json_mode=False)
        out = (res or "").strip()
        if not out:
            return ""
        # For full summary only: if output is significantly shorter than original, treat as failed.
        if style != "one_line" and content_len > 0 and len(out) < _SUMMARY_MIN_RATIO * content_len:
            log_debug(
                f"⚠️ Fast summary too short ({len(out)} < {_SUMMARY_MIN_RATIO * content_len:.0f} chars), using original"
            )
            return ""
        return out
    except Exception as e:
        log_debug(f"⚠️ Fast summary failed: {e}")
        return ""


def _generate_one_line_summary(content, op_type=None):
    """Generate a single-sentence summary for one-liner-summary token. Returns one line or empty."""
    return _generate_fast_summary(content, op_type=op_type, style="one_line")


def _generate_context_boosted_text(content):
    """
    Rewrite content with context from Information on Moi for clarity.
    Retains all arguments/examples; does not summarize.
    Returns original content on failure.
    """
    if not content or not str(content).strip():
        return content or ""
    try:
        context = gather_information_on_moi_short(limit_chars=5000)
        user_note = (content or "")[:4000]
        prompt = load_prompt(
            "04-report-context/02-context_boosted_text",
            variables={"context": context, "user_note": user_note},
        )
        result = call_llm("", prompt, MODEL_MED, json_mode=False)
        if result and str(result).strip():
            return str(result).strip()
    except Exception as e:
        log_debug(f"⚠️ Context-boosted text failed: {e}")
    return content


def _build_main_file_content_from_chain(
    mode_chain, time_12h, content, summary=None, op_type=None
):
    """
    Parse report-notes-save-to-main-file (e.g. "one-liner-summary,original")
    and return concatenated content for the main file.
    Tokens: original, summary, one-liner-summary, context-boosted-text.
    summary = full summary (all points); one-liner-summary = single sentence. Each uses its own prompt when generated.
    Router-provided summary is treated as full summary; one-liner is always generated when needed.
    Fallback: return content if chain invalid or result empty/short.
    """
    if not content or not str(content).strip():
        return content or "", None
    chain = (mode_chain or "").strip()
    if not chain:
        return content, None
    try:
        tokens = [
            t.strip().lower() for t in chain.replace(" ", ",").split(",") if t.strip()
        ]
    except Exception:
        return content, None
    valid = {"original", "summary", "one-liner-summary", "context-boosted-text"}
    parts = []
    content_len = len(content.strip()) if content else 0
    need_full = "summary" in tokens
    need_one_liner = "one-liner-summary" in tokens
    # Full summary: router-provided or generate with full-summary prompt
    summary_val = (summary or "").strip()
    if need_full and not summary_val:
        summary_val = _generate_fast_summary(content, op_type, style="full")
    if not summary_val:
        summary_val = content
    if need_full and content_len > 0 and summary_val and len(summary_val) < _SUMMARY_MIN_RATIO * content_len:
        summary_val = content
    # One-liner: always generated with one-line prompt when token present
    one_liner_val = None
    if need_one_liner:
        one_liner_val = _generate_one_line_summary(content, op_type)
        if not one_liner_val or not one_liner_val.strip():
            # Fallback: first sentence of full summary or truncate
            first_sentence = (summary_val or "").split(". ")[0].strip()
            if first_sentence and len(first_sentence) <= 300:
                one_liner_val = first_sentence + ("." if not first_sentence.endswith(".") else "")
            else:
                one_liner_val = (summary_val or content or "")[:200].rstrip()
                if len((summary_val or content or "")) > 200:
                    one_liner_val = one_liner_val.rsplit(" ", 1)[0] + "..."
    for t in tokens:
        if t not in valid:
            continue
        if t == "original":
            parts.append(content)
        elif t == "summary":
            parts.append(summary_val)
        elif t == "one-liner-summary":
            parts.append(f"**{time_12h}** {one_liner_val or summary_val}")
        elif t == "context-boosted-text":
            boosted = _generate_context_boosted_text(content)
            parts.append(boosted)
    if not parts:
        return content, None
    body = "\n\n".join(parts)
    if not body or len(body.strip()) < 10:
        return content, None
    one_liner_for_diary = (one_liner_val or "").strip() or None if need_one_liner else None
    return body, one_liner_for_diary


def _classify_todo_timing_and_type(content: str) -> dict:
    """
    Extract and classify todos from content by timing (today/tomorrow/someday) and type (task vs principle).
    Returns dict with keys: today, tomorrow, someday, principles.
    Each value is list of (text, is_done) tuples.
    Uses 2AM threshold: before 2AM, time-sensitive tasks may be classified as tomorrow.

    IMPORTANT: content must be the current user input only (e.g. the note being saved). Never pass
    the whole diary file or any other long context, or the LLM may re-extract old/removed todos.
    """
    empty_result = {"today": [], "tomorrow": [], "someday": [], "principles": []}
    if not content or not content.strip():
        return empty_result
    text = content.strip().lower()
    todo_phrases = (
        "remind me",
        "i need to",
        "don't forget",
        "don't forget to",
        "todo:",
        "to do:",
        "to-do:",
        "task:",
        "must ",
        "have to ",
        "need to ",
        "i should ",
    )
    has_todo = any(p in text for p in todo_phrases) or re.search(
        r"\b(to[- ]?do|todo)s?\b", text, re.IGNORECASE
    )
    if not has_todo:
        return empty_result

    now = datetime.datetime.now()
    current_time_str = now.strftime("%Y-%m-%d %A %H:%M")
    time_instructions = (
        f"CURRENT TIME: {current_time_str}. "
        f"Before {TODO_ROUTING_HOUR_THRESHOLD}:00 AM, treat 'today' tasks that require daylight/working hours as tomorrow. "
        f"After {TODO_ROUTING_HOUR_THRESHOLD}:00 AM, 'today' means the current calendar day."
    )

    system = (
        "You classify todos and tasks into four categories. Return valid JSON only.\n\n"
        f"DECISION FRAMEWORK - {time_instructions}\n\n"
        "Categories:\n"
        "- today: do today (immediate, or any time today if after 2AM)\n"
        "- tomorrow: explicitly 'tomorrow', or time-sensitive (e.g. call during working hours, when they open) that cannot be done today given current time\n"
        "- someday: indefinite future, no specific date (e.g. 'check out X tool', 'try that restaurant')\n"
        "- principles: habits, guidelines, rules to follow (e.g. 'stop using hot water so long', 'use toilet for no more than two hours')\n"
        'Output format: {"today": [{"text": "task", "done": false}], "tomorrow": [], "someday": [], "principles": []}\n'
        "One user intention = one item. Do NOT split a single thought. Use done:true only if task is ALREADY COMPLETED.\n"
        "Examples: 'finish eating muffins' -> today; 'call polyclinic tomorrow' -> tomorrow; 'call during working hours' at 11PM -> tomorrow; "
        "'check out Google Anti-gravity AI tool' -> someday; 'stop using hot water heater so long' -> principles."
    )
    # Only the current input is sent; never the whole diary or other files
    user = f"Content to classify:\n{content[:4000]}"

    try:
        todos = call_llm_structured(
            system=system,
            user=user,
            model=MODEL_MED,
            response_model=TodoClassification,
            max_retries=2,
        )
        no_task = ("no tasks", "no task", "nothing", "none", "n/a")

        def to_tuples(items):
            out = []
            for item in items:
                t = (item.text or "").strip()
                if not t:
                    continue
                if t.lower() in no_task or any(p in t.lower() for p in no_task):
                    continue
                out.append((t, item.done))
            return out

        return {
            "today": to_tuples(todos.today),
            "tomorrow": to_tuples(todos.tomorrow),
            "someday": to_tuples(todos.someday),
            "principles": to_tuples(todos.principles),
        }
    except Exception as e:
        log_debug(f"⚠️ Todo classification failed: {e}")
        return empty_result


def _parse_diary_mode(mode_str):
    """
    Parse report-notes-save-to-diary-mode string.
    Returns (primary_mode, include_todos, report_also_mode).
    primary_mode: "project-mention" | "original" | "summary" | "one-liner-summary".
    include_todos: True only if the mode string explicitly includes "todos" and is not project-mention.
    report_also_mode: When primary is "project-mention" and a report format is chained (e.g. one-liner-summary),
        this is that format so both Active Projects bullet and report text are written; else None.
    project-mention => include_todos is always False; report text only if report_also_mode is set.
    """
    if not mode_str or not str(mode_str).strip():
        return ("original", False, None)
    raw = str(mode_str).strip().lower()
    tokens = [t.strip() for t in raw.replace(" ", ",").split(",") if t.strip()]
    include_todos = "todos" in tokens and "project-mention" not in raw
    if "project-mention" in raw:
        report_also = None
        for t in ("one-liner-summary", "summary", "original"):
            if t in tokens:
                report_also = t
                break
        return ("project-mention", False, report_also)
    primary = "original"
    for t in ("one-liner-summary", "summary", "original"):
        if t in tokens:
            primary = t
            break
    return (primary, include_todos, None)


def _main_chain_includes_todos(chain_str):
    """True if report-notes-save-to-main-file chain contains the 'todos' token."""
    if not chain_str or not str(chain_str).strip():
        return False
    tokens = [
        t.strip().lower()
        for t in str(chain_str).replace(" ", ",").split(",")
        if t.strip()
    ]
    return "todos" in tokens


def _format_todos_for_project_file(todo_items):
    """Format today's todo list for appending to a project file (devlog/experiment/zettel)."""
    if not todo_items:
        return ""
    lines = []
    for text, is_done in todo_items:
        prefix = "- [x] " if is_done else "- [ ] "
        lines.append(prefix + (text or "").strip())
    if not lines:
        return ""
    return "\n\n### Tasks\n\n" + "\n".join(lines)


def _has_entries_under_heading(existing_content, today_header):
    """Return True if today_header exists and has non-empty content after it."""
    if not existing_content or not today_header:
        return False
    idx = existing_content.find(today_header)
    if idx < 0:
        return False
    after = existing_content[idx + len(today_header) :].strip()
    return bool(after and len(after) > 2)


def _format_entry_body_for_save_format(body, time_12h, save_format):
    """
    Transform body based on *-notes-save-format. Returns formatted string.
    save_format: simple | divider | timestamp | bullet-list
    """
    if save_format == "simple" or save_format == "divider":
        return body
    if save_format == "timestamp":
        return f"> {time_12h}\n\n{body}"
    if save_format == "bullet-list":
        lines = (body or "").strip().split("\n")
        if not lines:
            return f"- **{time_12h}**\n"
        first = lines[0].strip()
        rest = [ln.strip() for ln in lines[1:] if ln.strip()]
        if not rest:
            return f"- **{time_12h}** {first}" if first else f"- **{time_12h}**\n"
        indent = "    "
        rest_block = "\n".join(indent + ln for ln in rest)
        return f"- **{time_12h}** {first}\n{rest_block}"
    return body


def _format_diary_entry(timestamp_str, content, save_format, file_note_line=None):
    """
    Format a diary entry for blockquote (default) or bullet-list.
    save_format: default | bullet-list.
    """
    content = (content or "").strip()
    file_suffix = (
        f"\n\n> {_file_note_line_to_display(file_note_line)}"
        if file_note_line
        else ""
    )
    if save_format == "bullet-list":
        lines = content.split("\n")
        if not lines:
            return f"- **{timestamp_str}**{file_suffix}\n"
        first = lines[0].strip()
        rest = [ln.strip() for ln in lines[1:] if ln.strip()]
        if not rest:
            return f"- **{timestamp_str}** {first}{file_suffix}\n" if first else f"- **{timestamp_str}**{file_suffix}\n"
        indent = "    "
        rest_block = "\n".join(indent + ln for ln in rest)
        return f"- **{timestamp_str}** {first}\n{rest_block}{file_suffix}\n"
    return f"> {timestamp_str}\n\n{content}{file_suffix}\n"


def _parse_save_format_tokens(save_format):
    """Parse *-notes-save-format string into tokens. Returns set of lowercase tokens."""
    if not save_format or not str(save_format).strip():
        return set()
    raw = str(save_format).strip().lower()
    return {
        t.strip()
        for t in raw.replace(" ", ",").split(",")
        if t.strip() in ("simple", "divider", "timestamp", "bullet-list")
    }


def _append_to_main_file_with_format(
    path, today_header, main_file_body, save_format, time_12h
):
    """
    Append main_file_body to path under today_header.
    save_format: simple | divider | timestamp | bullet-list, or chained (e.g. divider, timestamp).
    Divider (---) is added only when "divider" is explicitly in the chain and there are multiple entries.
    """
    tokens = _parse_save_format_tokens(save_format)
    body_format = (
        "timestamp"
        if "timestamp" in tokens
        else "bullet-list"
        if "bullet-list" in tokens
        else "simple"
    )
    with open(path, "r", encoding="utf-8") as f:
        existing = f.read()
    prefix = "\n\n" if today_header in existing else f"\n\n{today_header}\n\n"
    body = _format_entry_body_for_save_format(main_file_body, time_12h, body_format)
    needs_divider = (
        "divider" in tokens and _has_entries_under_heading(existing, today_header)
    )
    to_write = prefix + ("---\n" if needs_divider else "") + body
    with open(path, "a", encoding="utf-8") as f:
        f.write(to_write)


def _route_classified_todos(
    classified,
    diary_block_context=None,
    daily_note_content=None,
    send_today_to_daily=True,
):
    """
    Route classified todos to appropriate destinations:
    - today -> today's daily note (if send_today_to_daily): in the same diary time block as the entry
      when consolidate-todos-in-task-section is false, else in ## Tasks when true.
    - tomorrow -> tomorrow's daily note Tasks section
    - someday -> Apple Note "Someday Tasks"
    - principles -> Apple Note "Principles & Habits"

    diary_block_context: (path_today, timestamp_str) when we just wrote a diary block; used to insert
      todos into that block when consolidate-todos-in-task-section is false.
    daily_note_content: when set, Tasks-section write uses this instead of re-reading.
    send_today_to_daily: if False, today's todos are not written to the daily file (e.g. they went to project file).
    """
    if send_today_to_daily and classified.get("today"):
        path_today, _, _ = _get_daily_note_path()
        _ensure_daily_note_exists(path_today)
        # false = same input time block as the diary entry we just wrote; true = ## Tasks section
        if diary_block_context is not None and not get_setting(
            "consolidate-todos-in-task-section", False
        ):
            path, timestamp_str = diary_block_context
            _insert_todos_into_diary_block(path, timestamp_str, classified["today"])
        else:
            _append_todos_to_daily_tasks_section(
                path_today, classified["today"], content=daily_note_content
            )

    # Tomorrow tasks -> tomorrow's daily note Tasks section
    if classified.get("tomorrow"):
        path_tomorrow, _ = _get_daily_note_path_for_offset(1)
        _ensure_daily_note_exists(path_tomorrow)
        _append_todos_to_daily_tasks_section(path_tomorrow, classified["tomorrow"])

    # Someday tasks -> Apple Note "Someday Tasks"
    for task_text, _ in classified.get("someday") or []:
        append_to_apple_note(APPLE_NOTE_SOMEDAY_TASKS, task_text)

    # Principles -> Apple Note "Principles & Habits"
    for task_text, _ in classified.get("principles") or []:
        append_to_apple_note(APPLE_NOTE_PRINCIPLES, task_text)


def _extract_todos_from_content(content):
    """Extract today's todos only. Used by process_todos_into_daily_note. Returns list of (text, is_done) tuples."""
    classified = _classify_todo_timing_and_type(content)
    return classified.get("today", [])


def _normalize_timestamp_for_match(s):
    """Normalize timestamp string for flexible block matching (handles '2:30PM' vs '2:30 PM')."""
    if not s:
        return ""
    return re.sub(r"\s+", "", s.strip().lower())


def _insert_todos_into_diary_block(path, timestamp_str, todo_items):
    """
    Insert today's todos at end of the diary block that starts with > {timestamp_str}.
    Block is delimited by ---. Uses flexible timestamp matching.
    Falls back to _append_todos_to_daily_tasks_section if block cannot be found.
    """
    if not todo_items:
        return
    if is_vault_path_protected(path):
        log_debug(
            f"❌ Skip consolidate todos: protected path (template/excalidraw) {path}"
        )
        return
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    def fmt(t):
        return "- [X] " + t[0] if t[1] else "- [ ] " + t[0]

    new_todos_str = "\n".join(fmt(t) for t in todo_items)
    target_norm = _normalize_timestamp_for_match(timestamp_str)

    # Split into blocks by --- (keep separators to reconstruct)
    blocks = re.split(r"(\n---\n)", content)
    # blocks: [preamble, "\n---\n", block1_content, "\n---\n", block2_content, ...]
    if len(blocks) < 2:
        log_debug(
            "📋 consolidate-todos: no --- blocks found, falling back to Tasks section"
        )
        _append_todos_to_daily_tasks_section(path, todo_items)
        return

    # Find block whose first line matches > {timestamp} or - **{timestamp}**
    insertion_block_idx = None
    for i in range(1, len(blocks), 2):
        if i + 1 >= len(blocks):
            break
        block_content = blocks[i + 1]
        first_line = block_content.split("\n")[0].strip()
        block_timestamp = None
        if first_line.startswith(">"):
            block_timestamp = first_line[1:].strip()
        elif first_line.startswith("- **") and "**" in first_line[4:]:
            m = re.match(r"-\s*\*\*(.+?)\*\*", first_line)
            if m:
                block_timestamp = m.group(1).strip()
        if block_timestamp and _normalize_timestamp_for_match(block_timestamp) == target_norm:
            insertion_block_idx = i + 1
            # Prefer last match (most recently appended)

    if insertion_block_idx is None:
        log_debug(
            f"📋 consolidate-todos: block with timestamp > {timestamp_str} not found, falling back to Tasks section"
        )
        _append_todos_to_daily_tasks_section(path, todo_items)
        return

    # Insert todos at end of block (before next --- or EOF)
    block = blocks[insertion_block_idx]
    # Block content may end with \n; we insert before any trailing newline so we don't add extra blank lines
    blocks[insertion_block_idx] = block.rstrip() + "\n\n" + new_todos_str + "\n"

    new_content = "".join(blocks)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    log_debug(f"📋 Inserted {len(todo_items)} todo(s) into diary block -> {path}")


def _append_todos_to_daily_tasks_section(path, todo_items, content=None):
    """Ensure ## Tasks exists (insert above ## Log if missing), then append each task. Uses '- [X] ' for completed, '- [ ] ' for pending.
    When ## Project Log exists, inserts above it so order is Tasks -> Project Log -> Log.
    content: if provided, use instead of reading from path (avoids race where todo step overwrites a just-appended diary block)."""
    if not todo_items:
        return
    if is_vault_path_protected(path):
        log_debug(f"❌ Skip todos: protected path (template/excalidraw) {path}")
        return
    if content is None:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

    def fmt(t):
        return "- [X] " + t[0] if t[1] else "- [ ] " + t[0]

    new_todos_str = "\n".join(fmt(t) for t in todo_items)

    # Split on first of ## Project Log or ## Log so Tasks go above Project Log when it exists
    project_log_match = _RE_PROJECT_LOG_HEADER.search(content)
    log_match = _RE_LOG_HEADER.search(content)
    if log_match is None:
        content = content.rstrip() + "\n\n## Tasks\n\n" + new_todos_str + "\n\n## Log\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        log_debug(f"📋 Appended {len(todo_items)} todo(s) to Tasks section -> {path}")
        return

    log_start = log_match.start()
    before_log = content[:log_start].rstrip()
    after_log = content[log_start:]
    if project_log_match is not None and project_log_match.start() < log_start:
        before_log = content[: project_log_match.start()].rstrip()
        after_log = content[project_log_match.start() :]

    if "## Tasks" not in before_log:
        before_log = before_log + "\n\n## Tasks\n\n" + new_todos_str
    else:
        before_log = before_log + "\n" + new_todos_str

    new_content = before_log + "\n\n" + after_log
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    log_debug(f"📋 Appended {len(todo_items)} todo(s) to Tasks section -> {path}")


def process_todos_into_daily_note(daily_note_path, content):
    """Extract todos from content and append them to the Tasks section of the given daily note file.
    Used by diary-daily-note.py after it has already appended to the journal, so a single process
    owns all writes to the daily note (avoids two processes overwriting the same file)."""
    if not content or not content.strip():
        return
    todo_lines = _extract_todos_from_content(content)
    if todo_lines:
        _append_todos_to_daily_tasks_section(daily_note_path, todo_lines)


# Regex to find link-like spans (markdown, wiki, bare URL) in order of appearance.
_RE_LINK_MARKDOWN = re.compile(r"\[[^\]]*\]\([^)]+\)")
_RE_LINK_WIKI = re.compile(r"\[\[[^\]]+\]\]")
_RE_LINK_URL = re.compile(r"https?://[^\s\]\)]+")


def _extract_links_ordered(text):
    """Extract all link spans from text in order (left to right). Returns list of (start, end, substring)."""
    if not text:
        return []
    spans = []
    for pattern in (_RE_LINK_MARKDOWN, _RE_LINK_WIKI, _RE_LINK_URL):
        for m in pattern.finditer(text):
            spans.append((m.start(), m.end(), m.group(0)))
    spans.sort(key=lambda x: x[0])
    # Merge overlapping or adjacent and keep order (take first occurrence if two matches overlap)
    result = []
    last_end = -1
    for start, end, sub in spans:
        if start >= last_end:
            result.append((start, end, sub))
            last_end = end
    return result


def _strip_explanatory_paragraphs(text):
    """Remove paragraphs that explain corrections (e.g. 'Corrected "X" to "Y"')
    or meta-notes (e.g. 'Note: I've made some minor adjustments...').
    These often appear as a second/last paragraph with quoted words or as a Note: block."""
    if not text or not text.strip():
        return text
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    kept = []
    for p in paras:
        # Skip paragraphs that look like correction explanations: start with Corrected/Changes/Fixed/Edits and have quoted words
        if re.match(
            r"^(Corrected|Changes? made|Fixed|Edits?):?\s+", p, re.IGNORECASE
        ):
            if '"' in p or re.search(r"'[^']{2,}'", p):
                continue
        # Skip paragraphs that start with Note: (e.g. "Note: I've made some minor adjustments...")
        if re.match(r"^Note:\s+", p, re.IGNORECASE):
            continue
        kept.append(p)
    return "\n\n".join(kept).strip()


def _restore_original_links(corrected_text, original_links):
    """Replace link spans in corrected_text with original link strings when they differ.
    original_links: list of (start, end, substring) from original text (order preserved).
    We find link spans in corrected_text in order; if i-th corrected link != i-th original, replace."""
    if not original_links:
        return corrected_text
    corrected_links = _extract_links_ordered(corrected_text)
    if len(corrected_links) != len(original_links):
        # Length mismatch: still try to replace by index where we have pairs
        pass
    replacements = []
    for i in range(min(len(original_links), len(corrected_links))):
        _, _, orig_sub = original_links[i]
        c_start, c_end, corr_sub = corrected_links[i]
        if corr_sub != orig_sub:
            replacements.append((c_start, c_end, orig_sub))
    if not replacements:
        return corrected_text
    # Apply from end to start so indices stay valid
    for start, end, repl in sorted(replacements, key=lambda x: -x[0]):
        corrected_text = corrected_text[:start] + repl + corrected_text[end:]
    return corrected_text


def correct_diary_text(content):
    """Correct diary text with llama3.1:8b: spell-check and whitespace only; transcription errors only.
    Preserves links (post-check restores any original link if the model changed it).
    Returns original content on LLM failure or empty response.
    When code-based-text-cleaning is true, uses LanguageTool + heuristics instead of LLM."""
    if not content or not content.strip():
        return content
    original_links = _extract_links_ordered(content)
    try:
        if get_setting("code-based-text-cleaning", False):
            from .transcript_cleanup import code_based_cleanup

            corrected = code_based_cleanup(content.strip())
            if not corrected or not corrected.strip():
                return content
            corrected = _restore_original_links(corrected.strip(), original_links)
            return corrected
        prompt = load_prompt("05-diary/01-correct_diary")
        corrected = call_llm_diary_correction(
            prompt, content.strip(), MODEL_STAGING, json_mode=False
        )
        if not corrected or not corrected.strip():
            return content
        corrected = corrected.strip()
        # Defensive strip: remove common LLM preamble and wrapper phrases
        preamble_patterns = [
            r"^(Here is the )?corrected text:\s*\n?",
            r"^Here'?s (?:a |the )?(?:rewritten version|corrected text)(?: of your text)?(?:\s+with some minor corrections for readability)?:\s*\n?",
            r"^Here is (?:a |the )?(?:rewritten version|corrected text)(?: of your text)?(?:\s+with some minor corrections)?:\s*\n?",
            r"^Note:\s+[^\n]+\n+",  # leading "Note: ..." line(s) before first real content
        ]
        for pat in preamble_patterns:
            corrected = re.sub(pat, "", corrected, flags=re.IGNORECASE).strip()
        corrected = _strip_explanatory_paragraphs(corrected)
        corrected = _restore_original_links(corrected, original_links)
        return corrected
    except Exception as e:
        log_debug(f"⚠️ Diary text correction failed: {e}")
        return content


def handle_daily_raw(content, source_datetime=None, skip_todos=False):
    """Append content to the daily note (4AM logic, template, todos). source_datetime=(date_str, time_12h, dt) from filename or None for current.
    If skip_todos=True, skips LLM todo classification for fast raw append (e.g. Alfred diary hotkey)."""
    if source_datetime is not None:
        date_str, time_12h, dt = source_datetime
        path_today, _, _ = _get_daily_note_path(for_dt=dt)
        timestamp_str = time_12h
        log_debug(
            f"💾 Daily note using original date/time from filename: {date_str} {time_12h}"
        )
    else:
        path_today, now, _ = _get_daily_note_path()
        timestamp_str = _format_time_12h(now)
        log_debug("💾 Daily note using current date/time")
    if is_vault_path_protected(path_today):
        log_debug(
            f"❌ Block: cannot write to protected path (template/excalidraw): {path_today}"
        )
        return "❌ Cannot modify template or excalidraw file"
    _ensure_daily_note_exists(path_today)

    diary_mode = get_setting("report-notes-save-to-diary-mode", "original")
    diary_save_format = (
        get_setting("diary-save-format", "default") or "default"
    ).strip().lower()
    if diary_save_format not in ("default", "bullet-list"):
        diary_save_format = "default"
    use_project_log = (
        get_setting("group-diary-by-project", False) and diary_mode != "project-mention"
    )
    if use_project_log:
        new_block = _format_diary_entry(timestamp_str, content, diary_save_format)

        def build_new_content(current_content):
            before_pl, project_log_content, log_content = _split_daily_sections(
                current_content
            )
            project_entries = _parse_project_log_to_entries(project_log_content or "")
            general_blocks = _parse_log_section_to_general_blocks(log_content)
            general_blocks.append(new_block)
            return _rebuild_daily_content(before_pl, project_entries, general_blocks)

        if not _read_merge_write_daily_note(path_today, build_new_content):
            log_debug("❌ Daily note save aborted (file conflict)")
            return "❌ Diary write could not be verified"
    else:
        with open(path_today, "r", encoding="utf-8") as f:
            current_content = f.read()
        _, _, log_content = _split_daily_sections(current_content)
        log_has_entry = bool(log_content.strip()) and (
            "---" in log_content
            or _RE_TIMESTAMP_LINE.search(log_content)
            or re.search(r"-\s+\*\*[^*]+\*\*", log_content)  # bullet-list format
        )
        formatted = _format_diary_entry(timestamp_str, content, diary_save_format)
        if log_has_entry:
            to_append = f"\n\n---\n{formatted}"
        else:
            to_append = f"\n\n{formatted}"
        with open(path_today, "a", encoding="utf-8") as f:
            f.write(to_append)

    # Todo extraction uses only the current input (never the whole diary). After the LLM call we
    # do a single fresh read and write todos immediately so we never hold diary content across
    # a slow LLM call (avoids overwriting user edits or dropping the just-appended block).
    if not skip_todos:
        classified = _classify_todo_timing_and_type(content)
        try:
            with open(path_today, "r", encoding="utf-8") as f:
                daily_note_content_for_todos = f.read()
        except OSError:
            daily_note_content_for_todos = None
        _route_classified_todos(
            classified,
            diary_block_context=(path_today, timestamp_str),
            daily_note_content=daily_note_content_for_todos,
        )

    # Verify diary block is on disk (todo step may have overwritten file)
    try:
        with open(path_today, "r", encoding="utf-8") as f:
            on_disk = f.read()
        block_header_with_divider = f"\n---\n> {timestamp_str}\n\n"
        block_header_first_entry = f"> {timestamp_str}\n\n"
        block_header_bullet = f"- **{timestamp_str}**"
        content_fingerprint = (
            (content.strip()[:80] + "…")
            if len(content.strip()) > 80
            else content.strip()
        )
        block_found = (
            block_header_with_divider in on_disk
            or block_header_first_entry in on_disk
            or block_header_bullet in on_disk
        )
        content_found = (
            not content_fingerprint or content_fingerprint.rstrip("…") in on_disk
        )
        if not block_found or not content_found:
            log_debug(
                f"❌ Diary write verification failed: block or content not found in {path_today}"
            )
            return "❌ Diary write could not be verified"
    except Exception as e:
        log_debug(f"❌ Diary write verification error: {e}")
        return "❌ Diary write could not be verified"

    # Optionally append to a keyword-matched devlog (e.g. "smart butler" -> Smart Butler.md)
    if get_setting("diary-also-append-to-matched-devlog", False) and content:
        try:
            matched_devlogs, _, _ = match_keywords_in_content(content)
            if matched_devlogs:
                limited, _, _ = apply_category_limits(
                    matched_devlogs, {}, {}, max_devlogs=1
                )
                if limited:
                    devlog_path = next(iter(limited))
                    if source_datetime is not None:
                        sd = source_datetime
                    else:
                        date_str = os.path.basename(path_today).replace(".md", "")
                        sd = (date_str, timestamp_str, datetime.datetime.now())
                    handle_dev_log(content, devlog_path, source_datetime=sd)
                    log_debug(
                        f"💾 Diary also appended to matched devlog -> {devlog_path}"
                    )
        except Exception as e:
            log_debug(f"⚠️ diary-also-append-to-matched-devlog failed: {e}")

    log_debug(f"💾 Action: Daily Note Saved -> {path_today}")
    return f"{get_vault_folder(path_today)} | Daily"


def handle_daily(content, source_datetime=None):
    """Default: correct (spell-check, whitespace, link preservation) then append. Used by voice-memo classifier."""
    content = correct_diary_text(content)
    return handle_daily_raw(content, source_datetime=source_datetime)


def handle_idea(content):
    log_debug("Generating Idea Filename...")
    name = (
        call_llm(load_prompt("11-filename/01-generate_filename"), content, MODEL_FAST)
        or "idea"
    )
    name = "".join([c for c in name if c.isalnum() or c in ("-", "_")]).strip().lower()
    today = datetime.datetime.now().strftime("%Y-%m-%d")

    path = os.path.join(IDEAS_DIR, f"{name}_{today}.md")
    count = 1
    while os.path.exists(path):
        path = os.path.join(IDEAS_DIR, f"{name}_{today}_{count}.md")
        count += 1

    if is_vault_path_protected(path):
        log_debug(
            f"❌ Block: cannot write to protected path (template/excalidraw): {path}"
        )
        return "❌ Cannot modify template or excalidraw file"
    os.makedirs(IDEAS_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"---\ndate: {today}\n---\n#Idea\n\n{content}")

    log_debug(f"💾 Action: Idea File Created -> {path}")
    return f"{get_vault_folder(path)} | Idea: {os.path.basename(path)}"


def handle_experiment_create(content):
    log_debug("Creating New Experiment...")
    today = datetime.datetime.now().strftime("%Y-%m-%d")

    # Generate Clean Filename
    name = (
        call_llm(load_prompt("11-filename/01-generate_filename"), content, MODEL_FAST)
        or "exp"
    )
    clean_name = (
        "".join([c for c in name if c.isalnum() or c in ("-", "_")]).strip().lower()
    )
    filename = f"tiny-experiment-{clean_name}-{today}.md"
    path = os.path.join(EXPERIMENT_DIR, filename)

    if is_vault_path_protected(path):
        log_debug(
            f"❌ Block: cannot write to protected path (template/excalidraw): {path}"
        )
        return "❌ Cannot modify template or excalidraw file"
    # 1. Create the Note
    os.makedirs(EXPERIMENT_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            f"---\ndate_created: {today}\n---\n\n#Tiny-Experiment\n\n# {clean_name.replace('-', ' ').title()}\n\n{content}"
        )

    # 2. Append to Index (Pure Python Verification)
    try:
        if not is_vault_path_protected(EXPERIMENT_INDEX):
            link_entry = format_wiki_link(filename)
            with open(EXPERIMENT_INDEX, "a", encoding="utf-8") as f:
                f.write(f"\n{link_entry}")

        log_debug(f"Linked to Experiment Index: {EXPERIMENT_INDEX}")
    except Exception as e:
        log_debug(f"⚠️ Failed to link to Index: {e}")

    append_blockquote_to_human_diary(f"Experiments: {vault_relative_link(path)}")
    log_debug(f"💾 Action: Experiment File Saved -> {path}")
    return f"{get_vault_folder(path)} | New Exp: {filename}"


def handle_experiment_log(
    content,
    path,
    extra_paths=None,
    source_datetime=None,
    summary=None,
    skip_diary_report_and_todos=False,
):
    if not path or not is_safe_path(path):
        log_debug(f"❌ Exp Log Failed: Unsafe/Null Path '{path}'")
        return "❌ Err: Invalid Path"
    if is_vault_path_protected(path):
        log_debug(f"❌ Exp Log Failed: protected path (template/excalidraw): {path}")
        return "❌ Cannot modify template or excalidraw file"
    if not os.path.exists(path):
        log_debug(f"❌ Exp Log Failed: File not found '{path}'")
        return "❌ Err: Not Found"

    if source_datetime is not None:
        date_str, time_12h, dt = source_datetime
        date_str = _note_date_from_datetime(dt)
        log_debug(
            f"💾 Exp log using original date/time from filename: {date_str} {time_12h}"
        )
    else:
        now = datetime.datetime.now()
        date_str = _note_date_from_datetime(now)
        time_12h = _format_time_12h(now)
        log_debug("💾 Exp log using current date/time")

    # Resolve summary if needed (diary or main-file chain) and router did not provide one
    diary_mode = get_setting("report-notes-save-to-diary-mode", "original")
    diary_primary, _, report_also = _parse_diary_mode(diary_mode)
    report_mode_for_summary = (
        report_also if diary_primary == "project-mention" else diary_primary
    )
    main_chain = (
        get_setting("experiment-notes-save-to-main-file")
        or get_setting("report-notes-save-to-main-file", "one-liner-summary,original")
        or ""
    )
    needs_summary = report_mode_for_summary in ("summary", "one-liner-summary") or any(
        t in main_chain.lower() for t in ("summary", "one-liner-summary")
    )
    if needs_summary and not (summary or "").strip():
        summary = _generate_fast_summary(content, "use_experiment_log") or summary
    if not (summary or "").strip():
        summary = None

    content_for_chain = content
    if (
        get_setting("code-based-text-cleaning", False)
        and content
        and str(content).strip()
    ):
        cleaned = code_based_cleanup(content.strip())
        if cleaned and cleaned.strip():
            content_for_chain = cleaned
    main_chain_tokens = [
        t.strip().lower()
        for t in (main_chain or "").replace(" ", ",").split(",")
        if t.strip()
    ]
    chain_has_todos = "todos" in main_chain_tokens
    main_file_body, one_liner_for_diary = _build_main_file_content_from_chain(
        main_chain, time_12h, content_for_chain, summary, "use_experiment_log"
    )
    if not main_file_body or len(main_file_body.strip()) < 10:
        main_file_body = content_for_chain

    today_header = f"## {date_str}"
    save_format = get_setting("experiment-notes-save-format", "simple") or "simple"
    _append_to_main_file_with_format(
        path, today_header, main_file_body, save_format, time_12h
    )

    classified = _classify_todo_timing_and_type(content)
    if chain_has_todos and classified.get("today"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(_format_todos_for_project_file(classified["today"]))
        log_debug(
            f"📋 Appended {len(classified['today'])} todo(s) to project file -> {path}"
        )
    if not skip_diary_report_and_todos:
        diary_primary, diary_include_todos, report_also_mode = _parse_diary_mode(
            get_setting("report-notes-save-to-diary-mode", "original")
        )
        send_today_to_daily = not chain_has_todos and (
            diary_primary != "project-mention" and diary_include_todos
        )
        _route_classified_todos(classified, send_today_to_daily=send_today_to_daily)

    refd_basenames = []
    rel_primary = os.path.relpath(path, VAULT_ROOT).replace("\\", "/")
    block_embed = f"\n\n![[{rel_primary}#{date_str}]]\n"
    for other in extra_paths or []:
        if other == path:
            continue
        if not is_safe_path(other) or not os.path.exists(other):
            log_debug(f"⚠️ Exp Log: skipping invalid/absent extra_path: {other}")
            continue
        if is_vault_path_protected(other):
            log_debug(
                f"⚠️ Exp Log: skipping protected path (template/excalidraw): {other}"
            )
            continue
        with open(other, "a", encoding="utf-8") as f:
            f.write(block_embed)
        refd_basenames.append(os.path.basename(other))
        log_debug(f"💾 Action: Block ref added to Experiment -> {other}")

    log_debug(f"💾 Action: Appended to Experiment -> {path}")

    # Report note to human diary (project-mention / original / summary / one-liner-summary; chained = both).
    # Skipped when router also sent to diary (split): one write per input, diary from use_daily_journal overrides.
    if not skip_diary_report_and_todos:
        diary_primary, _, report_also_mode = _parse_diary_mode(
            get_setting("report-notes-save-to-diary-mode", "original")
        )
        report_mode = (
            report_also_mode if diary_primary == "project-mention" else diary_primary
        )
        if diary_primary == "project-mention":
            _append_active_projects_bullet_if_needed(date_str, path)
        if report_mode and not get_setting("add-context-to-report-summary", False):
            file_note = f"Updated {vault_relative_link(path)}"
            if report_mode == "original":
                _append_report_note_to_human_diary(
                    "original", date_str, time_12h, file_note, content, project_path=path
                )
            elif report_mode == "summary":
                body = (summary or "").strip() or content
                _append_report_note_to_human_diary(
                    "summary", date_str, time_12h, file_note, body, project_path=path
                )
            else:
                body = one_liner_for_diary if one_liner_for_diary else _to_one_line_for_diary((summary or "").strip() or content)
                _append_report_note_to_human_diary(
                    "one-liner-summary",
                    date_str,
                    time_12h,
                    file_note,
                    body,
                    project_path=path,
                )

    msg = f"{get_vault_folder(path)} | Exp Log: {os.path.basename(path)}"
    if refd_basenames:
        msg += f"; block ref → {', '.join(refd_basenames)}"
    return msg


def _find_existing_devlog_for_slug(slug):
    """Return path of an existing devlog file in DEVLOG_DIR whose stem matches slug, or None."""
    if not slug or not os.path.isdir(DEVLOG_DIR):
        return None
    exact = os.path.join(DEVLOG_DIR, f"{slug}.md")
    if os.path.exists(exact) and is_safe_path(exact):
        return exact
    try:
        for name in os.listdir(DEVLOG_DIR) or []:
            if not name.endswith(".md"):
                continue
            stem = name[:-3]
            if stem == slug:
                path = os.path.join(DEVLOG_DIR, name)
                if is_safe_path(path):
                    return path
    except OSError:
        pass
    return None


def handle_dev_log_create(content):
    """Create a new devlog project note, or silently append to existing if file already exists (auto-discovery)."""
    log_debug("Devlog create: resolving project slug...")
    name = (
        call_llm(load_prompt("11-filename/01-generate_filename"), content, MODEL_FAST)
        or "project"
    )
    clean_name = (
        "".join([c for c in name if c.isalnum() or c in ("-", "_")]).strip().lower()
    )
    if not clean_name:
        clean_name = "project"

    # Auto-discovery: if a matching file already exists, append instead of creating
    existing_path = _find_existing_devlog_for_slug(clean_name)
    if existing_path:
        log_debug(
            f"Devlog create: found existing '{existing_path}', appending via handle_dev_log."
        )
        return handle_dev_log(content, existing_path)

    path = os.path.join(DEVLOG_DIR, f"{clean_name}.md")
    if is_vault_path_protected(path):
        log_debug(
            f"❌ Block: cannot write to protected path (template/excalidraw): {path}"
        )
        return "❌ Cannot modify template or excalidraw file"
    os.makedirs(DEVLOG_DIR, exist_ok=True)
    title_phrase = clean_name.replace("-", " ").title()
    if is_template_path(path):
        frontmatter = "---\n---\n\n"
    else:
        how_i_refer = f"how I refer to this project: {title_phrase}"
        frontmatter = (
            f'---\nbutler_summary: "{how_i_refer}"\nbutler_keywords: ""\n---\n\n'
        )
    body = f"# {title_phrase}\n\n{content}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(frontmatter + body)

    record_butler_write(path)
    append_blockquote_to_human_diary(f"Project: {vault_relative_link(path)}")
    log_debug(f"💾 Action: New Devlog Created -> {path}")
    return f"{get_vault_folder(path)} | New Devlog: {os.path.basename(path)}"


def handle_dev_log(
    content,
    path,
    source_datetime=None,
    summary=None,
    skip_diary_report_and_todos=False,
):
    """Append content to a project devlog file. Adds ## YYYY-MM-DD if missing; always prefixes with time in 12h AM/PM."""
    if not path or not is_safe_path(path):
        log_debug(f"❌ Dev Log Failed: Unsafe/Null Path '{path}'")
        return "❌ Err: Invalid Path"
    if is_vault_path_protected(path):
        log_debug(f"❌ Dev Log Failed: protected path (template/excalidraw): {path}")
        return "❌ Cannot modify template or excalidraw file"
    abs_path = os.path.abspath(os.path.normpath(path))
    abs_devlog = os.path.abspath(DEVLOG_DIR)
    if not abs_path.startswith(abs_devlog + os.sep) and abs_path != abs_devlog:
        log_debug(f"❌ Dev Log Failed: Path not under Devlog dir '{path}'")
        return "❌ Err: Path must be under Devlog"
    if not os.path.exists(path):
        log_debug(f"❌ Dev Log Failed: File not found '{path}'")
        return "❌ Err: Not Found"

    if source_datetime is not None:
        date_str, time_12h, dt = source_datetime
        date_str = _note_date_from_datetime(dt)
        log_debug(
            f"💾 Devlog using original date/time from filename: {date_str} {time_12h}"
        )
    else:
        now = datetime.datetime.now()
        date_str = _note_date_from_datetime(now)
        time_12h = _format_time_12h(now)
        log_debug("💾 Devlog using current date/time")

    # Resolve summary if needed (diary or main-file chain) and router did not provide one
    diary_mode = get_setting("report-notes-save-to-diary-mode", "original")
    diary_primary, _, report_also = _parse_diary_mode(diary_mode)
    report_mode_for_summary = (
        report_also if diary_primary == "project-mention" else diary_primary
    )
    main_chain = (
        get_setting("devlog-notes-save-to-main-file")
        or get_setting("report-notes-save-to-main-file", "one-liner-summary,original")
        or ""
    )
    needs_summary = report_mode_for_summary in ("summary", "one-liner-summary") or any(
        t in main_chain.lower() for t in ("summary", "one-liner-summary")
    )
    if needs_summary and not (summary or "").strip():
        summary = _generate_fast_summary(content, "use_dev_log") or summary
    if not (summary or "").strip():
        summary = None

    content_for_chain = content
    if (
        get_setting("code-based-text-cleaning", False)
        and content
        and str(content).strip()
    ):
        cleaned = code_based_cleanup(content.strip())
        if cleaned and cleaned.strip():
            content_for_chain = cleaned
    main_chain_tokens = [
        t.strip().lower()
        for t in (main_chain or "").replace(" ", ",").split(",")
        if t.strip()
    ]
    chain_has_todos = "todos" in main_chain_tokens
    main_file_body, one_liner_for_diary = _build_main_file_content_from_chain(
        main_chain, time_12h, content_for_chain, summary, "use_dev_log"
    )
    if not main_file_body or len(main_file_body.strip()) < 10:
        main_file_body = content_for_chain

    today_header = f"## {date_str}"
    save_format = get_setting("devlog-notes-save-format", "simple") or "simple"
    _append_to_main_file_with_format(
        path, today_header, main_file_body, save_format, time_12h
    )

    classified = _classify_todo_timing_and_type(content)
    if chain_has_todos and classified.get("today"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(_format_todos_for_project_file(classified["today"]))
        log_debug(
            f"📋 Appended {len(classified['today'])} todo(s) to project file -> {path}"
        )

    log_debug(f"💾 Action: Appended to Devlog -> {path}")
    record_butler_write(path)

    if not skip_diary_report_and_todos:
        diary_primary, diary_include_todos, report_also_mode = _parse_diary_mode(
            get_setting("report-notes-save-to-diary-mode", "original")
        )
        send_today_to_daily = not chain_has_todos and (
            diary_primary != "project-mention" and diary_include_todos
        )
        _route_classified_todos(classified, send_today_to_daily=send_today_to_daily)

        report_mode = (
            report_also_mode if diary_primary == "project-mention" else diary_primary
        )
        if diary_primary == "project-mention":
            _append_active_projects_bullet_if_needed(date_str, path)
        if report_mode and not get_setting("add-context-to-report-summary", False):
            file_note = f"Updated {vault_relative_link(path)}"
            if report_mode == "original":
                _append_report_note_to_human_diary(
                    report_mode, date_str, time_12h, file_note, content, project_path=path
                )
            elif report_mode == "summary":
                body = (summary or "").strip() or content
                _append_report_note_to_human_diary(
                    report_mode, date_str, time_12h, file_note, body, project_path=path
                )
            else:
                body = one_liner_for_diary if one_liner_for_diary else _to_one_line_for_diary((summary or "").strip() or content)
                _append_report_note_to_human_diary(
                    "one-liner-summary",
                    date_str,
                    time_12h,
                    file_note,
                    body,
                    project_path=path,
                )

    return f"{get_vault_folder(path)} | Dev log: {os.path.basename(path)}"


# --- Zettel creation (inlined from KeyboardMaestro SaveToZettel/create_zettel_note.py) ---
_ZETTEL_VAULT = os.path.join(
    VAULT_ROOT, "ZettelPublish (Content Creator V2 April 2025)"
)
_ZETTEL_INBOX = os.path.join(_ZETTEL_VAULT, "01 Inbox")
_ZETTEL_SCAN_FOLDERS = [
    "01 Inbox",
    "02 Reference Notes",
    "03 Sleeping Notes",
    "04 Main (Point) Notes",
]
_ZETTEL_ID_PATTERN = re.compile(r"^\s*zettel_id:\s*(\d+)\s*$", re.MULTILINE)


def _zettel_strip_front_matter(content):
    """Return body only (after second ---)."""
    parts = content.split("---")
    if len(parts) >= 3:
        return parts[2].strip()
    return content.strip()


def _zettel_get_highest_id():
    """Max zettel_id in scanned folders."""
    highest = 0
    for folder in _ZETTEL_SCAN_FOLDERS:
        scan_path = os.path.join(_ZETTEL_VAULT, folder)
        if not os.path.exists(scan_path):
            continue
        for name in os.listdir(scan_path):
            if not name.endswith(".md"):
                continue
            filepath = os.path.join(scan_path, name)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    m = _ZETTEL_ID_PATTERN.search(f.read())
                    if m and int(m.group(1)) > highest:
                        highest = int(m.group(1))
            except Exception:
                pass
    return highest


def _zettel_find_duplicate(note_content):
    """Return path of existing note with same body, or None."""
    normalized = note_content.strip()
    for folder in _ZETTEL_SCAN_FOLDERS:
        scan_path = os.path.join(_ZETTEL_VAULT, folder)
        if not os.path.isdir(scan_path):
            continue
        for name in os.listdir(scan_path):
            if not name.endswith(".md"):
                continue
            filepath = os.path.join(scan_path, name)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    body = _zettel_strip_front_matter(f.read())
                    if body == normalized:
                        return filepath
            except Exception:
                pass
    return None


def _zettel_create_note(note_content):
    """
    Create a new zettel in 01 Inbox with front matter (date_created, zettel_id).
    Returns created file path, or None on duplicate or write error.
    """
    if _zettel_find_duplicate(note_content):
        return None
    os.makedirs(_ZETTEL_INBOX, exist_ok=True)
    highest = _zettel_get_highest_id()
    new_id = highest + 1
    now = datetime.datetime.now()
    date_created = now.strftime("%Y-%m-%d")
    file_timestamp = now.strftime("%Y-%m-%d_%I-%M-%p")
    front_matter = f"""---
date_created: {date_created}
zettel_id: {new_id}
---

"""
    full_content = front_matter + note_content.strip()
    new_filename = f"{new_id}-{file_timestamp}.md"
    new_filepath = os.path.join(_ZETTEL_INBOX, new_filename)
    if is_vault_path_protected(new_filepath):
        log_debug(
            f"❌ Zettel create: protected path (template/excalidraw): {new_filepath}"
        )
        return None
    try:
        with open(new_filepath, "w", encoding="utf-8") as f:
            f.write(full_content)
        return new_filepath
    except Exception as e:
        log_debug(f"❌ Zettel write failed: {e}")
        return None


def _zettel_update_file_content(file_path, new_body):
    """
    Update zettel file body while preserving front matter.
    Used by task_zettelkasten_cleanup after LLM cleanup.
    """
    if not file_path or not os.path.isfile(file_path):
        return
    if is_vault_path_protected(file_path):
        log_debug(
            f"❌ Zettel update: protected path (template/excalidraw): {file_path}"
        )
        return
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw = f.read()
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            front = "---" + parts[1] + "---\n\n"
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(front + new_body.strip())
        else:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_body.strip())
    except Exception as e:
        log_debug(f"❌ Zettel update failed: {e}")


def _zettel_append_to_body(file_path, append_text):
    """Append text to zettel body while preserving front matter."""
    if not file_path or not os.path.isfile(file_path) or not append_text:
        return
    if is_vault_path_protected(file_path):
        log_debug(
            f"❌ Zettel append to body: protected path (template/excalidraw): {file_path}"
        )
        return
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw = f.read()
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            front = "---" + parts[1] + "---\n\n"
            body = parts[2].strip()
            new_body = body + "\n\n" + append_text.strip()
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(front + new_body)
        else:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write("\n\n" + append_text.strip())
    except Exception as e:
        log_debug(f"❌ Zettel append failed: {e}")


def handle_zettel_append(path, content):
    """
    Append content to an existing zettel file. Path must be under _ZETTEL_VAULT.
    Uses idempotency so the same content is not appended twice to the same file.
    """
    if not path or not path.strip():
        log_debug("❌ Zettel append: no path")
        return "❌ Err: No Path"
    path = os.path.abspath(os.path.normpath(path.strip()))
    if not is_safe_path(path):
        log_debug(f"❌ Zettel append: unsafe path {path}")
        return "❌ Err: Unsafe Path"
    if is_vault_path_protected(path):
        log_debug(f"❌ Zettel append: protected path (template/excalidraw): {path}")
        return "❌ Cannot modify template or excalidraw file"
    abs_zettel = os.path.abspath(_ZETTEL_VAULT)
    if not path.startswith(abs_zettel + os.sep) and path != abs_zettel:
        log_debug(f"❌ Zettel append: path not under zettel vault {path}")
        return "❌ Err: Path must be under Zettel vault"
    if not os.path.isfile(path):
        log_debug(f"❌ Zettel append: file not found {path}")
        return "❌ Err: Not Found"
    from .cache_manager import IdempotencyManager
    from .types import CACHE_DB_PATH

    idem = IdempotencyManager(db_path=CACHE_DB_PATH)
    content_for_id = content + "\0" + path
    op_id = idem.generate_operation_id(content_for_id, "zettel_append")
    try:
        idem.check_and_record(op_id, "zettel_append", content_for_id, path)
    except ValueError:
        log_debug("⚠️ Zettel append skipped (idempotency).")
        return "⏭️ Skipped (duplicate)"
    _zettel_append_to_body(path, content)
    record_butler_write(path)
    log_debug(f"💾 Action: Appended to Zettel -> {path}")
    return f"{get_vault_folder(path)} | Zettel appended: {os.path.basename(path)}"


def get_destination_path_for_operation(op_type, path, source_datetime=None):
    """
    Return the file path that will be written to for this operation (for reference link injection).
    Returns None if no vault path (e.g. Apple Notes). For ops that create a new file, returns the directory or vault root so vault name is correct.
    """
    if op_type == "use_daily_journal":
        if source_datetime is not None:
            _, _, dt = source_datetime
            p, _, _ = _get_daily_note_path(for_dt=dt)
            return p
        p, _, _ = _get_daily_note_path()
        return p
    if op_type in ("use_experiment_log", "use_dev_log") and path:
        return os.path.abspath(path)
    if op_type == "use_idea_generator":
        return IDEAS_DIR
    if op_type == "use_zettel_script":
        return _ZETTEL_VAULT
    if op_type == "use_zettel_append" and path:
        return os.path.abspath(path)
    if op_type == "use_fiction_append":
        return FICTION_PATH
    if op_type == "use_experiment_create":
        return EXPERIMENT_DIR
    if op_type == "use_dev_log_create":
        return DEVLOG_DIR
    return None


def handle_zettel(content, summary=None, skip_diary_report_and_todos=False):
    """
    Create zettel note with raw text, enqueue cleanup (priority 10) then breakdown (priority 2).
    Cleanup runs LLM text cleanup and updates file; breakdown adds AI sections.
    When zettel-notes-save-to-diary-mode (or report-notes-save-to-diary-mode if unset) is summary or one-liner-summary, appends a diary entry.
    """
    log_debug("Action: Zettel (create file with raw -> enqueue cleanup + breakdown)...")

    _, now, _ = _get_daily_note_path()
    time_12h = _format_time_12h(now)

    diary_mode = get_setting("zettel-notes-save-to-diary-mode", None) or get_setting(
        "report-notes-save-to-diary-mode", "original"
    )
    diary_primary, _, report_also = _parse_diary_mode(diary_mode)
    report_mode_for_summary = (
        report_also if diary_primary == "project-mention" else diary_primary
    )
    main_chain = (
        get_setting("zettel-notes-save-to-main-file", None)
        or get_setting("report-notes-save-to-main-file", "one-liner-summary,original")
        or ""
    )
    needs_summary = report_mode_for_summary in ("summary", "one-liner-summary") or any(
        t in main_chain.lower() for t in ("summary", "one-liner-summary")
    )
    if needs_summary and not (summary or "").strip():
        summary = _generate_fast_summary(content, "use_zettel_script") or summary
    if not (summary or "").strip():
        summary = None

    content_for_chain = content
    if (
        get_setting("code-based-text-cleaning", False)
        and content
        and str(content).strip()
    ):
        cleaned = code_based_cleanup(content.strip())
        if cleaned and cleaned.strip():
            content_for_chain = cleaned
    main_chain_tokens = [
        t.strip().lower()
        for t in (main_chain or "").replace(" ", ",").split(",")
        if t.strip()
    ]
    chain_has_todos = "todos" in main_chain_tokens
    main_file_body, one_liner_for_diary = _build_main_file_content_from_chain(
        main_chain, time_12h, content_for_chain, summary, "use_zettel_script"
    )
    if not main_file_body or len(main_file_body.strip()) < 10:
        main_file_body = content_for_chain

    # Create physical note with chain-built content
    log_debug("🚀 Creating note in zettel Inbox (raw content)...")
    created_file_path = _zettel_create_note(main_file_body)
    if not created_file_path:
        duplicate_path = _zettel_find_duplicate(main_file_body)
        if duplicate_path:
            log_debug(f"🛑 Duplicate content; existing note: {duplicate_path}")
            return "❌ Err: Duplicate"
        log_debug("❌ Zettel note creation failed.")
        return "❌ Err: Script Fail"

    log_debug(f"✅ Note created: {created_file_path}")

    classified = _classify_todo_timing_and_type(content)
    if chain_has_todos and classified.get("today"):
        try:
            with open(created_file_path, "a", encoding="utf-8") as f:
                f.write(_format_todos_for_project_file(classified["today"]))
            log_debug(
                f"📋 Appended {len(classified['today'])} todo(s) to project file -> {created_file_path}"
            )
        except OSError as e:
            log_debug(f"⚠️ Failed to append todos to zettel: {e}")
    if not skip_diary_report_and_todos:
        diary_primary, diary_include_todos, report_also_mode = _parse_diary_mode(diary_mode)
        send_today_to_daily = not chain_has_todos and (
            diary_primary != "project-mention" and diary_include_todos
        )
        _route_classified_todos(classified, send_today_to_daily=send_today_to_daily)

        report_mode = (
            report_also_mode if diary_primary == "project-mention" else diary_primary
        )
        if diary_primary == "project-mention":
            _append_active_projects_bullet_if_needed(None, created_file_path)
        if report_mode:
            if get_setting("add-context-to-report-summary", False):
                from .task_queue import enqueue_context_aware_report_summary

                enqueue_context_aware_report_summary(
                    op_type="use_zettel_script",
                    original_text=content,
                    path=created_file_path,
                    source_datetime=None,
                    event_description="Created zettelkasten note for intellectual work",
                )
            else:
                file_note = f"Zettel: {vault_relative_link(created_file_path)}"
                body = (summary or "").strip() or content
                if report_mode == "original":
                    _append_report_note_to_human_diary(
                        "original",
                        None,
                        time_12h,
                        file_note,
                        content,
                        project_path=created_file_path,
                    )
                elif report_mode == "summary":
                    _append_report_note_to_human_diary(
                        "summary",
                        None,
                        time_12h,
                        file_note,
                        body,
                        project_path=created_file_path,
                    )
                else:
                    one_liner_body = one_liner_for_diary if one_liner_for_diary else _to_one_line_for_diary(body)
                    _append_report_note_to_human_diary(
                        "one-liner-summary",
                        None,
                        time_12h,
                        file_note,
                        one_liner_body,
                        project_path=created_file_path,
                    )

    # Enqueue cleanup (priority 10); cleanup will enqueue breakdown (priority 2)
    # Only pass original_content when chain includes "original" (raw transcript to clean)
    from .task_queue import enqueue_zettelkasten_cleanup

    chain_tokens = [
        t.strip().lower()
        for t in (main_chain or "").replace(" ", ",").split(",")
        if t.strip()
    ]
    pass_original = "original" in chain_tokens and content
    if enqueue_zettelkasten_cleanup(
        main_file_body,
        created_file_path,
        original_content=content if pass_original else None,
    ):
        log_debug("🐢 Zettelkasten cleanup enqueued (then breakdown).")
    else:
        log_debug("⏭️ Zettelkasten cleanup skipped (duplicate/idempotency).")

    return "Inbox | Zettel Created"


def handle_apple_coffee_log(content):
    log_debug("Logging to Apple Notes...")

    # Clean content for AppleScript (escape quotes and replace newlines with HTML breaks)
    safe_content = content.replace('"', '\\"').replace("\n", "<br>")
    note_name = "Coffee Log"
    tag = "#my_espresso_brew"

    # AppleScript to find/create the note and append the entry with a timestamp
    applescript = f'''
    tell application "Notes"
        tell default account
            if not (exists note "{note_name}") then
                make new note with properties {{name:"{note_name}", body:"<h1>{note_name}</h1><p>{tag}</p>"}}
            end if

            set targetNote to note "{note_name}"
            set oldBody to body of targetNote

            -- Prepare the new entry with a timestamp
            set newEntry to "<hr><p><b>" & (do shell script "date '+%Y-%m-%d %H:%M'") & "</b><br>" & "{safe_content}" & "</p>"

            -- Inject the new entry before the closing body tags
            set newBody to text 1 thru -15 of oldBody & newEntry & "</body></html>"
            set body of targetNote to newBody
        end tell
    end tell
    '''

    try:
        subprocess.run(["osascript", "-e", applescript], check=True)
        log_debug(f"✅ AppleScript Success: Appended to '{note_name}'")
        return "External | Apple Notes (Coffee)"
    except Exception as e:
        log_debug(f"❌ AppleScript Failed: {e}")
        return "❌ Err: AppleScript Fail"


def append_to_apple_note(note_title: str, content: str) -> bool:
    """
    Append timestamped content to an Apple Note by title.
    Creates the note if it doesn't exist.
    Returns True on success, False on failure.
    """
    if not content or not content.strip():
        return False
    safe_content = content.replace('"', '\\"').replace("\n", "<br>")
    safe_note_name = note_title.replace('"', '\\"')
    applescript = f'''
    tell application "Notes"
        tell default account
            if not (exists note "{safe_note_name}") then
                make new note with properties {{name:"{safe_note_name}", body:""}}
            end if

            set targetNote to note "{safe_note_name}"
            set oldBody to body of targetNote

            set newEntry to "<hr><p><b>" & (do shell script "date '+%Y-%m-%d %H:%M'") & "</b><br>" & "{safe_content}" & "</p>"

            if oldBody ends with "</body></html>" then
                set newBody to text 1 thru -15 of oldBody & newEntry & "</body></html>"
            else
                set newBody to oldBody & newEntry
            end if
            set body of targetNote to newBody
        end tell
    end tell
    '''
    try:
        subprocess.run(
            ["osascript", "-e", applescript],
            check=True,
            timeout=15,
            capture_output=True,
        )
        log_debug(f"✅ AppleScript Success: Appended to '{note_title}'")
        return True
    except subprocess.CalledProcessError as e:
        log_debug(f"❌ AppleScript Failed for '{note_title}': {e}")
        return False
    except subprocess.TimeoutExpired:
        log_debug(f"❌ AppleScript timed out for '{note_title}'")
        return False
    except Exception as e:
        log_debug(f"❌ AppleScript exception for '{note_title}': {e}")
        return False


def handle_apple_notes_general(content):
    log_debug("Logging to Apple Notes (General AI)...")

    mapping = resolve_apple_notes_target_from_memories(content)
    note_name = mapping.get("note_name") or "Inbox"
    tag = mapping.get("tag") or "#inbox"

    safe_content = content.replace('"', '\\"').replace("\n", "<br>")
    safe_note_name = note_name.replace('"', '\\"')
    safe_tag = tag.replace('"', '\\"')

    applescript = f'''
    tell application "Notes"
        tell default account
            if not (exists note "{safe_note_name}") then
                make new note with properties {{name:"{safe_note_name}", body:"<h1>{safe_note_name}</h1><p>{safe_tag}</p>"}}
            end if

            set targetNote to note "{safe_note_name}"
            set oldBody to body of targetNote

            -- Append: timestamp + content only (tag is set once when the note is created)
            set newEntry to "<hr><p><b>" & (do shell script "date '+%Y-%m-%d %H:%M'") & "</b><br>" & "{safe_content}" & "</p>"

            -- Inject the new entry before the closing body tags
            if oldBody ends with "</body></html>" then
                set newBody to text 1 thru -15 of oldBody & newEntry & "</body></html>"
            else
                set newBody to oldBody & newEntry
            end if
            set body of targetNote to newBody
        end tell
    end tell
    '''

    try:
        subprocess.run(["osascript", "-e", applescript], check=True)
        log_debug(f"✅ AppleScript Success: Appended to '{note_name}' ({tag})")
        if mapping.get("memory_written_path"):
            log_debug(f"Memory recorded: {mapping.get('memory_written_path')}")
        return f"External | Apple Notes (General): {note_name}"
    except Exception as e:
        log_debug(f"❌ AppleScript Failed (General): {e}")
        return "❌ Err: AppleScript Fail"


def handle_memory(content):
    """
    Save user preference and attribute statements to My Preferences (e.g. coffee.md, skincare.md).
    Used only by the background preference save; not part of the main router.
    Uses pick_preferences_file_or_new, extract_preference_statements, save_preferences_to_memory.
    """
    log_memory_debug("Saving preferences/attributes to My Preferences...")
    ensure_dir(PREFERENCES_MEMORY_ROOT)
    md_files = list_md_files_in_folder(PREFERENCES_MEMORY_ROOT)
    memory_candidates = []
    for fp in md_files:
        rel = os.path.basename(fp)
        memory_candidates.append({
            "rel": rel,
            "content": safe_read_text(fp, limit_chars=3000),
        })

    pick = pick_preferences_file_or_new(content, memory_candidates)
    statements = extract_preference_statements(content)
    if not statements or not statements.strip():
        log_memory_debug("No preference statements extracted; skipping write.")
        return "Preferences | (none extracted)"

    path = None
    if pick.get("use_existing"):
        path = save_preferences_to_memory(
            statements, use_existing_filename=pick["use_existing"]
        )
        name = pick["use_existing"]
    else:
        path = save_preferences_to_memory(
            statements,
            new_filename=pick.get("new_filename"),
            topic=pick.get("topic"),
        )
        name = pick.get("new_filename", "preferences.md")

    if not path:
        return "Preferences | (write failed)"
    log_memory_debug(f"💾 Preferences saved -> {name}")
    return f"Preferences | {name}"


def run_preference_save_in_background(content):
    """
    Enqueue preference extraction task. Does not block; note sorting is unaffected.
    Call after main router operations so the same note still goes to daily/zettel,
    while a worker writes to e.g. skincare.md or coffee.md.
    """
    if not content or not str(content).strip():
        return
    from .task_queue import enqueue_preference_extract

    if enqueue_preference_extract(content):
        log_memory_debug("🐢 Preference extract enqueued.")


def run_temporal_memory_save_in_background(content):
    """
    Enqueue task to write AI observation from note content to today's daily file.
    Does not block; note sorting is unaffected.
    """
    if not content or not str(content).strip():
        return
    from .task_queue import enqueue_ai_observation

    if enqueue_ai_observation("Processed user note", content):
        log_memory_debug("🐢 Temporal memory save enqueued.")


def run_ai_observation_to_temporal_in_background(event_description, content=None):
    """
    Enqueue task to write an AI observation (routing event) to temporal memories.
    event_description: e.g. "Routed to daily journal", "Captured new idea"
    content: optional note content; when provided, the observation combines event and content.
    Does not block; note sorting is unaffected.
    """
    if not event_description or not str(event_description).strip():
        return
    from .task_queue import enqueue_ai_observation

    if enqueue_ai_observation(event_description, content):
        log_memory_debug(f"🐢 AI observation enqueued: {event_description[:50]}...")


def _increment_deduction_counter():
    """
    Increment calls_since_last_run in deduction state. Used by task queue worker.
    """
    try:
        import importlib.util
        import os

        # Module has hyphen in name, must use importlib
        module_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "deduction-heartbeat.py"
        )
        spec = importlib.util.spec_from_file_location(
            "deduction_heartbeat", module_path
        )
        deduction_heartbeat = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(deduction_heartbeat)

        deduction_heartbeat.increment_calls()
    except Exception as e:
        log_memory_debug(f"⚠️ Deduction increment failed: {e}")
        raise


def _append_zettelkasten_ai_sections(
    created_file_path,
    cleaned_text,
    breakdown_only=False,
    analysis_only=False,
):
    """
    Run zettelkasten --background to append Breakdown + Analysis to the note.
    Used by task queue worker. Blocks until complete (worker runs this in task).
    breakdown_only/analysis_only: run only that part (when True).
    """
    if not os.path.isfile(ZETTELKASTEN_SCRIPT_PATH):
        log_memory_debug("⚠️ Zettelkasten script not found; skipping.")
        return
    cmd = [
        PYTHON_EXEC,
        ZETTELKASTEN_SCRIPT_PATH,
        "--background",
        created_file_path,
        cleaned_text,
        "true" if breakdown_only else "false",
        "true" if analysis_only else "false",
    ]
    subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        timeout=600,
    )


def run_deduction_increment_in_background():
    """
    Enqueue task to increment the deduction call counter (calls_since_last_run).
    Used by the note classifier so the deduction heartbeat can run after enough "data events".
    """
    from .task_queue import enqueue_deduction_increment

    enqueue_deduction_increment()
    log_memory_debug("🐢 Deduction increment enqueued.")
