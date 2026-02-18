"""Daily writer plugin for appending to Obsidian daily notes.

Subscribes to note.routed events and appends content to YYYY-MM-DD.md files
in the configured Obsidian vault. Creates new files with Obsidian frontmatter
and emits note.written events after writing.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.core.config import get_config
from src.core.event_bus import emit, note_routed, note_written
from src.core.safe_write import safe_read, safe_write
from src.plugins.base import BasePlugin
from src.plugins.manifest import PluginManifest

logger = logging.getLogger(__name__)


class DailyWriterPlugin(BasePlugin):
    """Plugin that writes routed notes to daily files.

    Features:
    - Subscribe to note.routed events
    - Filter for destination="daily"
    - Append to YYYY-MM-DD.md in vault/Daily/
    - Add Obsidian frontmatter on new files
    - Include timestamps and source links
    - Emit note.written events
    """

    def __init__(self, plugin_dir: Path, manifest: Optional[PluginManifest] = None) -> None:
        """Initialize the daily writer plugin."""
        super().__init__(plugin_dir, manifest)
        self._vault_path: Optional[Path] = None
        self._daily_folder: Optional[Path] = None
        self._timezone: str = "America/New_York"
        self._config: dict[str, Any] = {}
        self._subscription: Optional[Any] = None

    def _load_config(self) -> None:
        """Load plugin configuration."""
        plugin_config = get_config().get("plugins", {}).get("daily_writer", {})

        # Default values
        default_vault_path = "~/Documents/Obsidian/Vault"
        default_daily_folder = "Daily"
        default_timezone = "America/New_York"

        # Get vault path
        vault_path = plugin_config.get("vault_path", default_vault_path)
        self._vault_path = Path(os.path.expanduser(vault_path))

        # Get daily folder
        daily_folder = plugin_config.get("daily_folder", default_daily_folder)
        self._daily_folder = self._vault_path / daily_folder

        # Create daily folder if needed
        self._daily_folder.mkdir(parents=True, exist_ok=True)

        # Get timezone
        self._timezone = plugin_config.get("timezone", default_timezone)

        self._config["timezone"] = self._timezone

        logger.info(
            f"Daily writer configured: vault={self._vault_path}, "
            f"daily={self._daily_folder}, tz={self._timezone}"
        )

    def _get_current_date(self) -> datetime:
        """Get current datetime in configured timezone."""
        try:
            import zoneinfo

            tz = zoneinfo.ZoneInfo(self._timezone)
        except (KeyError, ImportError):
            # Fallback to UTC if timezone not available
            tz = timezone.utc
        return datetime.now(tz)

    def _get_daily_file_path(self, date: datetime) -> Path:
        """Get the path to the daily file for a given date."""
        filename = f"{date.strftime('%Y-%m-%d')}.md"
        return self._daily_folder / filename

    def _create_frontmatter(self, date: datetime) -> str:
        """Create Obsidian frontmatter for a new daily note."""
        date_str = date.strftime("%Y-%m-%d")
        return f"""---
date: {date_str}
---

# {date.strftime("%B %d, %Y")}

"""

    def _format_entry(self, text: str, source: str, timestamp: datetime) -> str:
        """Format a note entry with timestamp and source."""
        time_str = timestamp.strftime("%H:%M")
        return f"""## {time_str}

{text}

_Source: {source}_

---

"""

    def _handle_note_routed(self, sender: Any, **kwargs: Any) -> None:
        """Handle note.routed events."""
        # Check if this note is destined for daily
        destination = kwargs.get("destination", "")
        if destination != "daily":
            return

        text = kwargs.get("text", "")
        if not text:
            return

        # Get source (default to "unknown")
        source = kwargs.get("source", "unknown")

        # Get timestamp
        timestamp_str = kwargs.get("timestamp")
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                timestamp = self._get_current_date()
        else:
            timestamp = self._get_current_date()

        # Get or create daily file
        daily_path = self._get_daily_file_path(timestamp)

        # Check if file exists
        is_new_file = not daily_path.exists()

        # Read existing content or create new
        if is_new_file:
            content = self._create_frontmatter(timestamp)
        else:
            content = safe_read(daily_path)
            if content is None:
                logger.error(f"Failed to read daily file: {daily_path}")
                return

        # Append new entry
        entry = self._format_entry(text, source, timestamp)
        content += entry

        # Write using safe_write
        result = safe_write(daily_path, content)

        if result["success"]:
            word_count = len(text.split())
            logger.info(f"Wrote note to {daily_path}")

            # Emit note.written event
            emit(
                note_written,
                sender="daily_writer",
                path=str(daily_path),
                timestamp=timestamp.isoformat(),
                word_count=word_count,
                source=source,
            )
        else:
            logger.error(f"Failed to write daily note: {result.get('error')}")

    def on_enable(self) -> None:
        """Enable the plugin and subscribe to events."""
        self._load_config()

        # Subscribe to note.routed events
        self._subscription = note_routed.connect(self._handle_note_routed)

        logger.info("Daily writer plugin enabled")

    def on_disable(self) -> None:
        """Disable the plugin and unsubscribe from events."""
        if self._subscription:
            note_routed.disconnect(self._handle_note_routed)
            self._subscription = None

        logger.info("Daily writer plugin disabled")

    def get_status(self) -> dict[str, Any]:
        """Get plugin status information."""
        return {
            "vault_path": str(self._vault_path) if self._vault_path else None,
            "daily_folder": str(self._daily_folder) if self._daily_folder else None,
            "timezone": self._timezone,
            "is_subscribed": self._subscription is not None,
        }

    def write_note(self, text: str, source: str = "manual") -> bool:
        """Write a note directly to today's daily file.

        Args:
            text: Note content to write
            source: Source identifier

        Returns:
            True if successful, False otherwise
        """
        if not self._vault_path:
            self._load_config()

        timestamp = self._get_current_date()

        # Get daily file path
        daily_path = self._get_daily_file_path(timestamp)

        # Check if file exists
        is_new_file = not daily_path.exists()

        # Read existing content or create new
        if is_new_file:
            content = self._create_frontmatter(timestamp)
        else:
            content = safe_read(daily_path)
            if content is None:
                logger.error(f"Failed to read daily file: {daily_path}")
                return False

        # Append new entry
        entry = self._format_entry(text, source, timestamp)
        content += entry

        # Write using safe_write
        result = safe_write(daily_path, content)

        if result["success"]:
            word_count = len(text.split())

            # Emit note.written event
            emit(
                note_written,
                sender="daily_writer",
                path=str(daily_path),
                timestamp=timestamp.isoformat(),
                word_count=word_count,
                source=source,
            )
            return True

        return False
