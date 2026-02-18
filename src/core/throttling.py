"""Smart throttling for resource-aware task execution.

Provides decorators that check system resources before executing tasks,
deferring work when the system is busy or on battery power.

Usage:
    from src.core.throttling import throttled, ThrottledException

    @throttled(max_cpu=60, max_ram=80, require_power=False)
    def heavy_task():
        # Only runs when system has resources
        pass

    # With Huey integration
    @task(retries=5, retry_delay=300)
    @throttled(max_cpu=60, max_ram=75, require_power=True)
    def background_job():
        # Retries automatically when throttled
        pass
"""

from __future__ import annotations

import functools
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, TypeVar

import psutil

logger = logging.getLogger(__name__)

# Type variable for decorated functions
F = TypeVar("F", bound=Callable[..., Any])


class ThrottledException(Exception):
    """Raised when a task is throttled due to resource constraints.

    Attributes:
        reason: Description of why the task was throttled
        resource: Which resource triggered throttling (cpu, ram, power)
        value: Current resource value
        threshold: Threshold that was exceeded
    """

    def __init__(
        self,
        reason: str,
        resource: Optional[str] = None,
        value: Optional[float] = None,
        threshold: Optional[float] = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.resource = resource
        self.value = value
        self.threshold = threshold

    def __str__(self) -> str:
        msg = self.reason
        if self.resource and self.value is not None and self.threshold is not None:
            msg += f" ({self.resource}: {self.value:.1f}% > {self.threshold:.1f}%)"
        return msg


@dataclass
class SystemResources:
    """Snapshot of current system resources.

    Attributes:
        cpu_percent: CPU usage percentage (0-100)
        ram_percent: RAM usage percentage (0-100)
        on_battery: Whether system is running on battery
        battery_percent: Battery level percentage (None if desktop)
    """

    cpu_percent: float
    ram_percent: float
    on_battery: bool
    battery_percent: Optional[float]

    @classmethod
    def current(cls) -> SystemResources:
        """Get current system resource snapshot.

        Returns:
            SystemResources with current values
        """
        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory().percent

        battery = psutil.sensors_battery()
        if battery is not None:
            on_battery = not battery.power_plugged
            battery_percent = battery.percent
        else:
            on_battery = False
            battery_percent = None

        return cls(
            cpu_percent=cpu,
            ram_percent=ram,
            on_battery=on_battery,
            battery_percent=battery_percent,
        )


def check_throttle(
    max_cpu: Optional[float] = None,
    max_ram: Optional[float] = None,
    require_power: bool = False,
) -> Optional[ThrottledException]:
    """Check if system resources exceed thresholds.

    Args:
        max_cpu: Maximum CPU percentage (None = no check)
        max_ram: Maximum RAM percentage (None = no check)
        require_power: If True, throttle when on battery

    Returns:
        ThrottledException if throttled, None otherwise
    """
    resources = SystemResources.current()

    # Check CPU
    if max_cpu is not None and resources.cpu_percent > max_cpu:
        return ThrottledException(
            f"CPU usage too high: {resources.cpu_percent:.1f}% > {max_cpu:.1f}%",
            resource="cpu",
            value=resources.cpu_percent,
            threshold=max_cpu,
        )

    # Check RAM
    if max_ram is not None and resources.ram_percent > max_ram:
        return ThrottledException(
            f"RAM usage too high: {resources.ram_percent:.1f}% > {max_ram:.1f}%",
            resource="ram",
            value=resources.ram_percent,
            threshold=max_ram,
        )

    # Check power
    if require_power and resources.on_battery:
        battery_str = ""
        if resources.battery_percent is not None:
            battery_str = f" ({resources.battery_percent:.0f}%)"
        return ThrottledException(
            f"System on battery power{battery_str}",
            resource="power",
            value=1.0,  # On battery
            threshold=0.0,  # Requires power
        )

    return None


def throttled(
    func: Optional[F] = None,
    *,
    max_cpu: Optional[float] = None,
    max_ram: Optional[float] = None,
    require_power: bool = False,
    on_throttle: Optional[Callable[[ThrottledException], None]] = None,
) -> Callable[[F], F] | F:
    """Decorator that throttles task execution based on system resources.

    Checks system resources before executing the decorated function.
    If resources exceed thresholds, raises ThrottledException.

    Args:
        func: Function to decorate (if used without parentheses)
        max_cpu: Maximum CPU percentage (None = no check, default: None)
        max_ram: Maximum RAM percentage (None = no check, default: None)
        require_power: If True, throttle when on battery (default: False)
        on_throttle: Optional callback called when throttled

    Returns:
        Decorated function that checks resources before execution

    Example:
        @throttled(max_cpu=60, max_ram=80)
        def process_video():
            # Only runs when CPU < 60% and RAM < 80%
            pass

        @throttled(require_power=True, max_cpu=50)
        def heavy_background_task():
            # Only runs when plugged in AND CPU < 50%
            pass

        # With Huey - automatic retry on throttle
        @task(retries=5, retry_delay=60)
        @throttled(max_cpu=60, max_ram=75)
        def background_job():
            pass
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Check resources
            throttle_error = check_throttle(
                max_cpu=max_cpu,
                max_ram=max_ram,
                require_power=require_power,
            )

            if throttle_error is not None:
                logger.debug(f"Task {fn.__name__} throttled: {throttle_error.reason}")
                if on_throttle is not None:
                    on_throttle(throttle_error)
                raise throttle_error

            # Execute the function
            return fn(*args, **kwargs)

        return wrapper  # type: ignore

    if func is not None:
        return decorator(func)
    return decorator


def adaptive_throttle(
    func: Optional[F] = None,
    *,
    base_cpu: float = 50.0,
    base_ram: float = 70.0,
    battery_cpu: float = 30.0,
    battery_ram: float = 50.0,
) -> Callable[[F], F] | F:
    """Decorator with adaptive thresholds based on power status.

    Uses lower thresholds when on battery to preserve power.

    Args:
        func: Function to decorate
        base_cpu: CPU threshold when plugged in
        base_ram: RAM threshold when plugged in
        battery_cpu: CPU threshold when on battery
        battery_ram: RAM threshold when on battery

    Returns:
        Decorated function with adaptive thresholds

    Example:
        @adaptive_throttle(base_cpu=60, battery_cpu=30)
        def smart_task():
            # Uses 60% CPU threshold when plugged in
            # Uses 30% CPU threshold when on battery
            pass
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            resources = SystemResources.current()

            # Choose thresholds based on power status
            if resources.on_battery:
                cpu_threshold = battery_cpu
                ram_threshold = battery_ram
            else:
                cpu_threshold = base_cpu
                ram_threshold = base_ram

            # Check resources
            throttle_error = check_throttle(
                max_cpu=cpu_threshold,
                max_ram=ram_threshold,
                require_power=False,
            )

            if throttle_error is not None:
                logger.debug(f"Task {fn.__name__} throttled (adaptive): {throttle_error.reason}")
                raise throttle_error

            return fn(*args, **kwargs)

        return wrapper  # type: ignore

    if func is not None:
        return decorator(func)
    return decorator


def wait_for_resources(
    max_cpu: Optional[float] = None,
    max_ram: Optional[float] = None,
    require_power: bool = False,
    timeout: float = 60.0,
    poll_interval: float = 1.0,
) -> bool:
    """Wait until system resources are below thresholds.

    Blocks until resources are available or timeout is reached.

    Args:
        max_cpu: Maximum CPU percentage (None = no check)
        max_ram: Maximum RAM percentage (None = no check)
        require_power: If True, wait for power connection
        timeout: Maximum time to wait in seconds
        poll_interval: How often to check resources

    Returns:
        True if resources became available, False if timeout

    Example:
        # Wait up to 30 seconds for system to become idle
        if wait_for_resources(max_cpu=30, max_ram=50, timeout=30):
            run_heavy_task()
        else:
            print("System still busy, skipping task")
    """
    start_time = time.time()

    while time.time() - start_time < timeout:
        throttle_error = check_throttle(
            max_cpu=max_cpu,
            max_ram=max_ram,
            require_power=require_power,
        )

        if throttle_error is None:
            return True

        time.sleep(poll_interval)

    return False


__all__ = [
    "ThrottledException",
    "SystemResources",
    "check_throttle",
    "throttled",
    "adaptive_throttle",
    "wait_for_resources",
]
