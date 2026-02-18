"""Tests for the daily writer plugin."""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.core.event_bus import emit, note_routed, note_written
from src.plugins.daily_writer.plugin import DailyWriterPlugin


@pytest.fixture
def temp_plugin_dir():
    """Create temporary plugin directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        plugin_dir = Path(tmpdir) / "daily_writer"
        plugin_dir.mkdir()
        yield plugin_dir


@pytest.fixture
def manifest(temp_plugin_dir):
    """Create test manifest."""
    manifest_data = {
        "name": "daily_writer",
        "version": "1.0.0",
        "description": "Test daily writer",
        "enabled": True,
        "events_listens": ["note.routed"],
        "events_emits": ["note.written"],
        "config": {
            "vault_path": "~/Documents/Obsidian/Vault",
            "daily_folder": "Daily",
            "timezone": "America/New_York",
        },
    }
    manifest_path = temp_plugin_dir / "plugin.yaml"
    with open(manifest_path, "w") as f:
        yaml.dump(manifest_data, f)
    return manifest_path


@pytest.fixture
def plugin(temp_plugin_dir, manifest):
    """Create daily writer plugin instance."""
    return DailyWriterPlugin(temp_plugin_dir)


class TestDailyWriterPlugin:
    """Tests for DailyWriterPlugin."""

    def test_init(self, plugin):
        """Test plugin initialization."""
        assert plugin.name == "daily_writer"
        assert plugin.version == "1.0.0"

    def test_get_current_date(self, plugin):
        """Test getting current date with timezone."""
        with patch("src.plugins.daily_writer.plugin.get_config") as mock_config:
            mock_config.return_value.get.return_value = {}

            date = plugin._get_current_date()
            assert isinstance(date, datetime)

    def test_get_daily_file_path(self, plugin):
        """Test daily file path generation."""
        test_date = datetime(2025, 1, 15, 10, 30)

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin._daily_folder = Path(tmpdir)

            path = plugin._get_daily_file_path(test_date)
            assert path.name == "2025-01-15.md"
            assert path.parent == Path(tmpdir)

    def test_create_frontmatter(self, plugin):
        """Test frontmatter creation."""
        test_date = datetime(2025, 1, 15, 10, 30)

        frontmatter = plugin._create_frontmatter(test_date)

        assert "---" in frontmatter
        assert "date: 2025-01-15" in frontmatter
        assert "# January 15, 2025" in frontmatter

    def test_format_entry(self, plugin):
        """Test entry formatting."""
        timestamp = datetime(2025, 1, 15, 14, 30)

        entry = plugin._format_entry("Test note content", "voice", timestamp)

        assert "## 14:30" in entry
        assert "Test note content" in entry
        assert "_Source: voice_" in entry

    def test_handle_note_routed_non_daily(self, plugin):
        """Test that non-daily destinations are ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin._daily_folder = Path(tmpdir)
            plugin._timezone = "UTC"

            # Track if note.written was emitted
            written_events = []

            @note_written.connect
            def handler(sender, **kwargs):
                written_events.append(kwargs)

            try:
                plugin._handle_note_routed(
                    sender="test",
                    text="Test note",
                    destination="inbox",  # Not "daily"
                    source="test",
                )

                # Should not emit note.written
                assert len(written_events) == 0
            finally:
                note_written.disconnect(handler)

    def test_handle_note_routed_daily(self, plugin):
        """Test that daily notes are written."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin._vault_path = Path(tmpdir)
            plugin._daily_folder = Path(tmpdir) / "Daily"
            plugin._daily_folder.mkdir()
            plugin._timezone = "UTC"

            # Track if note.written was emitted
            written_events = []

            @note_written.connect
            def handler(sender, **kwargs):
                written_events.append(kwargs)

            try:
                # Mock _get_current_date to return a fixed date
                with patch.object(plugin, "_get_current_date") as mock_date:
                    mock_date.return_value = datetime(2025, 1, 15, 14, 30)

                    plugin._handle_note_routed(
                        sender="test",
                        text="Test voice note",
                        destination="daily",
                        source="voice",
                    )

                    # Should emit note.written
                    assert len(written_events) == 1
                    assert "path" in written_events[0]
                    assert written_events[0]["source"] == "voice"

                    # Check file was created
                    daily_file = plugin._daily_folder / "2025-01-15.md"
                    assert daily_file.exists()
            finally:
                note_written.disconnect(handler)

    def test_on_enable_subscribes(self, plugin):
        """Test that on_enable subscribes to events."""
        with patch("src.plugins.daily_writer.plugin.get_config") as mock_config:
            mock_config.return_value.get.return_value = {}

            plugin.on_enable()
            assert plugin._subscription is not None

            plugin.on_disable()

    def test_on_disable_unsubscribes(self, plugin):
        """Test that on_disable unsubscribes from events."""
        with patch("src.plugins.daily_writer.plugin.get_config") as mock_config:
            mock_config.return_value.get.return_value = {}

            plugin.on_enable()
            assert plugin._subscription is not None

            plugin.on_disable()
            assert plugin._subscription is None

    def test_get_status(self, plugin):
        """Test status reporting."""
        plugin._vault_path = Path("/test/vault")
        plugin._daily_folder = Path("/test/vault/Daily")
        plugin._timezone = "America/New_York"

        status = plugin.get_status()

        assert status["vault_path"] == "/test/vault"
        assert status["daily_folder"] == "/test/vault/Daily"
        assert status["timezone"] == "America/New_York"

    def test_write_note(self, plugin):
        """Test writing a note directly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin._vault_path = Path(tmpdir)
            plugin._daily_folder = Path(tmpdir) / "Daily"
            plugin._daily_folder.mkdir()
            plugin._timezone = "UTC"

            # Mock _get_current_date
            with patch.object(plugin, "_get_current_date") as mock_date:
                mock_date.return_value = datetime(2025, 1, 15, 14, 30)

                result = plugin.write_note("Direct test note", "test")

                assert result is True

                # Check file was created
                daily_file = plugin._daily_folder / "2025-01-15.md"
                assert daily_file.exists()
                assert "Direct test note" in daily_file.read_text()


class TestDailyWriterPluginIntegration:
    """Integration tests for daily writer plugin."""

    def test_full_flow(self, temp_plugin_dir):
        """Test complete flow from note.routed to note.written."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir)

            # Create manifest
            manifest_data = {
                "name": "daily_writer",
                "version": "1.0.0",
                "enabled": True,
                "events_listens": ["note.routed"],
                "events_emits": ["note.written"],
            }
            manifest_path = temp_plugin_dir / "plugin.yaml"
            with open(manifest_path, "w") as f:
                yaml.dump(manifest_data, f)

            # Mock config
            mock_config = MagicMock()
            mock_config.get.return_value = {
                "vault_path": str(vault_path),
                "daily_folder": "Daily",
                "timezone": "UTC",
            }

            with patch("src.plugins.daily_writer.plugin.get_config", return_value=mock_config):
                plugin = DailyWriterPlugin(temp_plugin_dir)
                plugin.on_enable()

                # Track events
                routed_events = []
                written_events = []

                @note_routed.connect
                def routed_handler(sender, **kwargs):
                    routed_events.append(kwargs)

                @note_written.connect
                def written_handler(sender, **kwargs):
                    written_events.append(kwargs)

                try:
                    # Emit a note.routed event
                    emit(
                        note_routed,
                        sender="test",
                        text="Integration test note",
                        destination="daily",
                        source="integration_test",
                    )

                    # Wait a moment for processing
                    import time

                    time.sleep(0.1)

                    # Check events
                    assert len(routed_events) == 1
                    assert len(written_events) == 1
                    assert written_events[0]["source"] == "integration_test"

                finally:
                    note_routed.disconnect(routed_handler)
                    note_written.disconnect(written_handler)
                    plugin.on_disable()
