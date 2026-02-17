#!/usr/bin/env python3
"""
Menu bar app for Note Router: shows active workflows, current step, and last 5 completed.
Poll workflow state from ~/Library/Application Support/NoteRouter/active/.

NOTE_ROUTER_MENUBAR: set to "0" to disable (minimal menu + Quit); unset or "1" for normal.
Only these entry points report to the menubar: note-classifier-llm-voice-memo (automator/alfred),
apple-notes-import-inbox, deduction-heartbeat, youtube_to_reference, zettelkasten-alfred-handler.
Run with: pythonw menubar_workflow_app.py  (or python; keep in foreground)
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

# Ensure we can import from src
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import rumps
from AppKit import NSApplication, NSImage

from src.workflow_status import BUTLER_REPORT_PATH, get_state_dir_for_polling, get_recent_workflows_path

try:
    from src.types import VERBOSE_LOG_PATH
except ImportError:
    VERBOSE_LOG_PATH = os.path.join(os.path.expanduser("~"), "Local Projects", "AI Memories", "Debug", "System Logs", "main.log")

# Icons (optional): if menubar/icons/ exists, use default.png and active.png
_ICONS_DIR = os.path.join(_SCRIPT_DIR, "menubar", "icons")
_DOCK_ICON = "/Users/caffae/Documents/Useful Archive/Useful Scripts/Note Sorting Scripts/menubar/app_icons/active.png"
_DEFAULT_ICON = os.path.join(_ICONS_DIR, "default.png") if os.path.isdir(_ICONS_DIR) else None
_ACTIVE_ICON = os.path.join(_ICONS_DIR, "active.png") if os.path.isdir(_ICONS_DIR) else None
_STALE_HOURS = 1  # ignore workflows older than this
_MENUBAR_DISABLED_ENV = "NOTE_ROUTER_MENUBAR"
_MAX_ERROR_LINES = 30


def _extract_error_block_for_run(log_path: str, workflow_id: str) -> str:
    """Read log_path, find line containing run_id=workflow_id, return that line plus following lines until next [Butler] or cap."""
    if not os.path.isfile(log_path):
        return ""
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return ""
    start = None
    for i, line in enumerate(lines):
        if workflow_id in line and ("run_id=" in line or "[Butler]" in line):
            start = i
            break
    if start is None:
        return ""
    end = start + 1
    for i in range(start + 1, min(start + _MAX_ERROR_LINES, len(lines))):
        if "[Butler]" in lines[i]:
            break
        end = i + 1
    return "".join(lines[start:end]).strip()


def _on_open_workflow(_, workflow_id: str, is_recent: bool, success: bool):
    """Open main.log (failure) and copy error to clipboard, or open butler report in Ghostty (success/active)."""
    if is_recent and not success:
        # Open main.log and copy error block to clipboard when we have a run id
        if workflow_id:
            block = _extract_error_block_for_run(VERBOSE_LOG_PATH, workflow_id)
            if block:
                try:
                    subprocess.run(["pbcopy"], input=block.encode("utf-8"), check=False)
                except Exception:
                    pass
        try:
            subprocess.run(["open", VERBOSE_LOG_PATH], check=False)
        except Exception:
            pass
    else:
        # Open butler report in Ghostty with tl
        path = BUTLER_REPORT_PATH
        if " " in path:
            cmd = ["ghostty", "-e", f'tl "{path}"']
        else:
            cmd = ["ghostty", "-e", f"tl {path}"]
        try:
            subprocess.Popen(cmd)
        except Exception:
            try:
                subprocess.run(["open", path], check=False)
            except Exception:
                pass


def _set_dock_icon(path):
    """Set the application dock icon from a PNG file path."""
    if not path or not os.path.isfile(path):
        return
    try:
        img = NSImage.alloc().initWithContentsOfFile_(path)
        if img is not None:
            NSApplication.sharedApplication().setApplicationIconImage_(img)
    except Exception:
        pass


def _load_workflows():
    """Load all workflow state JSON files; return (list of dicts sorted by started_at, state_dir_exists)."""
    state_dir = get_state_dir_for_polling()
    if not state_dir:
        return [], False
    if not os.path.isdir(state_dir):
        return [], False
    now = datetime.now()
    stale_cutoff = now - timedelta(hours=_STALE_HOURS)
    workflows = []
    for name in os.listdir(state_dir):
        if not name.endswith(".json"):
            continue
        path = os.path.join(state_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            started = data.get("started_at", "")
            try:
                started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                if started_dt.tzinfo is not None:
                    started_dt = started_dt.astimezone().replace(tzinfo=None)
                if started_dt < stale_cutoff:
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                    continue
            except Exception:
                pass
            data["workflow_id"] = name[:-5]
            workflows.append(data)
        except Exception:
            continue
    workflows.sort(key=lambda w: w.get("started_at", ""))
    return workflows, True


def _load_recent_workflows():
    """Load last 5 completed workflows from recent_workflows.json."""
    path = get_recent_workflows_path()
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("recent", [])[:5]
    except Exception:
        return []


class NoteRouterMenubarApp(rumps.App):
    def __init__(self):
        icon = _DEFAULT_ICON if _DEFAULT_ICON and os.path.isfile(_DEFAULT_ICON) else None
        super().__init__(
            name="Note Router",
            title="Note" if not icon else None,
            icon=icon,
            template=bool(icon),
            menu=[],
        )
        _set_dock_icon(_DOCK_ICON)
        self._menubar_disabled = os.environ.get(_MENUBAR_DISABLED_ENV) == "0"
        self._update_menu()
        _set_dock_icon(_DEFAULT_ICON)

    @rumps.timer(2)
    def _poll(self, _):
        self._update_menu()

    def _on_refresh(self, _):
        self._refresh_ui()

    def _refresh_ui(self):
        """Update menu and icon from current workflow state."""
        if self._menubar_disabled:
            items = [
                rumps.MenuItem("Menubar disabled (NOTE_ROUTER_MENUBAR=0)", callback=None),
                None,
                rumps.MenuItem("Quit", callback=lambda _: rumps.quit_application()),
            ]
            self.menu.clear()
            self.menu.update(items)
            return

        workflows, state_dir_exists = _load_workflows()
        state_dir = get_state_dir_for_polling()
        items = []

        if state_dir and not state_dir_exists:
            items.append(rumps.MenuItem("State directory not found", callback=None))

        for w in workflows:
            wtype = w.get("type", "?")
            step = w.get("step", "—")
            label = (w.get("label") or "").strip()
            if label:
                title = f"{wtype}: {label} — {step}"
            else:
                title = f"{wtype} — {step}"
            if len(title) > 60:
                title = title[:57] + "…"
            parent = rumps.MenuItem(title)
            steps_list = w.get("steps", [])
            for s in steps_list[:-1]:
                txt = (s[:47] + "…") if len(s) > 50 else s
                parent.add(rumps.MenuItem(txt, callback=None))
            if steps_list:
                curr = steps_list[-1]
                parent.add(rumps.MenuItem((curr[:47] + "…") if len(curr) > 50 else curr, callback=None))
            parent.add(None)
            wid = w.get("workflow_id", "")
            parent.add(rumps.MenuItem("Open report", callback=lambda _, wid=wid: _on_open_workflow(_, wid, False, True)))
            items.append(parent)
        if not workflows:
            items.append(rumps.MenuItem("No active workflows", callback=None))

        # Border and recent workflows (last 5)
        recent = _load_recent_workflows()
        if recent:
            items.append(None)
            items.append(rumps.MenuItem("——— Recent ———", callback=None))
            for r in recent:
                wtype = r.get("type", "?")
                label = (r.get("label") or "").strip()
                step_chain = r.get("step_chain", "—")
                success = r.get("success", True)
                sym = "✓" if success else "✗"
                if label:
                    title = f"{wtype}: {label} — {step_chain} {sym}"
                else:
                    title = f"{wtype} — {step_chain} {sym}"
                if len(title) > 60:
                    title = title[:57] + "…"
                parent = rumps.MenuItem(title)
                step_names = [s.strip() for s in step_chain.split(" → ")] if step_chain else []
                for s in step_names:
                    txt = (s[:47] + "…") if len(s) > 50 else s
                    parent.add(rumps.MenuItem(txt, callback=None))
                parent.add(rumps.MenuItem(sym, callback=None))
                parent.add(None)
                wid = r.get("workflow_id", "")
                action_label = "View log" if not success else "Open report"
                parent.add(rumps.MenuItem(action_label, callback=lambda _, wid=wid, success=success: _on_open_workflow(_, wid, True, success)))
                items.append(parent)

        items.extend([
            None,
            rumps.MenuItem("Refresh", callback=self._on_refresh),
            rumps.MenuItem("Quit", callback=lambda _: rumps.quit_application()),
        ])
        self.menu.clear()
        self.menu.update(items)
        # Update menubar and dock icons based on active workflows
        if workflows and _ACTIVE_ICON and os.path.isfile(_ACTIVE_ICON):
            self.icon = _ACTIVE_ICON
        elif _DEFAULT_ICON and os.path.isfile(_DEFAULT_ICON):
            self.icon = _DEFAULT_ICON
        else:
            self.title = "Note"
            self.icon = None
        _set_dock_icon(_DOCK_ICON)

    def _update_menu(self):
        self._refresh_ui()


def main():
    NoteRouterMenubarApp().run()


if __name__ == "__main__":
    main()
