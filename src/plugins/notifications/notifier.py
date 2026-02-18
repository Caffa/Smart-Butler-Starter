"""Notification service for macOS notifications via terminal-notifier.

Provides native macOS notifications for Butler activity:
- Success notifications with Obsidian path display
- Error notifications with emoji indicators and log viewer action
- Click actions to open files in Obsidian

Uses subprocess to call terminal-notifier CLI with graceful degradation
when the tool is unavailable.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Stage emoji mapping for error notifications
STAGE_EMOJIS = {
    "transcription": "🎤",
    "routing": "📂",
    "writing": "📝",
    "processing": "⚙️",
    "unknown": "❌",
}


class NotificationService:
    """Handles macOS notifications via terminal-notifier.

    Features:
    - Send success notifications for note.written events
    - Send error notifications for pipeline.error events
    - Format Obsidian paths for display (vault/folder/file)
    - Click actions to open in Obsidian or view logs
    - Graceful degradation when terminal-notifier unavailable
    """

    def __init__(self) -> None:
        """Initialize the notification service."""
        self._terminal_notifier_available = self._check_terminal_notifier()

    def _check_terminal_notifier(self) -> bool:
        """Check if terminal-notifier is available.

        Returns:
            True if terminal-notifier is in PATH, False otherwise
        """
        available = shutil.which("terminal-notifier") is not None
        if not available:
            logger.warning(
                "terminal-notifier not found in PATH - "
                "notifications disabled. Install with: brew install terminal-notifier"
            )
        return available

    def _format_obsidian_path(self, path: Path) -> str:
        """Format a file path for Obsidian display.

        Shows vault/folder/file.md format instead of full filesystem path.

        Args:
            path: Full file path

        Returns:
            Formatted display path
        """
        # Try to extract vault-relative path
        # Common Obsidian vault locations
        parts = path.parts

        # Look for Obsidian in path
        for i, part in enumerate(parts):
            if part == "Obsidian" and i + 1 < len(parts):
                # Found Obsidian folder, next folder is likely the vault
                vault_name = parts[i + 1] if i + 1 < len(parts) else "Vault"
                remaining = parts[i + 2 :] if i + 2 < len(parts) else []
                if remaining:
                    return f"{vault_name}/{'/'.join(remaining)}"
                return vault_name

        # Fallback to just filename
        return path.name

    def _truncate_text(self, text: str, max_length: int = 50) -> str:
        """Truncate text with ellipsis if too long.

        Args:
            text: Text to truncate
            max_length: Maximum length before truncation

        Returns:
            Truncated text with "..." if needed
        """
        if len(text) <= max_length:
            return text
        return text[: max_length - 3] + "..."

    def _get_error_emoji(self, stage: str) -> str:
        """Get emoji for error stage.

        Args:
            stage: Pipeline stage where error occurred

        Returns:
            Emoji character for the stage
        """
        return STAGE_EMOJIS.get(stage.lower(), STAGE_EMOJIS["unknown"])

    def _send_notification(
        self,
        title: str,
        message: str,
        sound: str = "default",
        open_url: Optional[str] = None,
    ) -> bool:
        """Send a macOS notification via terminal-notifier.

        Args:
            title: Notification title
            message: Notification message body
            sound: Sound to play (Glass, Pop, Basso, or 'default')
            open_url: URL to open when notification is clicked

        Returns:
            True if notification sent successfully, False otherwise
        """
        if not self._terminal_notifier_available:
            logger.debug("terminal-notifier unavailable, skipping notification")
            return False

        cmd = [
            "terminal-notifier",
            "-title",
            title,
            "-message",
            message,
            "-sound",
            sound,
        ]

        if open_url:
            cmd.extend(["-open", open_url])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                logger.debug(f"Notification failed: {result.stderr}")
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            logger.warning("Notification timed out")
            return False
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")
            return False

    def send_note_notification(
        self,
        path: str,
        source: str,
        word_count: int,
        text_preview: Optional[str] = None,
    ) -> bool:
        """Send a notification when a note is successfully written.

        Args:
            path: Full file path where note was written
            source: Source of the note (e.g., 'voice', 'telegram')
            word_count: Number of words in the note
            text_preview: Preview of the note content

        Returns:
            True if notification sent successfully, False otherwise
        """
        file_path = Path(path)
        display_path = self._format_obsidian_path(file_path)

        # Build message
        preview = ""
        if text_preview:
            preview = self._truncate_text(text_preview, 50) + " | "

        message = f"{preview}{display_path} | {word_count} words"

        # Build Obsidian open URL
        obsidian_url = f"obsidian://open?path={file_path.absolute()}"

        return self._send_notification(
            title="Note Saved",
            message=message,
            sound="Glass",
            open_url=obsidian_url,
        )

    def send_error_notification(
        self,
        error: str,
        context: Optional[dict[str, Any]] = None,
        log_path: Optional[str] = None,
    ) -> bool:
        """Send an error notification.

        Args:
            error: Error message or exception
            context: Error context with stage information
            log_path: Path to log file for "View log" action

        Returns:
            True if notification sent successfully, False otherwise
        """
        context = context or {}
        stage = context.get("stage", "unknown")

        # Get emoji for stage
        emoji = self._get_error_emoji(stage)

        # Build message
        error_text = str(error)
        message = f"{emoji} {self._truncate_text(error_text, 80)}"

        # Build log viewer URL
        open_url = None
        if log_path:
            open_url = f"file://{log_path}"

        return self._send_notification(
            title="Butler Error",
            message=message,
            sound="Basso",
            open_url=open_url,
        )

    @property
    def is_available(self) -> bool:
        """Check if terminal-notifier is available."""
        return self._terminal_notifier_available


__all__ = ["NotificationService", "STAGE_EMOJIS"]
