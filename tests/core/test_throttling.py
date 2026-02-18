"""Tests for smart throttling.

Tests cover:
- CPU threshold checking
- RAM threshold checking
- Power status detection
- Decorator behavior
- Integration with task queue
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.throttling import (
    SystemResources,
    ThrottledException,
    adaptive_throttle,
    check_throttle,
    throttled,
    wait_for_resources,
)


class TestSystemResources:
    """Tests for SystemResources dataclass."""

    def test_current_returns_snapshot(self) -> None:
        """SystemResources.current() returns valid snapshot."""
        resources = SystemResources.current()

        assert 0 <= resources.cpu_percent <= 100
        assert 0 <= resources.ram_percent <= 100
        assert isinstance(resources.on_battery, bool)
        # battery_percent may be None on desktop

    def test_resources_dataclass(self) -> None:
        """SystemResources can be created directly."""
        resources = SystemResources(
            cpu_percent=50.0,
            ram_percent=60.0,
            on_battery=False,
            battery_percent=80.0,
        )

        assert resources.cpu_percent == 50.0
        assert resources.ram_percent == 60.0
        assert not resources.on_battery
        assert resources.battery_percent == 80.0


class TestCheckThrottle:
    """Tests for check_throttle function."""

    def test_no_throttle_when_all_none(self) -> None:
        """No throttling when all thresholds are None."""
        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=90.0,
                ram_percent=90.0,
                on_battery=True,
                battery_percent=10.0,
            )

            result = check_throttle()
            assert result is None

    def test_throttle_on_high_cpu(self) -> None:
        """Throttles when CPU exceeds threshold."""
        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=75.0,
                ram_percent=50.0,
                on_battery=False,
                battery_percent=100.0,
            )

            result = check_throttle(max_cpu=60.0)
            assert result is not None
            assert result.resource == "cpu"
            assert result.value == 75.0
            assert result.threshold == 60.0

    def test_no_throttle_on_low_cpu(self) -> None:
        """No throttle when CPU is below threshold."""
        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=40.0,
                ram_percent=50.0,
                on_battery=False,
                battery_percent=100.0,
            )

            result = check_throttle(max_cpu=60.0)
            assert result is None

    def test_throttle_on_high_ram(self) -> None:
        """Throttles when RAM exceeds threshold."""
        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=30.0,
                ram_percent=90.0,
                on_battery=False,
                battery_percent=100.0,
            )

            result = check_throttle(max_ram=80.0)
            assert result is not None
            assert result.resource == "ram"

    def test_throttle_on_battery(self) -> None:
        """Throttles when on battery and require_power=True."""
        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=30.0,
                ram_percent=50.0,
                on_battery=True,
                battery_percent=50.0,
            )

            result = check_throttle(require_power=True)
            assert result is not None
            assert result.resource == "power"

    def test_no_throttle_when_plugged_in(self) -> None:
        """No throttle when plugged in and require_power=True."""
        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=30.0,
                ram_percent=50.0,
                on_battery=False,
                battery_percent=100.0,
            )

            result = check_throttle(require_power=True)
            assert result is None

    def test_throttle_on_multiple_violations(self) -> None:
        """Throttles on first violation found (CPU checked first)."""
        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=90.0,
                ram_percent=90.0,
                on_battery=True,
                battery_percent=10.0,
            )

            result = check_throttle(max_cpu=60.0, max_ram=80.0, require_power=True)
            assert result is not None
            # CPU is checked first
            assert result.resource == "cpu"


class TestThrottledDecorator:
    """Tests for throttled decorator."""

    def test_executes_when_resources_available(self) -> None:
        """Function executes when resources are available."""
        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=30.0,
                ram_percent=50.0,
                on_battery=False,
                battery_percent=100.0,
            )

            @throttled(max_cpu=60.0, max_ram=80.0)
            def normal_task() -> str:
                return "success"

            result = normal_task()
            assert result == "success"

    def test_raises_when_cpu_high(self) -> None:
        """Raises ThrottledException when CPU is high."""
        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=75.0,
                ram_percent=50.0,
                on_battery=False,
                battery_percent=100.0,
            )

            @throttled(max_cpu=60.0)
            def cpu_intensive_task() -> str:
                return "should not reach"

            with pytest.raises(ThrottledException) as exc_info:
                cpu_intensive_task()

            assert "CPU" in str(exc_info.value)

    def test_raises_when_ram_high(self) -> None:
        """Raises ThrottledException when RAM is high."""
        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=30.0,
                ram_percent=90.0,
                on_battery=False,
                battery_percent=100.0,
            )

            @throttled(max_ram=80.0)
            def ram_intensive_task() -> str:
                return "should not reach"

            with pytest.raises(ThrottledException) as exc_info:
                ram_intensive_task()

            assert "RAM" in str(exc_info.value)

    def test_raises_on_battery_when_required(self) -> None:
        """Raises ThrottledException on battery when require_power=True."""
        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=30.0,
                ram_percent=50.0,
                on_battery=True,
                battery_percent=50.0,
            )

            @throttled(require_power=True)
            def power_required_task() -> str:
                return "should not reach"

            with pytest.raises(ThrottledException) as exc_info:
                power_required_task()

            assert "battery" in str(exc_info.value).lower()

    def test_on_throttle_callback(self) -> None:
        """on_throttle callback is called when throttled."""
        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=75.0,
                ram_percent=50.0,
                on_battery=False,
                battery_percent=100.0,
            )

            callback_calls: list[ThrottledException] = []

            def on_throttle(exc: ThrottledException) -> None:
                callback_calls.append(exc)

            @throttled(max_cpu=60.0, on_throttle=on_throttle)
            def callback_task() -> str:
                return "should not reach"

            with pytest.raises(ThrottledException):
                callback_task()

            assert len(callback_calls) == 1
            assert callback_calls[0].resource == "cpu"

    def test_decorator_without_parentheses(self) -> None:
        """Decorator works without parentheses."""
        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=30.0,
                ram_percent=50.0,
                on_battery=False,
                battery_percent=100.0,
            )

            @throttled
            def no_options_task() -> str:
                return "success"

            result = no_options_task()
            assert result == "success"

    def test_preserves_function_metadata(self) -> None:
        """Decorator preserves function name and docstring."""

        @throttled(max_cpu=60.0)
        def documented_task() -> str:
            """This is a documented task."""
            return "done"

        assert documented_task.__name__ == "documented_task"
        assert documented_task.__doc__ == "This is a documented task."


class TestAdaptiveThrottle:
    """Tests for adaptive_throttle decorator."""

    def test_uses_base_thresholds_when_plugged(self) -> None:
        """Uses base thresholds when plugged in."""
        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=55.0,  # Above battery threshold but below base
                ram_percent=50.0,
                on_battery=False,
                battery_percent=100.0,
            )

            @adaptive_throttle(base_cpu=60.0, battery_cpu=30.0)
            def adaptive_task() -> str:
                return "success"

            result = adaptive_task()
            assert result == "success"

    def test_uses_battery_thresholds_on_battery(self) -> None:
        """Uses lower thresholds when on battery."""
        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=40.0,  # Above battery threshold
                ram_percent=50.0,
                on_battery=True,
                battery_percent=50.0,
            )

            @adaptive_throttle(base_cpu=60.0, battery_cpu=30.0)
            def adaptive_task() -> str:
                return "should not reach"

            with pytest.raises(ThrottledException) as exc_info:
                adaptive_task()

            assert exc_info.value.resource == "cpu"


class TestWaitForResources:
    """Tests for wait_for_resources function."""

    def test_returns_immediately_when_available(self) -> None:
        """Returns True immediately when resources are available."""
        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=30.0,
                ram_percent=50.0,
                on_battery=False,
                battery_percent=100.0,
            )

            result = wait_for_resources(max_cpu=60.0, timeout=5.0)
            assert result is True
            # Should only check once
            assert mock_current.call_count == 1

    def test_waits_until_available(self) -> None:
        """Waits until resources become available."""
        call_count = [0]

        def mock_current_factory():
            call_count[0] += 1
            if call_count[0] < 3:
                return SystemResources(
                    cpu_percent=90.0,  # High first two times
                    ram_percent=50.0,
                    on_battery=False,
                    battery_percent=100.0,
                )
            return SystemResources(
                cpu_percent=30.0,  # Low on third call
                ram_percent=50.0,
                on_battery=False,
                battery_percent=100.0,
            )

        with patch.object(SystemResources, "current", side_effect=mock_current_factory):
            result = wait_for_resources(
                max_cpu=60.0,
                timeout=10.0,
                poll_interval=0.01,  # Fast polling for tests
            )
            assert result is True

    def test_returns_false_on_timeout(self) -> None:
        """Returns False when timeout is reached."""
        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=90.0,  # Always high
                ram_percent=50.0,
                on_battery=False,
                battery_percent=100.0,
            )

            result = wait_for_resources(
                max_cpu=60.0,
                timeout=0.1,  # Very short timeout
                poll_interval=0.05,
            )
            assert result is False


class TestThrottledException:
    """Tests for ThrottledException."""

    def test_exception_message(self) -> None:
        """Exception has descriptive message."""
        exc = ThrottledException(
            "CPU too high",
            resource="cpu",
            value=75.0,
            threshold=60.0,
        )

        assert str(exc) == "CPU too high (cpu: 75.0% > 60.0%)"
        assert exc.resource == "cpu"
        assert exc.value == 75.0
        assert exc.threshold == 60.0

    def test_exception_without_details(self) -> None:
        """Exception works without detailed attributes."""
        exc = ThrottledException("Generic throttle reason")

        assert str(exc) == "Generic throttle reason"
        assert exc.resource is None
        assert exc.value is None
        assert exc.threshold is None


class TestThrottleWithTaskQueue:
    """Tests for throttling integration with task queue."""

    def setup_method(self) -> None:
        """Reset Huey before each test."""
        from src.core.task_queue import reset_huey

        reset_huey()

    def test_throttled_task_raises_retryable_error(self) -> None:
        """ThrottledException can trigger Huey retry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from pathlib import Path
            from src.core.task_queue import get_huey, task

            db_path = Path(tmpdir) / "tasks.db"
            get_huey(db_path)

            with patch.object(SystemResources, "current") as mock_current:
                mock_current.return_value = SystemResources(
                    cpu_percent=75.0,
                    ram_percent=50.0,
                    on_battery=False,
                    battery_percent=100.0,
                )

                @task(retries=3)
                @throttled(max_cpu=60.0)
                def throttled_background_task() -> str:
                    return "success"

                # Execute locally - should raise ThrottledException
                with pytest.raises(ThrottledException):
                    throttled_background_task.call_local()

    def test_throttle_and_capability_integration(self) -> None:
        """Throttled tasks can use capabilities."""
        from src.core.capabilities import clear_registry, register_capability

        clear_registry()

        def mock_capability() -> str:
            return "capability_result"

        register_capability("test_cap", mock_capability)

        with patch.object(SystemResources, "current") as mock_current:
            mock_current.return_value = SystemResources(
                cpu_percent=30.0,
                ram_percent=50.0,
                on_battery=False,
                battery_percent=100.0,
            )

            @throttled(max_cpu=60.0)
            def capability_using_task() -> str:
                from src.core.capabilities import get_capability

                cap = get_capability("test_cap")
                return cap() if cap else "no cap"

            result = capability_using_task()
            assert result == "capability_result"
