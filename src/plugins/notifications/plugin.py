"""Notifications plugin for macOS notifications and audio feedback.

Subscribes to note.written and pipeline.error events and provides
immediate feedback through macOS notifications and system sounds.

Features:
- Success notifications with Obsidian path display
- Error notifications with emoji indicators
- Audio feedback for success, waiting, and error states
- Graceful degradation when system tools unavailable
- Global mute support via config
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from src.core.config import get_config
from src.core.event_bus import (
    SignalSubscription,
    note_written,
    pipeline_error,
)
from src.plugins.base import BasePlugin
from src.plugins.manifest import PluginManifest

from .audio import play_error_sound, play_success_sound
from .notifier import NotificationService

logger = logging.getLogger(__name__)


class NotificationsPlugin(BasePlugin):
    """Plugin providing macOS notifications and audio feedback.

    Subscribes to:
    - note.written: Shows success notification + plays Glass sound
    - pipeline.error: Shows error notification + plays Basso sound

    The plugin gracefully degrades when terminal-notifier or afplay
    are unavailable, logging warnings but continuing to function.
    """

    def __init__(
        self,
        plugin_dir: Path,
        manifest: Optional[PluginManifest] = None,
    ) -> None:
        """Initialize the notifications plugin.

        Args:
            plugin_dir: Directory containing the plugin
            manifest: Optional pre-loaded manifest
        """
        super().__init__(plugin_dir, manifest)

        # Check system tool availability
        self._terminal_notifier_available = shutil.which("terminal-notifier") is not None
        self._afplay_available = shutil.which("afplay") is not None

        # Initialize services
        self._notifier: Optional[NotificationService] = None
        self._muted: bool = False

        # Log availability status
        if not self._terminal_notifier_available:
            logger.warning(
                "terminal-notifier not found - notifications disabled. "
                "Install with: brew install terminal-notifier"
            )
        if not self._afplay_available:
            logger.warning("afplay not found - audio feedback disabled")

    def _load_config(self) -> None:
        """Load plugin configuration from global config."""
        config = get_config()
        notifications_config = config.get("notifications", {})
        self._muted = notifications_config.get("muted", False)

        if self._muted:
            logger.info("Notifications are globally muted")

    def _get_log_path(self) -> Optional[str]:
        """Get the path to Butler's log file.

        Returns:
            Path to log file if available, None otherwise
        """
        # Try common log locations
        log_paths = [
            Path.home() / "Library" / "Logs" / "butler" / "butler.log",
            Path("/var/log/butler.log"),
        ]

        for log_path in log_paths:
            if log_path.exists():
                return str(log_path)

        return None

    def _on_note_written(self, sender: Any, **kwargs: Any) -> None:
        """Handle note.written event.

        Args:
            sender: Event sender
            **kwargs: Event data (path, timestamp, word_count, source)
        """
        if self._muted:
            logger.debug("Notifications muted, skipping note notification")
            return

        path = kwargs.get("path", "")
        source = kwargs.get("source", "unknown")
        word_count = kwargs.get("word_count", 0)

        # Get text preview if available (not in current event data)
        text_preview = kwargs.get("text_preview")

        # Send notification
        if self._notifier and self._terminal_notifier_available:
            self._notifier.send_note_notification(
                path=path,
                source=source,
                word_count=word_count,
                text_preview=text_preview,
            )

        # Play success sound
        if self._afplay_available:
            play_success_sound(muted=self._muted)

        logger.debug(f"Note notification sent for: {path}")

    def _on_pipeline_error(self, sender: Any, **kwargs: Any) -> None:
        """Handle pipeline.error event.

        Args:
            sender: Event sender
            **kwargs: Event data (error, context)
        """
        if self._muted:
            logger.debug("Notifications muted, skipping error notification")
            return

        error = kwargs.get("error", "Unknown error")
        context = kwargs.get("context", {})

        # Get log path for "View log" action
        log_path = self._get_log_path()

        # Send error notification
        if self._notifier and self._terminal_notifier_available:
            self._notifier.send_error_notification(
                error=str(error),
                context=context,
                log_path=log_path,
            )

        # Play error sound
        if self._afplay_available:
            play_error_sound(muted=self._muted)

        logger.debug(f"Error notification sent for: {error}")

    def on_enable(self) -> None:
        """Enable the plugin and subscribe to events."""
        # Load configuration
        self._load_config()

        # Initialize notification service
        self._notifier = NotificationService()

        # Log status
        logger.info(
            f"Notifications plugin enabled "
            f"(notifications: {'available' if self._terminal_notifier_available else 'unavailable'}, "
            f"audio: {'available' if self._afplay_available else 'unavailable'})"
        )

    def on_disable(self) -> None:
        """Disable the plugin and clean up resources."""
        # Event subscriptions are automatically disconnected by BasePlugin
        self._notifier = None
        logger.info("Notifications plugin disabled")

    def connect_events(self) -> None:
        """Connect to event signals declared in the manifest."""
        # Subscribe to note.written events
        note_written_sub = SignalSubscription(
            note_written,
            self._on_note_written,
        )
        note_written_sub.connect()
        self._event_subscriptions.append(note_written_sub)

        # Subscribe to pipeline.error events
        error_sub = SignalSubscription(
            pipeline_error,
            self._on_pipeline_error,
        )
        error_sub.connect()
        self._event_subscriptions.append(error_sub)

        logger.debug("Connected to note_written and pipeline_error signals")

    def get_status(self) -> dict[str, Any]:
        """Get plugin status information.

        Returns:
            Dictionary with plugin status
        """
        return {
            "terminal_notifier_available": self._terminal_notifier_available,
            "afplay_available": self._afplay_available,
            "muted": self._muted,
            "notifier_active": self._notifier is not None and self._notifier.is_available,
            "event_subscriptions": len(self._event_subscriptions),
        }

    def set_muted(self, muted: bool) -> None:
        """Set the mute state.

        Args:
            muted: True to mute notifications, False to unmute
        """
        self._muted = muted
        logger.info(f"Notifications {'muted' if muted else 'unmuted'}")


__all__ = ["NotificationsPlugin"]
