"""Event bus system using blinker for lifecycle signals.

Provides signal-based communication between components with support for
sender identification, multiple subscribers, and decorator-based subscription.
"""

from __future__ import annotations

import threading
import weakref
from typing import Any, Callable, TypeVar

from blinker import Namespace

# Create a namespace for all butler signals
_signals = Namespace()

# Lifecycle signals
input_received = _signals.signal("input.received")
"""Emitted when new input is captured.

Args:
    sender: Signal sender identifier
    text: The captured text content
    source: Source identifier (e.g., 'voice', 'telegram', 'cli')
    timestamp: ISO format timestamp
"""

note_routed = _signals.signal("note.routed")
"""Emitted when a note is classified and routed.

Args:
    sender: Signal sender identifier
    text: The note content
    destination: Target destination (e.g., 'daily_note', 'inbox', 'vault/path')
    metadata: Additional routing metadata
"""

note_written = _signals.signal("note.written")
"""Emitted when a note is successfully written to disk.

Args:
    sender: Signal sender identifier
    path: Full file path where note was written
    timestamp: ISO format timestamp
    word_count: Number of words in the note
    source: Original source of the note
"""

heartbeat_tick = _signals.signal("heartbeat.tick")
"""Periodic system pulse.

Args:
    sender: Signal sender identifier
    timestamp: ISO format timestamp
"""

day_ended = _signals.signal("day.ended")
"""End of day trigger.

Args:
    sender: Signal sender identifier
    date: Date string (YYYY-MM-DD)
"""

pipeline_error = _signals.signal("pipeline.error")
"""Processing error signal.

Args:
    sender: Signal sender identifier
    error: The exception or error message
    context: Dictionary with error context (task, stage, input_id)
"""

# Type variable for decorator
F = TypeVar("F", bound=Callable[..., Any])


class SignalSubscription:
    """Helper class for managing signal subscriptions."""

    def __init__(self, signal, receiver: Callable, sender: Any = None) -> None:
        self.signal = signal
        self.receiver = receiver
        self.sender = sender
        self._connected = False
        self._lock = threading.Lock()

    def connect(self) -> None:
        """Connect the receiver to the signal."""
        with self._lock:
            if not self._connected:
                if self.sender is not None:
                    self.signal.connect(self.receiver, sender=self.sender)
                else:
                    self.signal.connect(self.receiver)
                self._connected = True

    def disconnect(self) -> None:
        """Disconnect the receiver from the signal."""
        with self._lock:
            if self._connected:
                if self.sender is not None:
                    self.signal.disconnect(self.receiver, sender=self.sender)
                else:
                    self.signal.disconnect(self.receiver)
                self._connected = False

    def __enter__(self) -> SignalSubscription:
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.disconnect()


def on(signal, *, sender: Any = None, weak: bool = True) -> Callable[[F], F]:
    """Decorator for subscribing to signals.

    Args:
        signal: The signal to subscribe to
        sender: Optional sender filter (only receive from this sender)
        weak: If True, use weak reference (allows garbage collection)

    Returns:
        Decorator function that registers the handler

    Example:
        @on(input_received)
        def handle_input(sender, text, source, timestamp, **kwargs):
            print(f"Input from {source}: {text}")

        @on(note_routed, sender="classifier")
        def handle_routed(sender, text, destination, **kwargs):
            print(f"Routed to {destination}")
    """

    def decorator(func: F) -> F:
        # Connect the function directly to the signal
        # Blinker will pass sender as the first argument
        if sender is not None:
            signal.connect(func, sender=sender, weak=weak)
        else:
            signal.connect(func, weak=weak)
        return func

    return decorator


def emit(
    signal,
    *,
    sender: Any = None,
    **kwargs: Any,
) -> None:
    """Emit a signal with the given arguments.

    Args:
        signal: The signal to emit
        sender: Optional sender identification
        **kwargs: Signal-specific arguments

    Example:
        emit(input_received, sender="voice_capture", text="Hello", source="voice")
    """
    signal.send(sender, **kwargs)


def get_signal_receivers(signal) -> list[Callable]:
    """Get all receivers connected to a signal.

    Args:
        signal: The signal to inspect

    Returns:
        List of receiver functions
    """
    receivers = []
    for ref in signal.receivers.values():
        if isinstance(ref, weakref.ref):
            func = ref()
            if func is not None:
                receivers.append(func)
        else:
            receivers.append(ref)
    return receivers


def disconnect_all(signal, sender: Any = None) -> int:
    """Disconnect all receivers from a signal.

    Args:
        signal: The signal to clear
        sender: Optional sender filter

    Returns:
        Number of receivers disconnected
    """
    count = 0
    # Get list of receivers before modifying
    receivers = get_signal_receivers(signal)
    for receiver in receivers:
        try:
            if sender is not None:
                signal.disconnect(receiver, sender=sender)
            else:
                signal.disconnect(receiver)
            count += 1
        except Exception:
            pass
    return count


# Convenience exports
__all__ = [
    # Signals
    "input_received",
    "note_routed",
    "note_written",
    "heartbeat_tick",
    "day_ended",
    "pipeline_error",
    # Utilities
    "on",
    "emit",
    "SignalSubscription",
    "get_signal_receivers",
    "disconnect_all",
]
