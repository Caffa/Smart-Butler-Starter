"""
Task queue (local event bus) using Huey with Redis backend and task priorities.
Replaces fire-and-forget subprocess calls with persistent, retryable tasks.
Falls back to SqliteHuey if Redis is unavailable.
"""

from .types import HUEY_REDIS_URL, QUEUE_DB_PATH

_huey = None


def _create_huey():
    try:
        from huey import PriorityRedisHuey
        return PriorityRedisHuey(
            url=HUEY_REDIS_URL,
            immediate=False,
        )
    except Exception:
        from huey import SqliteHuey
        return SqliteHuey(filename=QUEUE_DB_PATH, immediate=False)


huey = _create_huey()

# Task type constants
TASK_AI_OBSERVATION = "ai_observation"
TASK_PREFERENCE_EXTRACT = "preference_extract"
TASK_DEDUCTION_INCREMENT = "deduction_increment"
TASK_DEDUCTION_HEARTBEAT = "deduction_heartbeat"
TASK_ZETTELKASTEN_BACKGROUND = "zettelkasten_background"
TASK_EVOLUTION_LOG = "evolution_log"
TASK_YOUTUBE_REFERENCE = "youtube_reference"
TASK_CONTEXT_AWARE_REPORT_SUMMARY = "context_aware_report_summary"


def _ensure_worker_running():
    """Start on-demand worker if not already running."""
    try:
        from . import worker_launcher
        worker_launcher.ensure_worker_running()
    except Exception:
        pass


def enqueue_ai_observation(event_description, content=None):
    """Enqueue AI observation task with request cache check."""
    from .cache_manager import get_cache_manager
    cache = get_cache_manager()
    task_key = f"{event_description}:{content or ''}"
    if not cache.should_process_request(task_key, TASK_AI_OBSERVATION):
        return False
    from .task_handlers import task_ai_observation
    task_ai_observation(event_description, content)
    _ensure_worker_running()
    return True


def enqueue_preference_extract(content):
    """Enqueue preference extraction with request cache check."""
    from .cache_manager import get_cache_manager
    cache = get_cache_manager()
    if not content or not str(content).strip():
        return False
    if not cache.should_process_request(content, TASK_PREFERENCE_EXTRACT):
        return False
    from .task_handlers import task_preference_extract
    task_preference_extract(content)
    _ensure_worker_running()
    return True


def enqueue_diary_memory(content):
    """Enqueue diary memory processing (priority 9)."""
    if not content or not str(content).strip():
        return False
    from .task_handlers import task_diary_memory
    task_diary_memory(content)
    _ensure_worker_running()
    return True


def enqueue_deduction_increment():
    """Enqueue deduction counter increment (no cache needed)."""
    from .task_handlers import task_deduction_increment
    task_deduction_increment()
    _ensure_worker_running()
    return True


def enqueue_deduction_heartbeat():
    """Enqueue deduction heartbeat (run when idle). Returns Result handle so caller can save result.id for revoke on force."""
    from .task_handlers import task_deduction_heartbeat
    result = task_deduction_heartbeat()
    _ensure_worker_running()
    return result


def enqueue_zettelkasten_cleanup(raw_content, file_path, original_content=None):
    """Enqueue zettelkasten cleanup (priority 10); cleanup enqueues breakdown (priority 2).
    When original_content is provided, only that portion is LLM-cleaned (header/summary preserved)."""
    from .cache_manager import IdempotencyManager
    from .types import CACHE_DB_PATH
    idem = IdempotencyManager(db_path=CACHE_DB_PATH)
    op_id = idem.generate_operation_id(raw_content, "zettelkasten_cleanup")
    try:
        idem.check_and_record(op_id, "zettelkasten_cleanup", raw_content, file_path)
    except ValueError:
        from .memory import log_memory_debug
        log_memory_debug("⚠️ Duplicate zettelkasten cleanup task skipped (idempotency).")
        return False
    from .task_handlers import task_zettelkasten_cleanup
    task_zettelkasten_cleanup(raw_content, file_path, original_content=original_content)
    _ensure_worker_running()
    return True


def enqueue_zettelkasten_background(
    created_file_path, cleaned_text,
    breakdown_only=False, analysis_only=False,
    op_suffix="",
):
    """Enqueue zettelkasten breakdown (Breakdown + Analysis). Priority 2.
    op_suffix: appended to operation type for idempotency (e.g. '_bd', '_kore') so heartbeat runs don't collide."""
    from .cache_manager import IdempotencyManager
    from .types import CACHE_DB_PATH
    idem = IdempotencyManager(db_path=CACHE_DB_PATH)
    op_type = "zettelkasten_bg" + (op_suffix or "")
    op_id = idem.generate_operation_id(cleaned_text, op_type)
    try:
        idem.check_and_record(op_id, op_type, cleaned_text, created_file_path)
    except ValueError:
        from .memory import log_memory_debug
        log_memory_debug("⚠️ Duplicate zettelkasten task skipped (idempotency).")
        return False
    from .task_handlers import task_zettelkasten_background
    task_zettelkasten_background(
        created_file_path, cleaned_text,
        breakdown_only=breakdown_only,
        analysis_only=analysis_only,
    )
    _ensure_worker_running()
    return True


def enqueue_evolution_log():
    """Enqueue supervisor-dev evolution log (night-only, run when idle)."""
    from Self_Analysis.task_handlers import task_evolution_log
    task_evolution_log()
    _ensure_worker_running()
    return True


def enqueue_youtube_reference(raw_transcript, uploader, title, video_id, url):
    """Enqueue YouTube reference note processing (LLM cleanup + summary + file write)."""
    from .cache_manager import IdempotencyManager
    from .types import CACHE_DB_PATH

    idem = IdempotencyManager(db_path=CACHE_DB_PATH)
    op_id = idem.generate_operation_id(video_id, "youtube_ref")
    try:
        idem.check_and_record(op_id, "youtube_ref", video_id, title)
    except ValueError:
        from .memory import log_memory_debug

        log_memory_debug(f"⚠️ Duplicate YouTube reference task skipped: {video_id}")
        return False

    # Log worker health before heavy task
    from . import worker_launcher
    worker_launcher.log_worker_health(f"youtube_ref:{video_id}")

    from .task_handlers import task_youtube_reference

    task_youtube_reference(raw_transcript, uploader, title, video_id, url)
    _ensure_worker_running()
    return True


def enqueue_context_aware_report_summary(
    op_type, original_text, path, source_datetime=None, event_description=""
):
    """
    Enqueue task to produce a context-aware summary (Information on Moi + optional Temporal),
    then write the diary entry and optionally send to AI observation.
    op_type: use_experiment_log | use_dev_log | use_zettel_script
    """
    from .task_handlers import task_context_aware_report_summary
    task_context_aware_report_summary(
        op_type=op_type,
        original_text=original_text or "",
        path=path or "",
        source_datetime=source_datetime,
        event_description=event_description or "Report note",
    )
    _ensure_worker_running()
    return True
