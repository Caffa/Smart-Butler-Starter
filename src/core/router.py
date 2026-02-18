"""Simple event router for MVP voice processing pipeline.

Bridges input_received events to note_routed events for basic daily note routing.
This is a simple passthrough router - all voice input is routed to daily notes.

For the AI-powered routing (Phase 5), this will be replaced with a classifier.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from src.core.event_bus import emit, input_received, note_routed
from src.core.event_bus import SignalSubscription

logger = logging.getLogger(__name__)

# Default destination for MVP - all voice input goes to daily notes
DEFAULT_DESTINATION = "daily"


class SimpleRouter:
    """Simple router that bridges input_received to note_routed.

    For MVP: all voice input is routed to daily notes.
    In Phase 5, this will be replaced with an AI-powered classifier.
    """

    def __init__(self) -> None:
        """Initialize the simple router."""
        self._subscription: Optional[SignalSubscription] = None
        self._destination: str = DEFAULT_DESTINATION

    def start(self) -> None:
        """Start the router by subscribing to input_received events."""
        if self._subscription is not None:
            logger.warning("Router already started")
            return

        # Subscribe to input_received signal
        self._subscription = input_received.connect(self._handle_input)
        logger.info(f"SimpleRouter started, routing to: {self._destination}")

    def stop(self) -> None:
        """Stop the router by disconnecting from input_received events."""
        if self._subscription is not None:
            input_received.disconnect(self._handle_input)
            self._subscription = None
            logger.info("SimpleRouter stopped")

    def _handle_input(self, sender: Any, **kwargs: Any) -> None:
        """Handle input_received events by routing to note_routed.

        Args:
            sender: Signal sender identifier
            **kwargs: Signal arguments (text, source, confidence, duration, timestamp)
        """
        # Extract the text and metadata
        text = kwargs.get("text", "")
        source = kwargs.get("source", "unknown")
        confidence = kwargs.get("confidence")
        duration = kwargs.get("duration")
        original_timestamp = kwargs.get("timestamp")

        if not text:
            logger.debug("Ignoring empty input")
            return

        # Use original timestamp if provided, otherwise use current time
        if original_timestamp:
            try:
                timestamp = datetime.fromisoformat(original_timestamp.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                timestamp = datetime.now(timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        # Emit note_routed with destination="daily" (MVP simple routing)
        emit(
            note_routed,
            sender="router",
            text=text,
            source=source,
            destination=self._destination,
            timestamp=timestamp.isoformat(),
            confidence=confidence,
            duration=duration,
        )

        logger.info(f"Routed input from {source} to {self._destination}")

    def set_destination(self, destination: str) -> None:
        """Set the default destination for routed notes.

        Args:
            destination: Target destination (e.g., 'daily', 'inbox', 'vault/path')
        """
        self._destination = destination
        logger.info(f"Router destination set to: {destination}")


def simple_route() -> SimpleRouter:
    """Convenience function to create and start a simple router.

    Returns:
        Started SimpleRouter instance
    """
    router = SimpleRouter()
    router.start()
    return router


__all__ = [
    "SimpleRouter",
    "simple_route",
    "DEFAULT_DESTINATION",
]
