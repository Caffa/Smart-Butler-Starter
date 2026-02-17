"""
Workflow status for menu bar display and butler reporting.

- State: JSON files in ~/Library/Application Support/NoteRouter/active/ (for menu bar app).
- Butler report: Rich-formatted block to ~/Desktop/human_readable_butler_report.log.
- Verbose line: One line per run to VERBOSE_LOG_PATH (main.log) with run_id, conclusion, step chain.

NOTE_ROUTER_MENUBAR: Only affects the menubar app (whether it shows or runs). Workflow state
is always written so the menubar can show activity when enabled. Set to "0" to disable the
menubar app; unset or "1" for normal behavior.
"""

import datetime
import fcntl
import json
import os
import tempfile
import uuid

# In-memory step history per workflow_id (for butler report and verbose line)
_workflows: dict[str, dict] = {}

# Paths
_STATE_DIR_ENV = "NOTE_ROUTER_WORKFLOW_STATE_DIR"
_MENUBAR_DISABLED_ENV = "NOTE_ROUTER_MENUBAR"
_RECENT_MAX = 5
BUTLER_REPORT_PATH = os.path.join(os.path.expanduser("~"), "Desktop", "human_readable_butler_report.log")


def _get_state_dir():
    """State is always written so the menubar can show activity. NOTE_ROUTER_MENUBAR only affects the menubar app."""
    return get_state_dir_for_polling()


def get_state_dir_for_polling() -> str:
    """Directory where workflow state JSON files live (for menu bar app polling)."""
    return os.environ.get(_STATE_DIR_ENV) or os.path.join(
        os.path.expanduser("~"), "Library", "Application Support", "NoteRouter", "active"
    )


def _timestamp_short():
    return datetime.datetime.now().strftime("%m-%d %H:%M:%S")


def _timestamp_iso():
    return datetime.datetime.now().isoformat()


def _log_write_error(message: str) -> None:
    """Log workflow_status write failures for debugging."""
    try:
        state_dir = get_state_dir_for_polling()
        parent = os.path.dirname(state_dir)
        os.makedirs(parent, exist_ok=True)
        log_path = os.path.join(parent, "workflow_status_errors.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{_timestamp_short()}] {message}\n")
    except Exception:
        pass


def _write_state_file(workflow_id: str, data: dict) -> None:
    state_dir = _get_state_dir()
    if not state_dir:
        return
    try:
        os.makedirs(state_dir, exist_ok=True)
        path = os.path.join(state_dir, f"{workflow_id}.json")
        fd, tmp = tempfile.mkstemp(dir=state_dir, prefix=".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception as e:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise
    except Exception as e:
        _log_write_error(f"write_state_file {workflow_id}: {e}")


def _delete_state_file(workflow_id: str) -> None:
    state_dir = _get_state_dir()
    if not state_dir:
        return
    try:
        path = os.path.join(state_dir, f"{workflow_id}.json")
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def _append_butler_report_block(
    workflow_id: str,
    workflow_type: str,
    label: str | None,
    started_at: str,
    ended_at: str,
    steps: list,
    success: bool,
    summary: str | None,
    input_text: str | None = None,
) -> None:
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
    except ImportError:
        return
    try:
        duration = ""
        try:
            start_dt = datetime.datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            end_dt = datetime.datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
            if start_dt.tzinfo:
                start_dt = start_dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            if end_dt.tzinfo:
                end_dt = end_dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            delta = end_dt - start_dt
            duration = f"{delta.total_seconds():.1f}s"
        except Exception:
            duration = "—"

        # Per-step durations: step i runs from steps[i] timestamp until steps[i+1] or ended_at
        step_lines = []
        if steps:
            try:
                end_dt = datetime.datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
                if end_dt.tzinfo:
                    end_dt = end_dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
                for i, (step_name, ts_str) in enumerate(steps):
                    try:
                        t = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if t.tzinfo:
                            t = t.astimezone(datetime.timezone.utc).replace(tzinfo=None)
                        if i + 1 < len(steps):
                            next_ts = datetime.datetime.fromisoformat(steps[i + 1][1].replace("Z", "+00:00"))
                            if next_ts.tzinfo:
                                next_ts = next_ts.astimezone(datetime.timezone.utc).replace(tzinfo=None)
                            secs = (next_ts - t).total_seconds()
                        else:
                            secs = (end_dt - t).total_seconds()
                        step_lines.append(f"  {step_name} ({secs:.1f}s)")
                    except Exception:
                        step_lines.append(f"  {step_name}")
            except Exception:
                step_lines = [f"  {s[0]}" for s in steps]
        else:
            step_lines = ["  (no steps)"]

        outcome = "success" if success else "failed"
        outcome_style = "green" if success else "red"

        table = Table(show_header=False)
        table.add_column(style="dim")
        table.add_column()
        table.add_row("run_id", workflow_id)
        table.add_row("type", workflow_type)
        if label:
            table.add_row("label", label)
        if input_text:
            truncated = (input_text.strip()[:500] + "…") if len(input_text.strip()) > 500 else input_text.strip()
            table.add_row("input_text", truncated)
        table.add_row("started", started_at)
        table.add_row("ended", ended_at)
        table.add_row("duration", duration)
        table.add_row("outcome", Text(outcome, style=outcome_style))
        if summary:
            table.add_row("summary", summary)
        table.add_row("steps", "\n".join(step_lines))

        title = Text(f"Butler run {workflow_id[:8]}… ", style="bold") + Text(outcome, style=outcome_style)
        panel = Panel(table, title=title, border_style="dim")

        with open(BUTLER_REPORT_PATH, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                console = Console(file=f, force_terminal=True)
                console.print(panel)
                console.print()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        try:
            with open(BUTLER_REPORT_PATH, "a", encoding="utf-8") as f:
                f.write(f"[{_timestamp_short()}] [Butler] write error: {e}\n")
        except Exception:
            pass


def get_recent_workflows_path() -> str:
    """Path to JSON file holding last N completed workflows for menubar history."""
    state_dir = get_state_dir_for_polling()
    parent = os.path.dirname(state_dir)
    return os.path.join(parent, "recent_workflows.json")


def _get_recent_workflows_path() -> str:
    return get_recent_workflows_path()


def _append_recent_workflow(workflow_id: str, workflow_type: str, label: str | None, step_chain: str, success: bool, summary: str | None, ended_at: str) -> None:
    """Append a completed workflow to recent history (max _RECENT_MAX)."""
    path = _get_recent_workflows_path()
    try:
        data = {"recent": []}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
        rec = {
            "workflow_id": workflow_id,
            "type": workflow_type,
            "label": label or "",
            "step_chain": step_chain,
            "success": success,
            "summary": (summary or "").strip()[:80],
            "ended_at": ended_at,
        }
        data.setdefault("recent", [])
        data["recent"].insert(0, rec)
        data["recent"] = data["recent"][:_RECENT_MAX]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        _log_write_error(f"append_recent_workflow: {e}")


def _append_verbose_line(workflow_id: str, success: bool, step_chain: str) -> None:
    try:
        from .types import VERBOSE_LOG_PATH
    except ImportError:
        return
    try:
        verbose_dir = os.path.dirname(VERBOSE_LOG_PATH)
        if not os.path.exists(verbose_dir):
            os.makedirs(verbose_dir, exist_ok=True)
        conclusion = "success" if success else "failed"
        line = f"[{_timestamp_short()}] [Butler] run_id={workflow_id} {conclusion} | {step_chain}\n"
        with open(VERBOSE_LOG_PATH, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(line)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass


def workflow_start(workflow_type: str, label: str | None = None, input_text: str | None = None) -> str:
    """Start a workflow. Returns workflow_id. Writes state JSON for menu bar; records start in memory for butler report."""
    workflow_id = str(uuid.uuid4())
    now = _timestamp_iso()
    data = {
        "type": workflow_type,
        "label": label or "",
        "step": "started",
        "started_at": now,
        "steps": ["started"],
    }
    if input_text is not None:
        data["input_text"] = input_text
    _workflows[workflow_id] = {
        "type": workflow_type,
        "label": label,
        "started_at": now,
        "steps": [],
    }
    if input_text is not None:
        _workflows[workflow_id]["input_text"] = input_text
    _write_state_file(workflow_id, data)
    return workflow_id


def workflow_step(workflow_id: str, step: str) -> None:
    """Update current step for the workflow. Updates state JSON and appends to in-memory step list for butler report."""
    now = _timestamp_iso()
    if workflow_id in _workflows:
        _workflows[workflow_id]["steps"].append((step, now))
    state_dir = _get_state_dir()
    if not state_dir:
        return
    path = os.path.join(state_dir, f"{workflow_id}.json")
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["step"] = step
        data["updated_at"] = now
        data.setdefault("steps", [])
        data["steps"].append(step)
        _write_state_file(workflow_id, data)
    except Exception:
        pass


def workflow_end(workflow_id: str, success: bool = True, summary: str | None = None) -> None:
    """End the workflow: remove state file, write butler report block (Desktop), append verbose line (main.log)."""
    _delete_state_file(workflow_id)
    if workflow_id not in _workflows:
        return
    rec = _workflows.pop(workflow_id)
    started_at = rec["started_at"]
    ended_at = _timestamp_iso()
    steps = rec["steps"]
    step_chain = " → ".join(s[0] for s in steps) if steps else "(no steps)"
    _append_butler_report_block(
        workflow_id=workflow_id,
        workflow_type=rec["type"],
        label=rec.get("label"),
        started_at=started_at,
        ended_at=ended_at,
        steps=steps,
        success=success,
        summary=summary,
        input_text=rec.get("input_text"),
    )
    _append_verbose_line(workflow_id, success, step_chain)
    _append_recent_workflow(
        workflow_id,
        rec["type"],
        rec.get("label"),
        step_chain,
        success,
        summary,
        ended_at,
    )
