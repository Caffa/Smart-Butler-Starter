"""Tests for the event bus system."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.core.event_bus import (
    SignalSubscription,
    day_ended,
    disconnect_all,
    emit,
    get_signal_receivers,
    heartbeat_tick,
    input_received,
    note_routed,
    note_written,
    on,
    pipeline_error,
)


class TestSignalBasics:
    """Test basic signal functionality."""

    def setup_method(self) -> None:
        """Clear all signal connections before each test."""
        for signal in [
            input_received,
            note_routed,
            note_written,
            heartbeat_tick,
            day_ended,
            pipeline_error,
        ]:
            disconnect_all(signal)

    def test_input_received_signal(self) -> None:
        """Test input_received signal emission and reception."""
        received = {}

        @on(input_received)
        def handler(text, source, timestamp, **kwargs):
            received["text"] = text
            received["source"] = source
            received["timestamp"] = timestamp

        emit(input_received, text="Hello world", source="voice", timestamp="2024-01-15T10:30:00Z")

        assert received["text"] == "Hello world"
        assert received["source"] == "voice"
        assert received["timestamp"] == "2024-01-15T10:30:00Z"

    def test_note_routed_signal(self) -> None:
        """Test note_routed signal with metadata."""
        received = {}

        @on(note_routed)
        def handler(text, destination, metadata, **kwargs):
            received["text"] = text
            received["destination"] = destination
            received["metadata"] = metadata

        emit(
            note_routed,
            text="Meeting notes",
            destination="daily_note",
            metadata={"confidence": 0.95, "tags": ["meeting"]},
        )

        assert received["text"] == "Meeting notes"
        assert received["destination"] == "daily_note"
        assert received["metadata"]["confidence"] == 0.95

    def test_note_written_signal(self) -> None:
        """Test note_written signal with file info."""
        received = {}

        @on(note_written)
        def handler(path, timestamp, word_count, source, **kwargs):
            received["path"] = path
            received["timestamp"] = timestamp
            received["word_count"] = word_count
            received["source"] = source

        emit(
            note_written,
            path="/vault/daily/2024-01-15.md",
            timestamp="2024-01-15T10:30:00Z",
            word_count=42,
            source="voice",
        )

        assert received["path"] == "/vault/daily/2024-01-15.md"
        assert received["word_count"] == 42

    def test_heartbeat_tick_signal(self) -> None:
        """Test heartbeat_tick periodic signal."""
        received = []

        @on(heartbeat_tick)
        def handler(timestamp, **kwargs):
            received.append(timestamp)

        emit(heartbeat_tick, timestamp="2024-01-15T10:30:00Z")
        emit(heartbeat_tick, timestamp="2024-01-15T10:31:00Z")

        assert len(received) == 2

    def test_day_ended_signal(self) -> None:
        """Test day_ended end-of-day signal."""
        received = {}

        @on(day_ended)
        def handler(date, **kwargs):
            received["date"] = date

        emit(day_ended, date="2024-01-15")

        assert received["date"] == "2024-01-15"

    def test_pipeline_error_signal(self) -> None:
        """Test pipeline_error with exception info."""
        received = {}

        @on(pipeline_error)
        def handler(error, context, **kwargs):
            received["error"] = error
            received["context"] = context

        emit(
            pipeline_error,
            error=ValueError("Invalid input"),
            context={"task": "transcription", "stage": "parse", "input_id": "123"},
        )

        assert isinstance(received["error"], ValueError)
        assert received["context"]["task"] == "transcription"


class TestSenderIdentification:
    """Test sender identification and filtering."""

    def setup_method(self) -> None:
        """Clear all signal connections before each test."""
        for signal in [
            input_received,
            note_routed,
            note_written,
            heartbeat_tick,
            day_ended,
            pipeline_error,
        ]:
            disconnect_all(signal)

    def test_sender_identification(self) -> None:
        """Test that sender is properly identified."""
        received_senders = []

        @on(input_received)
        def handler(**kwargs):
            received_senders.append(kwargs.get("sender"))

        emit(input_received, sender="voice_capture", text="Hello")
        emit(input_received, sender="telegram_bot", text="World")

        assert "voice_capture" in received_senders
        assert "telegram_bot" in received_senders

    def test_sender_filtering(self) -> None:
        """Test that sender filter works correctly."""
        voice_messages = []
        all_messages = []

        @on(input_received, sender="voice_capture")
        def voice_handler(text, **kwargs):
            voice_messages.append(text)

        @on(input_received)
        def all_handler(text, **kwargs):
            all_messages.append(text)

        emit(input_received, sender="voice_capture", text="Voice message")
        emit(input_received, sender="telegram_bot", text="Telegram message")

        assert voice_messages == ["Voice message"]  # Only voice messages
        assert len(all_messages) == 2  # All messages


class TestMultipleSubscribers:
    """Test multiple subscribers to the same signal."""

    def setup_method(self) -> None:
        """Clear all signal connections before each test."""
        for signal in [
            input_received,
            note_routed,
            note_written,
            heartbeat_tick,
            day_ended,
            pipeline_error,
        ]:
            disconnect_all(signal)

    def test_multiple_subscribers(self) -> None:
        """Test that multiple handlers can subscribe to same signal."""
        results = []

        @on(input_received)
        def handler1(text, **kwargs):
            results.append(f"handler1: {text}")

        @on(input_received)
        def handler2(text, **kwargs):
            results.append(f"handler2: {text}")

        @on(input_received)
        def handler3(text, **kwargs):
            results.append(f"handler3: {text}")

        emit(input_received, text="Test message")

        assert len(results) == 3
        assert "handler1: Test message" in results
        assert "handler2: Test message" in results
        assert "handler3: Test message" in results

    def test_receiver_count(self) -> None:
        """Test get_signal_receivers returns correct count."""

        @on(input_received)
        def handler1(**kwargs):
            pass

        @on(input_received)
        def handler2(**kwargs):
            pass

        receivers = get_signal_receivers(input_received)
        assert len(receivers) == 2


class TestDecoratorFeatures:
    """Test decorator functionality."""

    def setup_method(self) -> None:
        """Clear all signal connections before each test."""
        for signal in [
            input_received,
            note_routed,
            note_written,
            heartbeat_tick,
            day_ended,
            pipeline_error,
        ]:
            disconnect_all(signal)

    def test_decorator_preserves_function_metadata(self) -> None:
        """Test that @on preserves function name and docstring."""

        @on(input_received)
        def my_handler(text, **kwargs):
            """My handler docstring."""
            pass

        assert my_handler.__name__ == "my_handler"
        assert my_handler.__doc__ == "My handler docstring."

    def test_context_manager_subscription(self) -> None:
        """Test SignalSubscription context manager."""
        received = []

        def handler(text, **kwargs):
            received.append(text)

        # Subscription is active within context
        with SignalSubscription(input_received, handler):
            emit(input_received, text="Inside context")
            assert len(received) == 1

        # Subscription removed after context
        emit(input_received, text="Outside context")
        assert len(received) == 1  # Should still be 1


class TestThreadSafety:
    """Test thread safety of signal operations."""

    def setup_method(self) -> None:
        """Clear all signal connections before each test."""
        for signal in [
            input_received,
            note_routed,
            note_written,
            heartbeat_tick,
            day_ended,
            pipeline_error,
        ]:
            disconnect_all(signal)

    def test_concurrent_emissions(self) -> None:
        """Test that concurrent signal emissions are thread-safe."""
        received = []
        lock = threading.Lock()

        @on(input_received)
        def handler(text, **kwargs):
            with lock:
                received.append(text)
            time.sleep(0.01)  # Small delay to increase concurrency

        # Emit from multiple threads
        with ThreadPoolExecutor(max_workers=10) as executor:
            for i in range(100):
                executor.submit(emit, input_received, text=f"message_{i}")

        assert len(received) == 100

    def test_concurrent_subscriptions(self) -> None:
        """Test that concurrent subscribe/unsubscribe is safe."""
        errors = []

        def subscribe_worker(worker_id: int) -> None:
            try:

                @on(input_received)
                def handler(**kwargs):
                    pass

                time.sleep(0.001)
            except Exception as e:
                errors.append((worker_id, str(e)))

        threads = [threading.Thread(target=subscribe_worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent subscriptions: {errors}"


class TestDisconnectAll:
    """Test disconnect_all functionality."""

    def test_disconnect_all_removes_receivers(self) -> None:
        """Test disconnect_all removes all receivers."""

        @on(input_received)
        def handler1(**kwargs):
            pass

        @on(input_received)
        def handler2(**kwargs):
            pass

        assert len(get_signal_receivers(input_received)) == 2

        count = disconnect_all(input_received)
        assert count == 2
        assert len(get_signal_receivers(input_received)) == 0


class TestAllSignalsPresent:
    """Verify all required signals are exported."""

    def test_all_signals_exist(self) -> None:
        """Test that all 6 lifecycle signals are available."""
        from src.core.event_bus import (
            day_ended,
            heartbeat_tick,
            input_received,
            note_routed,
            note_written,
            pipeline_error,
        )

        # Just verify they exist and are signals
        assert input_received is not None
        assert note_routed is not None
        assert note_written is not None
        assert heartbeat_tick is not None
        assert day_ended is not None
        assert pipeline_error is not None
