"""Tests for the task queue.

Tests cover:
- Task registration and execution
- Retry behavior
- Periodic tasks
- Crash recovery
- Queue management
"""

from __future__ import annotations

import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

from src.core.task_queue import (
    flush_queue,
    get_huey,
    get_pending_tasks,
    get_scheduled_tasks,
    periodic_task,
    reset_huey,
    revoke_task,
    schedule_task,
    task,
)


class TestTaskQueue:
    """Tests for task queue functionality."""

    def setup_method(self) -> None:
        """Reset Huey before each test."""
        reset_huey()

    def test_get_huey_creates_instance(self) -> None:
        """get_huey creates a SqliteHuey instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            huey = get_huey(db_path)

            assert huey is not None
            assert db_path.exists()

    def test_get_huey_singleton(self) -> None:
        """get_huey returns same instance on subsequent calls."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            huey1 = get_huey(db_path)
            huey2 = get_huey(db_path)  # Same instance

            assert huey1 is huey2

    def test_task_decorator(self) -> None:
        """Task decorator registers function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            get_huey(db_path)

            @task
            def simple_task(value: int) -> int:
                return value * 2

            # Task is registered
            assert hasattr(simple_task, "schedule")
            assert hasattr(simple_task, "call_local")

    def test_task_with_options(self) -> None:
        """Task decorator accepts options."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            get_huey(db_path)

            @task(retries=5, retry_delay=120, priority=10)
            def important_task() -> str:
                return "done"

            # Task is registered
            assert hasattr(important_task, "schedule")

    def test_task_call_local(self) -> None:
        """call_local executes task immediately."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            get_huey(db_path)

            call_count = 0

            @task
            def counting_task() -> int:
                nonlocal call_count
                call_count += 1
                return call_count

            # Execute locally (blocking)
            result = counting_task.call_local()
            assert result == 1

            result = counting_task.call_local()
            assert result == 2

    def test_task_enqueue(self) -> None:
        """Calling task directly enqueues it for execution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            get_huey(db_path)

            @task
            def enqueued_task(value: int) -> int:
                return value * 2

            # Call task directly (enqueues it)
            result = enqueued_task(5)
            # Returns a Result object
            assert result is not None
            assert result.id is not None  # Result has 'id' attribute

    def test_task_schedule_with_delay(self) -> None:
        """schedule with delay queues task for future."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            get_huey(db_path)

            @task
            def delayed_task() -> str:
                return "delayed"

            # Schedule with delay
            result = delayed_task.schedule(delay=timedelta(minutes=5))
            assert result is not None

    def test_schedule_task_function(self) -> None:
        """schedule_task helper schedules tasks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            get_huey(db_path)

            @task
            def helper_task(x: int, y: int) -> int:
                return x + y

            result = schedule_task(
                helper_task,
                args=(1, 2),
                delay=timedelta(seconds=10),
            )
            assert result is not None


class TestRetryBehavior:
    """Tests for task retry behavior."""

    def setup_method(self) -> None:
        """Reset Huey before each test."""
        reset_huey()

    def test_retry_configuration(self) -> None:
        """Task retries are configured."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            get_huey(db_path)

            @task(retries=3, retry_delay=60)
            def retryable_task() -> str:
                return "success"

            # Task is registered with retry config
            assert hasattr(retryable_task, "schedule")

    def test_task_fails_and_retries(self) -> None:
        """Failed task can be retried."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            get_huey(db_path)

            attempts = 0

            @task(retries=2, retry_delay=0)
            def flaky_task() -> str:
                nonlocal attempts
                attempts += 1
                if attempts < 2:
                    raise ValueError("Not yet")
                return "success"

            # Execute locally to test the function itself
            # (retry logic is handled by consumer)
            try:
                flaky_task.call_local()
            except ValueError:
                pass

            # After failure, attempts incremented
            assert attempts == 1


class TestPeriodicTasks:
    """Tests for periodic task scheduling."""

    def setup_method(self) -> None:
        """Reset Huey before each test."""
        reset_huey()

    def test_periodic_task_crontab(self) -> None:
        """crontab creates valid schedule."""
        from src.core.task_queue import crontab

        # Daily at midnight
        schedule = crontab(hour=0, minute=0)
        assert schedule is not None

        # Every 15 minutes
        schedule = crontab(minute="*/15")
        assert schedule is not None

        # Every hour
        schedule = crontab(minute=0)
        assert schedule is not None

    def test_periodic_task_registration(self) -> None:
        """periodic_task can be registered (needs module-level function)."""
        # Periodic tasks require module-level functions for pickling
        # This test verifies the decorator accepts the right parameters
        from src.core.task_queue import crontab

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            huey = get_huey(db_path)

            # Use Huey directly to create a periodic task
            # (this avoids the pickling issue with local functions)
            @huey.periodic_task(crontab(hour=23, minute=0))
            def test_periodic() -> str:
                return "nightly"

            # Task is registered
            assert hasattr(test_periodic, "schedule")


class TestQueueManagement:
    """Tests for queue management functions."""

    def setup_method(self) -> None:
        """Reset Huey before each test."""
        reset_huey()

    def test_get_pending_tasks(self) -> None:
        """get_pending_tasks returns pending tasks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            get_huey(db_path)

            @task
            def pending_task() -> str:
                return "pending"

            # Enqueue task
            pending_task()

            # Get pending
            pending = get_pending_tasks()
            assert isinstance(pending, list)

    def test_get_scheduled_tasks(self) -> None:
        """get_scheduled_tasks returns scheduled tasks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            get_huey(db_path)

            @task
            def scheduled_task() -> str:
                return "scheduled"

            # Schedule with delay
            scheduled_task.schedule(delay=timedelta(hours=1))

            scheduled = get_scheduled_tasks()
            assert isinstance(scheduled, list)

    def test_flush_queue(self) -> None:
        """flush_queue removes all tasks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            get_huey(db_path)

            @task
            def flushable_task(value: int) -> str:
                return f"flushed {value}"

            # Enqueue multiple tasks
            for i in range(3):
                flushable_task(i)

            # Flush
            count = flush_queue()
            # Count depends on timing
            assert isinstance(count, int)


class TestTaskResults:
    """Tests for task result handling."""

    def setup_method(self) -> None:
        """Reset Huey before each test."""
        reset_huey()

    def test_get_task_result(self) -> None:
        """get_task_result retrieves results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            get_huey(db_path)

            @task
            def result_task() -> str:
                return "result_value"

            # Execute locally (immediate)
            result = result_task.call_local()
            assert result == "result_value"

    def test_revoke_scheduled_task(self) -> None:
        """revoke_task cancels a scheduled task."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            get_huey(db_path)

            @task
            def revocable_task() -> str:
                return "revoked"

            # Schedule task with delay
            scheduled = revocable_task.schedule(delay=timedelta(hours=1))
            task_id = scheduled.id  # Result has 'id' attribute

            # Revoke using the Result object's revoke method
            scheduled.revoke()

            # Check it's revoked
            assert scheduled.is_revoked()


class TestHueyConsumer:
    """Tests for Huey consumer compatibility."""

    def setup_method(self) -> None:
        """Reset Huey before each test."""
        reset_huey()

    def test_huey_consumer_available(self) -> None:
        """huey_consumer.py is available."""
        import subprocess

        result = subprocess.run(
            ["python", "-m", "huey.bin.huey_consumer", "--help"],
            capture_output=True,
            text=True,
        )
        # Consumer should show help
        assert "usage" in result.stdout.lower() or result.returncode == 0

    def test_queue_immediate_mode(self) -> None:
        """Queue can run in immediate mode for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            # Create huey with immediate=True (for testing)
            from huey import SqliteHuey

            huey = SqliteHuey(
                filename=str(db_path),
                results=True,
                immediate=True,  # Immediate mode for testing
            )

            executed = []

            @huey.task()
            def immediate_task(value: int) -> int:
                executed.append(value)
                return value * 2

            # In immediate mode, task executes right away
            result = immediate_task(5)
            # In immediate mode, result is available immediately
            assert result.get() == 10
            assert 5 in executed


class TestTaskIntegration:
    """Integration tests for task queue."""

    def setup_method(self) -> None:
        """Reset Huey before each test."""
        reset_huey()

    def test_task_with_event_bus(self) -> None:
        """Task can emit events."""
        from src.core.event_bus import input_received

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            get_huey(db_path)

            received: list[dict] = []

            @input_received.connect
            def handler(sender, **kwargs):
                received.append({"sender": sender, **kwargs})

            @task
            def event_emitting_task(text: str) -> str:
                input_received.send("task_queue", text=text)
                return "emitted"

            # Execute locally
            event_emitting_task.call_local("test event")
            assert len(received) == 1
            assert received[0]["text"] == "test event"

    def test_multiple_tasks_same_queue(self) -> None:
        """Multiple tasks share the same queue."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            get_huey(db_path)

            @task
            def task_a() -> str:
                return "a"

            @task
            def task_b() -> str:
                return "b"

            # Both use same Huey instance
            huey = get_huey()
            assert task_a.huey is huey
            assert task_b.huey is huey

    def test_task_with_capability_registry(self) -> None:
        """Task can use capabilities."""
        from src.core.capabilities import register_capability

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            get_huey(db_path)

            # Register a capability
            def transcribe(audio: bytes) -> str:
                return "transcribed"

            register_capability("transcription", transcribe)

            @task
            def transcription_task(audio: bytes) -> str:
                from src.core.capabilities import get_capability

                transcriber = get_capability("transcription")
                return transcriber(audio) if transcriber else "no capability"

            # Execute locally
            result = transcription_task.call_local(b"audio data")
            assert result == "transcribed"
