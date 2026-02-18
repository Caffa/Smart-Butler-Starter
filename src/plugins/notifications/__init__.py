"""Notifications plugin for macOS notifications and audio feedback.

Provides visual and audio feedback for Butler activity through:
- macOS native notifications via terminal-notifier
- System sound playback via afplay
- Event subscriptions to note.written and pipeline.error

The plugin gracefully degrades when system tools are unavailable.
"""

from src.plugins.notifications.plugin import NotificationsPlugin

__all__ = ["NotificationsPlugin"]
