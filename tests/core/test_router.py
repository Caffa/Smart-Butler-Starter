"""Tests for the simple router module."""

import pytest

from src.core.event_bus import (
    disconnect_all,
    emit,
    input_received,
    note_routed,
)
from src.core.router import DEFAULT_DESTINATION, SimpleRouter, simple_route


class TestSimpleRouter:
    """Test SimpleRouter functionality."""

    def setup_method(self) -> None:
        """Clear signal connections before each test."""
        disconnect_all(input_received)
        disconnect_all(note_routed)

    def teardown_method(self) -> None:
        """Clean up after each test."""
        disconnect_all(input_received)
        disconnect_all(note_routed)

    def test_router_subscribes_to_input_received(self) -> None:
        """Test that router subscribes to input_received signal."""
        router = SimpleRouter()
        router.start()

        # Verify router is subscribed by checking it receives events
        received = []

        def capture_event(sender, **kwargs):
            received.append(kwargs)

        note_routed.connect(capture_event)

        # Emit an input_received event
        emit(
            input_received,
            sender="voice_input",
            text="Test transcription",
            source="voice",
            confidence=0.95,
            duration=5.0,
            timestamp="2024-01-15T10:30:00Z",
        )

        # Router should have received and routed it
        assert len(received) == 1
        assert received[0]["text"] == "Test transcription"
        assert received[0]["source"] == "voice"
        assert received[0]["destination"] == DEFAULT_DESTINATION

        router.stop()

    def test_router_emits_note_routed_with_correct_fields(self) -> None:
        """Test that router emits note_routed with all required fields."""
        router = SimpleRouter()
        router.start()

        received = {}

        def capture_event(sender, **kwargs):
            received["sender"] = sender
            received.update(kwargs)

        note_routed.connect(capture_event)

        emit(
            input_received,
            sender="voice_input",
            text="Hello world",
            source="voice",
            confidence=0.85,
            duration=3.5,
            timestamp="2024-01-15T14:22:00Z",
        )

        assert received["text"] == "Hello world"
        assert received["source"] == "voice"
        assert received["destination"] == "daily"
        assert received["sender"] == "router"
        assert "timestamp" in received

        router.stop()

    def test_router_includes_destination_daily_by_default(self) -> None:
        """Test that default destination is 'daily'."""
        router = SimpleRouter()
        router.start()

        received = []

        def capture_event(sender, **kwargs):
            received.append(kwargs)

        note_routed.connect(capture_event)

        emit(
            input_received,
            sender="test",
            text="Test",
            source="test_source",
            timestamp="2024-01-15T10:00:00Z",
        )

        assert len(received) == 1
        assert received[0]["destination"] == "daily"

        router.stop()

    def test_router_passes_through_metadata(self) -> None:
        """Test that router passes confidence and duration through."""
        router = SimpleRouter()
        router.start()

        received = {}

        def capture_event(sender, **kwargs):
            received.update(kwargs)

        note_routed.connect(capture_event)

        emit(
            input_received,
            sender="voice_input",
            text="Test",
            source="voice",
            confidence=0.92,
            duration=10.5,
            timestamp="2024-01-15T10:00:00Z",
        )

        assert received.get("confidence") == 0.92
        assert received.get("duration") == 10.5

        router.stop()

    def test_router_handles_empty_text(self) -> None:
        """Test that router ignores empty text input."""
        router = SimpleRouter()
        router.start()

        received = []

        def capture_event(sender, **kwargs):
            received.append(kwargs)

        note_routed.connect(capture_event)

        emit(
            input_received,
            sender="voice_input",
            text="",
            source="voice",
            timestamp="2024-01-15T10:00:00Z",
        )

        # Router should not emit note_routed for empty text
        assert len(received) == 0

        router.stop()

    def test_router_stop_disconnects(self) -> None:
        """Test that stop() properly disconnects the router."""
        router = SimpleRouter()
        router.start()
        router.stop()

        received = []

        def capture_event(sender, **kwargs):
            received.append(kwargs)

        note_routed.connect(capture_event)

        emit(
            input_received,
            sender="voice_input",
            text="Test",
            source="voice",
            timestamp="2024-01-15T10:00:00Z",
        )

        # After stop, router should not emit
        assert len(received) == 0

    def test_set_destination_changes_default(self) -> None:
        """Test that set_destination changes the routing destination."""
        router = SimpleRouter()
        router.set_destination("inbox")

        router.start()

        received = []

        def capture_event(sender, **kwargs):
            received.append(kwargs)

        note_routed.connect(capture_event)

        emit(
            input_received,
            sender="voice_input",
            text="Test",
            source="voice",
            timestamp="2024-01-15T10:00:00Z",
        )

        assert len(received) == 1
        assert received[0]["destination"] == "inbox"

        router.stop()


class TestSimpleRoute:
    """Test the simple_route convenience function."""

    def setup_method(self) -> None:
        """Clear signal connections before each test."""
        disconnect_all(input_received)
        disconnect_all(note_routed)

    def teardown_method(self) -> None:
        """Clean up after each test."""
        disconnect_all(input_received)
        disconnect_all(note_routed)

    def test_simple_route_returns_started_router(self) -> None:
        """Test that simple_route returns a started router."""
        router = simple_route()

        assert router is not None
        assert isinstance(router, SimpleRouter)

        # Verify it's started by checking it routes events
        received = []

        def capture_event(sender, **kwargs):
            received.append(kwargs)

        note_routed.connect(capture_event)

        emit(
            input_received,
            sender="test",
            text="Test",
            source="test",
            timestamp="2024-01-15T10:00:00Z",
        )

        assert len(received) == 1

        router.stop()


class TestDefaultDestination:
    """Test default destination constant."""

    def test_default_destination_is_daily(self) -> None:
        """Verify default destination is 'daily'."""
        assert DEFAULT_DESTINATION == "daily"
