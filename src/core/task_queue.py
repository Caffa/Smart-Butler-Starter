"""Task queue with Huey for background processing.

Provides a lightweight task queue using SQLite for persistence,
enabling crash recovery and background job processing.

Usage:
    from src.core.task_queue import task, queue, periodic_task

    @task(retries=3)
    def process_audio(audio_path: str) -> str:
        # Background processing
        return "transcribed text"

    # Schedule task
    result = process_audio.schedule(args=["/path/to/audio.mp3"])

    # Periodic task
    @periodic_task(crontab(hour=23))
    def nightly_digest():
        # Runs every night at 11 PM
        pass
"""

from __future__ import annotations

import functools
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

from huey import SqliteHuey, crontab
from huey.api import Result, Task

logger = logging.getLogger(__name__)

# Type variable for decorated functions
F = TypeVar("F", bound=Callable[..., Any])

# Global Huey instance - initialized lazily
_huey: Optional[SqliteHuey] = None


def get_huey(db_path: Optional[Path] = None) -> SqliteHuey:
    """Get or create the Huey instance.

    Args:
        db_path: Path to SQLite database (default: ~/.butler/data/tasks.db)

    Returns:
        SqliteHuey instance
    """
    global _huey
    if _huey is None:
        if db_path is None:
            db_path = Path.home() / ".butler" / "data" / "tasks.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _huey = SqliteHuey(
            filename=str(db_path),
            results=True,  # Store results for crash recovery
            store_none=False,
            immediate=False,  # Use consumer mode (background processing)
        )
        logger.debug(f"Initialized Huey task queue at {db_path}")
    return _huey


def reset_huey() -> None:
    """Reset the global Huey instance.

    Useful for testing.
    """
    global _huey
    _huey = None


# Convenience alias for the queue
queue = get_huey


def task(
    func: Optional[F] = None,
    *,
    retries: int = 3,
    retry_delay: int = 60,
    priority: int = 0,
    context: bool = False,
    name: Optional[str] = None,
    expires: Optional[int | timedelta] = None,
) -> Callable[[F], F] | F:
    """Decorator to register a function as a Huey task.

    Args:
        func: Function to decorate (if used without parentheses)
        retries: Number of retry attempts on failure (default: 3)
        retry_delay: Seconds between retries (default: 60)
        priority: Task priority (higher = more important)
        context: If True, task receives TaskContext as first arg
        name: Custom task name (default: function name)
        expires: Task expiration time in seconds or timedelta

    Returns:
        Decorated function with .schedule() and .call_local() methods

    Example:
        @task(retries=5, retry_delay=120)
        def process_large_file(path: str) -> dict:
            # Background processing
            return {"status": "done"}

        # Schedule for background processing
        result = process_large_file.schedule(args=["/path/to/file"])

        # Execute immediately (blocking, for testing)
        result = process_large_file.call_local("/path/to/file")
    """
    huey = get_huey()

    def decorator(fn: F) -> F:
        task_decorator = huey.task(
            retries=retries,
            retry_delay=retry_delay,
            priority=priority,
            context=context,
            name=name,
            expires=expires,
        )
        return task_decorator(fn)

    if func is not None:
        return decorator(func)
    return decorator


def periodic_task(
    func: Optional[F] = None,
    *,
    validate_datetime: Optional[Callable] = None,
    retries: int = 0,
    retry_delay: int = 60,
    priority: int = 0,
    context: bool = False,
    name: Optional[str] = None,
    expires: Optional[int | timedelta] = None,
) -> Callable[[F], F] | F:
    """Decorator to register a periodic task.

    Args:
        func: Function to decorate
        validate_datetime: Callable returning True if task should run
        retries: Number of retry attempts
        retry_delay: Seconds between retries
        priority: Task priority
        context: If True, receives TaskContext
        name: Custom task name
        expires: Task expiration time

    Returns:
        Decorated function

    Example:
        @periodic_task(crontab(hour=23, minute=0))
        def nightly_digest():
            # Runs every night at 11 PM
            pass

        @periodic_task(crontab(minute="*/15"))
        def heartbeat():
            # Runs every 15 minutes
            pass
    """
    huey = get_huey()

    def decorator(fn: F) -> F:
        task_decorator = huey.periodic_task(
            validate_datetime=validate_datetime,
            retries=retries,
            retry_delay=retry_delay,
            priority=priority,
            context=context,
            name=name,
            expires=expires,
        )
        return task_decorator(fn)

    if func is not None:
        return decorator(func)
    return decorator


def schedule_task(
    fn: Callable,
    args: Optional[tuple] = None,
    kwargs: Optional[dict] = None,
    delay: Optional[int | timedelta] = None,
    eta: Optional[Any] = None,
    priority: Optional[int] = None,
    retries: Optional[int] = None,
    retry_delay: Optional[int] = None,
    expires: Optional[int | timedelta] = None,
) -> Result:
    """Schedule a task for execution.

    Args:
        fn: Task function to schedule
        args: Positional arguments
        kwargs: Keyword arguments
        delay: Delay in seconds or timedelta before execution
        eta: Specific datetime to execute
        priority: Override task priority
        retries: Override retry count
        retry_delay: Override retry delay
        expires: Task expiration

    Returns:
        Result object for tracking execution

    Example:
        result = schedule_task(
            process_audio,
            args=["/path/to/audio.mp3"],
            delay=timedelta(minutes=5),
        )
    """
    return fn.schedule(
        args=args or (),
        kwargs=kwargs or {},
        delay=delay,
        eta=eta,
        priority=priority,
        retries=retries,
        retry_delay=retry_delay,
        expires=expires,
    )


def get_task_result(task_id: str) -> Optional[Any]:
    """Get the result of a completed task.

    Args:
        task_id: Task identifier

    Returns:
        Task result or None if not complete
    """
    huey = get_huey()
    result = Result(task_id, huey)
    return result.get(preserve=True)


def revoke_task(task_id: str) -> bool:
    """Revoke a pending task.

    Args:
        task_id: Task to revoke

    Returns:
        True if task was revoked
    """
    huey = get_huey()
    return huey.revoke_by_id(task_id)


def get_pending_tasks() -> list[Task]:
    """Get list of pending tasks.

    Returns:
        List of pending Task objects
    """
    huey = get_huey()
    return huey.pending()


def get_scheduled_tasks() -> list[Task]:
    """Get list of scheduled tasks.

    Returns:
        List of scheduled Task objects
    """
    huey = get_huey()
    return huey.scheduled()


def flush_queue() -> int:
    """Flush all pending and scheduled tasks.

    Returns:
        Number of tasks flushed
    """
    huey = get_huey()
    count = 0
    # Flush pending
    while huey.pending():
        task = huey.dequeue()
        if task:
            count += 1
    # Flush scheduled
    for task in huey.scheduled()[:]:
        huey.revoke_by_id(task.id)
        count += 1
    return count


__all__ = [
    "queue",
    "task",
    "periodic_task",
    "schedule_task",
    "get_task_result",
    "revoke_task",
    "get_pending_tasks",
    "get_scheduled_tasks",
    "flush_queue",
    "get_huey",
    "reset_huey",
    "crontab",
]
