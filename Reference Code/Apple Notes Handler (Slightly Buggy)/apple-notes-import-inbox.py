#!/usr/bin/env python3
"""
Import lines from an Apple Note into the note router (same flow as voice-memo/Alfred).
Reads a configured note by title, splits body by newlines, processes each line through
get_router_plan + execute_action + background tasks, then clears the note body so only
the title remains.

Run periodically via Keyboard Maestro or launchd.
"""

import argparse
import re
import subprocess
import sys

import note_router_core_2026_01_28 as core
from src import workflow_status

# Default note title to watch (user can override via --note)
DEFAULT_NOTE_TITLE = "Notes for AI Import"


def get_note_body_via_applescript(note_title: str) -> str | None:
    """
    Read the body of an Apple Note by title from the default account.
    Returns the HTML body content. Returns None if an error occurs.
    """
    # Escape quotes for AppleScript string
    safe_title = note_title.replace('"', '\\"')

    script = f'''
    tell application "Notes"
        tell default account
            if not (exists note "{safe_title}") then
                make new note with properties {{name: "{safe_title}", body: ""}}
                return "CREATED_NEW_NOTE"
            end if
            -- Get HTML body directly
            return body of note "{safe_title}"
        end tell
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Check for stderr (AppleScript runtime errors)
        if result.returncode != 0:
            core.log_debug(f"AppleScript Error: {result.stderr.strip()}")
            return None

        out = (result.stdout or "").strip()

        if out == "CREATED_NEW_NOTE":
            return ""

        return out

    except subprocess.TimeoutExpired:
        core.log_debug("AppleScript timed out reading note.")
        return None
    except Exception as e:
        core.log_debug(f"Python exception running AppleScript: {e}")
        return None


def set_note_body_via_applescript(note_title: str, body: str) -> bool:
    """Set the body of an Apple Note by title. Use empty string to leave only the title."""
    safe_title = note_title.replace('"', '\\"')
    # Notes expects HTML; use a single space if empty to prevent UI glitches
    safe_body = (
        (body or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    )
    if not safe_body.strip():
        safe_body = " "

    script = f'''
    tell application "Notes"
        tell default account
            if (exists note "{safe_title}") then
                set body of note "{safe_title}" to "{safe_body}"
            end if
        end tell
    end tell
    '''
    try:
        subprocess.run(
            ["osascript", "-e", script], check=True, timeout=15, capture_output=True
        )
        return True
    except subprocess.CalledProcessError as e:
        core.log_debug(f"Failed to clear note: {e.stderr.decode().strip()}")
        return False


def html_to_plain_lines(html: str) -> list[str]:
    """Convert note body HTML to a list of non-empty plain-text lines."""
    if not html or not html.strip():
        return []

    text = html

    # 1. Replace <div> and <br> with newlines to preserve structure
    text = re.sub(r"</div>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)

    # 2. Extract URLs from <a> tags so they aren't lost when stripping tags
    # Example: <a href="http://google.com">link</a> -> link (http://google.com)
    # This regex is simplistic; for complex HTML, use a real parser (like BeautifulSoup),
    # but for Apple Notes valid HTML, this usually suffices.
    # text = re.sub(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', r'\2 (\1)', text, flags=re.IGNORECASE)

    # 3. Remove all remaining tags
    text = re.sub(r"<[^>]+>", "", text)

    # 4. Decode common entities
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("’", "'")
    )

    # 5. Split by lines and clean up
    lines = []
    for ln in text.splitlines():
        clean = ln.strip()
        if clean:
            lines.append(clean)

    return lines


def process_one_line(line: str) -> list[str]:
    """Run the same flow as the Alfred voice-memo script for one line (with reference resolution)."""
    wid = workflow_status.workflow_start("routing")
    try:
        workflow_status.workflow_step(wid, "Resolving references")
        _, append_to_path, resolved_refs = core.run_reference_resolution(line)
        msgs = []
        if append_to_path:
            workflow_status.workflow_step(wid, "Executing: zettel append")
            msg = core.execute_action(
                "use_zettel_append", append_to_path, line, line, resolved_refs=None
            )
            msgs.append(msg)
        else:
            workflow_status.workflow_step(wid, "AI routing")
            plan = core.get_router_plan(line)
            plan = core.consolidate_router_plan(plan)
            plan_op_types = [op.type for op in plan.operations]
            for op in plan.operations:
                workflow_status.workflow_step(wid, f"Executing: {op.type}")
                msg = core.execute_action(
                    op.type,
                    op.path,
                    op.content,
                    line,
                    extra_paths=getattr(op, "extra_paths", None),
                    summary=getattr(op, "summary", None) or "",
                    resolved_refs=resolved_refs or None,
                    plan_operation_types=plan_op_types,
                )
                msgs.append(msg)
        core.run_preference_save_in_background(line)
        core.run_temporal_memory_save_in_background(line)
        core.run_deduction_increment_in_background()
        workflow_status.workflow_end(
            wid, success=True, summary=", ".join(msgs)[:80] if msgs else None
        )
        return msgs
    except Exception as e:
        workflow_status.workflow_end(wid, success=False, summary=str(e)[:80])
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import lines from an Apple Note into the note router, then clear the note body."
    )
    parser.add_argument(
        "--note",
        default=DEFAULT_NOTE_TITLE,
        help=f"Apple Note title to read (default: {DEFAULT_NOTE_TITLE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and list lines only; do not process or clear the note",
    )
    args = parser.parse_args()

    # Get Body
    body = get_note_body_via_applescript(args.note)

    if body is None:
        # We allow the error log inside the function to print details
        print(
            f"Error: Could not read note '{args.note}'. See logs or stderr for details.",
            file=sys.stderr,
        )
        sys.exit(1)

    lines = html_to_plain_lines(body)

    # Skip title if it appears in body (common Apple Notes behavior)
    if lines and args.note.strip() in lines[0]:
        lines = lines[1:]

    if not lines:
        if args.dry_run:
            print("Note is empty.")
        sys.exit(0)

    core.log_run_start("Apple Notes Import Inbox")

    if args.dry_run:
        for i, ln in enumerate(lines, 1):
            print(f"  {i}: {core.snippet(ln)}")
        print(
            f"Dry run: {len(lines)} line(s). Run without --dry-run to process and clear."
        )
        sys.exit(0)

    success_count = 0
    errors = []

    # Process lines
    for i, line in enumerate(lines):
        try:
            msgs = process_one_line(line)
            success_count += 1
            core.log_debug(f"  [{i + 1}] {', '.join(msgs)}")
        except Exception as e:
            errors.append((i + 1, str(e)))
            core.log_debug(f"  [{i + 1}] Error: {e}")

    # Clear Note
    if not set_note_body_via_applescript(args.note, ""):
        core.log_debug("Failed to clear note body.")
        errors.append((0, "Failed to clear note body"))

    if errors:
        print(
            f"Processed {success_count}/{len(lines)}; {len(errors)} error(s).",
            file=sys.stderr,
        )
        for idx, err in errors:
            print(f"  {idx}: {err}", file=sys.stderr)
        sys.exit(1)

    print(f"OK: imported {success_count} line(s), note body cleared.")


if __name__ == "__main__":
    main()
