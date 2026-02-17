"""
On-demand Huey worker: start worker when tasks are enqueued, worker exits when idle.
Includes health monitoring for diagnosing crashes and hangs.
"""

import os
import subprocess
import sys
from datetime import datetime


def _script_dir():
    """Note Sorting Scripts directory (parent of src)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _worker_script():
    """Path to run_huey_worker.py."""
    return os.path.join(_script_dir(), "run_huey_worker.py")


def _log_worker_event(message):
    """Log worker events to the audit log."""
    try:
        from .memory import log_debug
        log_debug(f"[Worker] {message}")
    except Exception:
        pass


def get_worker_pid():
    """Get PID of running Huey worker, or None if not running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "run_huey_worker"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.stdout and result.stdout.strip():
            # Return first PID if multiple (shouldn't happen)
            pids = result.stdout.strip().split("\n")
            return int(pids[0])
        return None
    except Exception:
        return None


def is_worker_running():
    """True if Huey consumer process is already running."""
    return get_worker_pid() is not None


def get_worker_status():
    """
    Get detailed worker status for health monitoring.
    Returns dict with: running, pid, uptime_seconds (if available).
    """
    pid = get_worker_pid()
    if not pid:
        return {"running": False, "pid": None, "uptime_seconds": None}
    
    status = {"running": True, "pid": pid, "uptime_seconds": None}
    
    # Try to get uptime via ps
    try:
        result = subprocess.run(
            ["ps", "-o", "etime=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.stdout and result.stdout.strip():
            etime = result.stdout.strip()
            # Parse elapsed time (format: [[DD-]HH:]MM:SS)
            parts = etime.replace("-", ":").split(":")
            parts = [int(p) for p in parts]
            if len(parts) == 2:  # MM:SS
                status["uptime_seconds"] = parts[0] * 60 + parts[1]
            elif len(parts) == 3:  # HH:MM:SS
                status["uptime_seconds"] = parts[0] * 3600 + parts[1] * 60 + parts[2]
            elif len(parts) == 4:  # DD:HH:MM:SS
                status["uptime_seconds"] = parts[0] * 86400 + parts[1] * 3600 + parts[2] * 60 + parts[3]
    except Exception:
        pass
    
    return status


def start_worker():
    """Start Huey worker as background process."""
    script = _worker_script()
    if not os.path.isfile(script):
        _log_worker_event("⚠️ Worker script not found, cannot start")
        return False
    try:
        process = subprocess.Popen(
            [sys.executable, script],
            cwd=_script_dir(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _log_worker_event(f"🚀 Worker started (launcher PID: {process.pid})")
        return True
    except Exception as e:
        _log_worker_event(f"❌ Worker start failed: {e}")
        return False


def ensure_worker_running():
    """Start worker if not already running. Called by enqueue functions."""
    if not is_worker_running():
        start_worker()


def log_worker_health(task_name=""):
    """
    Log current worker health status. Call before heavy tasks for diagnostics.
    Returns True if worker is healthy, False otherwise.
    """
    status = get_worker_status()
    
    if not status["running"]:
        _log_worker_event(f"⚠️ Worker not running (task: {task_name})")
        return False
    
    uptime_str = ""
    if status["uptime_seconds"] is not None:
        mins = status["uptime_seconds"] // 60
        secs = status["uptime_seconds"] % 60
        uptime_str = f", uptime: {mins}m{secs}s"
    
    _log_worker_event(f"✓ Worker healthy (PID: {status['pid']}{uptime_str}) - task: {task_name}")
    return True


def check_and_restart_worker():
    """
    Check if worker is running, restart if not.
    Returns status dict with 'was_running' and 'now_running' flags.
    """
    was_running = is_worker_running()
    
    if not was_running:
        _log_worker_event("Worker not running, attempting restart...")
        start_worker()
        # Give it a moment to start
        import time
        time.sleep(0.5)
    
    now_running = is_worker_running()
    
    return {
        "was_running": was_running,
        "now_running": now_running,
        "restarted": not was_running and now_running,
    }
