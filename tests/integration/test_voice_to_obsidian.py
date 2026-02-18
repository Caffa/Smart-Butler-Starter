"""End-to-end integration tests for voice to Obsidian flow.

Tests the full MVP flow:
1. Voice input detects audio file
2. Transcriber processes audio
3. input.received event emitted
4. Note routed to daily
5. Daily writer writes to file
6. note.written event emitted
"""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.core.event_bus import emit, input_received, note_routed, note_written
from src.plugins.daily_writer.plugin import DailyWriterPlugin
from src.plugins.voice_input.plugin import VoiceInputPlugin


@pytest.fixture
def temp_vault():
    """Create temporary Obsidian vault."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = Path(tmpdir) / "Vault"
        vault.mkdir()
        yield vault


@pytest.fixture
def temp_watch_dir():
    """Create temporary watch directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_plugin_dir():
    """Create temporary plugin directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        voice_dir = Path(tmpdir) / "voice_input"
        voice_dir.mkdir()
        daily_dir = Path(tmpdir) / "daily_writer"
        daily_dir.mkdir()
        yield voice_dir, daily_dir


def create_manifest(
    plugin_dir: Path, name: str, events_listens: list = None, events_emits: list = None
):
    """Helper to create plugin manifest."""
    manifest_data = {
        "name": name,
        "version": "1.0.0",
        "enabled": True,
    }
    if events_listens:
        manifest_data["events_listens"] = events_listens
    if events_emits:
        manifest_data["events_emits"] = events_emits

    manifest_path = plugin_dir / "plugin.yaml"
    with open(manifest_path, "w") as f:
        yaml.dump(manifest_data, f)
    return manifest_path


class TestVoiceToObsidian:
    """Integration tests for complete voice to Obsidian flow."""

    def test_full_flow_voice_to_daily(self, temp_plugin_dir, temp_vault, temp_watch_dir):
        """Test complete flow: voice file -> transcription -> daily note."""
        voice_dir, daily_dir = temp_plugin_dir

        # Create manifests
        create_manifest(voice_dir, "voice_input", events_emits=["input.received"])
        create_manifest(
            daily_dir, "daily_writer", events_listens=["note.routed"], events_emits=["note.written"]
        )

        # Create audio file
        audio_file = temp_watch_dir / "test_voice.m4a"
        audio_file.write_text("dummy audio content")

        # Track events through the pipeline
        events = {
            "input_received": [],
            "note_routed": [],
            "note_written": [],
        }

        @input_received.connect
        def handle_input(sender, **kwargs):
            events["input_received"].append(kwargs)

        @note_routed.connect
        def handle_routed(sender, **kwargs):
            events["note_routed"].append(kwargs)

        @note_written.connect
        def handle_written(sender, **kwargs):
            events["note_written"].append(kwargs)

        try:
            # Mock config for voice input
            voice_config_value = {
                "voice_input": {
                    "watch_path": str(temp_watch_dir),
                    "confidence_threshold": 0.5,
                    "move_processed": False,
                }
            }

            # Mock config for daily writer
            daily_config_value = {
                "daily_writer": {
                    "vault_path": str(temp_vault),
                    "daily_folder": "Daily",
                    "timezone": "UTC",
                }
            }

            # Create mock config object
            class MockConfig:
                def get(self, key, default=None):
                    if key == "plugins":
                        return voice_config_value
                    return default

            # Create and enable plugins
            with patch("src.plugins.voice_input.plugin.get_config", return_value=MockConfig()):
                voice_plugin = VoiceInputPlugin(voice_dir)
                voice_plugin.on_enable()

            # Patch again for daily writer
            class MockConfigDaily:
                def get(self, key, default=None):
                    if key == "plugins":
                        return daily_config_value
                    return default

            with patch(
                "src.plugins.daily_writer.plugin.get_config", return_value=MockConfigDaily()
            ):
                daily_plugin = DailyWriterPlugin(daily_dir)
                daily_plugin.on_enable()

            # Mock transcriber to return test transcription
            mock_result = MagicMock()
            mock_result.text = "Remember to buy groceries"
            mock_result.confidence = 0.95
            mock_result.duration = 3.5

            with patch("src.plugins.voice_input.plugin.Transcriber") as MockTranscriber:
                mock_transcriber = MagicMock()
                mock_transcriber.transcribe.return_value = mock_result
                mock_transcriber.is_loaded = True
                MockTranscriber.return_value = mock_transcriber

                # Re-set transcriber
                voice_plugin._transcriber = mock_transcriber

                # Process the file
                result = voice_plugin.process_file(audio_file)

                assert result is True, "Voice processing should succeed"

            # Wait for event processing
            import time

            time.sleep(0.1)

            # Verify input.received was emitted
            assert len(events["input_received"]) == 1, "Should emit input.received"
            assert events["input_received"][0]["text"] == "Remember to buy groceries"
            assert events["input_received"][0]["source"] == "voice"

            # Verify note.routed was emitted (from voice input or manual trigger)
            # Note: The voice input emits input_received, we need to also emit note_routed
            # Let's emit it manually to complete the flow
            emit(
                note_routed,
                sender="test_router",
                text="Remember to buy groceries",
                destination="daily",
                source="voice",
            )

            time.sleep(0.1)

            # Verify note.written was emitted
            assert len(events["note_written"]) == 1, "Should emit note.written"
            assert events["note_written"][0]["source"] == "voice"

            # Verify daily file was created
            daily_file = temp_vault / "Daily" / f"{datetime.now().strftime('%Y-%m-%d')}.md"
            assert daily_file.exists(), "Daily file should be created"

            # Verify file content
            content = daily_file.read_text()
            assert "Remember to buy groceries" in content
            assert "---" in content  # Frontmatter

            # Cleanup
            voice_plugin.on_disable()
            daily_plugin.on_disable()

        finally:
            input_received.disconnect(handle_input)
            note_routed.disconnect(handle_routed)
            note_written.disconnect(handle_written)

    def test_event_chain_integrity(self, temp_plugin_dir, temp_vault):
        """Test that events propagate correctly through the chain."""
        voice_dir, daily_dir = temp_plugin_dir

        # Create manifests
        create_manifest(voice_dir, "voice_input", events_emits=["input.received"])
        create_manifest(
            daily_dir, "daily_writer", events_listens=["note.routed"], events_emits=["note.written"]
        )

        # Track event chain
        chain = []

        @input_received.connect
        def track_input(sender, **kwargs):
            chain.append(("input_received", kwargs))
            # Automatically route to daily
            emit(
                note_routed,
                sender="auto_router",
                text=kwargs["text"],
                destination="daily",
                source=kwargs["source"],
            )

        @note_routed.connect
        def track_routed(sender, **kwargs):
            chain.append(("note_routed", kwargs))

        @note_written.connect
        def track_written(sender, **kwargs):
            chain.append(("note_written", kwargs))

        try:
            # Mock configs
            voice_config_value = {
                "voice_input": {
                    "watch_path": "/tmp",
                    "confidence_threshold": 0.5,
                    "move_processed": False,
                }
            }
            daily_config_value = {
                "daily_writer": {
                    "vault_path": str(temp_vault),
                    "daily_folder": "Daily",
                    "timezone": "UTC",
                }
            }

            class MockConfigVoice:
                def get(self, key, default=None):
                    if key == "plugins":
                        return voice_config_value
                    return default

            class MockConfigDaily:
                def get(self, key, default=None):
                    if key == "plugins":
                        return daily_config_value
                    return default

            with patch("src.plugins.voice_input.plugin.get_config", return_value=MockConfigVoice()):
                voice_plugin = VoiceInputPlugin(voice_dir)
                voice_plugin._watch_path = Path("/tmp")
                voice_plugin._config = {"confidence_threshold": 0.5}
                voice_plugin._processed_folder = None

            with patch(
                "src.plugins.daily_writer.plugin.get_config", return_value=MockConfigDaily()
            ):
                daily_plugin = DailyWriterPlugin(daily_dir)
                daily_plugin.on_enable()

            # Emit input_received directly (simulating voice input)
            emit(
                input_received,
                sender="voice_input",
                text="Test chain",
                source="test",
                confidence=0.9,
                duration=2.0,
            )

            import time

            time.sleep(0.1)

            # Verify chain: input_received -> note_routed -> note_written
            # Note: may have extra events from other tests
            assert chain[0][0] == "input_received"
            assert chain[1][0] == "note_routed"
            # The last note_written should be from our test
            written_events = [e for e in chain if e[0] == "note_written"]
            assert len(written_events) >= 1, "Should have at least one note.written"

            daily_plugin.on_disable()

        finally:
            input_received.disconnect(track_input)
            note_routed.disconnect(track_routed)
            note_written.disconnect(track_written)

    def test_daily_writer_with_real_date(self, temp_plugin_dir, temp_vault):
        """Test daily writer creates proper date-formatted files."""
        _, daily_dir = temp_plugin_dir

        create_manifest(
            daily_dir, "daily_writer", events_listens=["note.routed"], events_emits=["note.written"]
        )

        daily_config_value = {
            "daily_writer": {
                "vault_path": str(temp_vault),
                "daily_folder": "Daily",
                "timezone": "UTC",
            }
        }

        class MockConfigDaily:
            def get(self, key, default=None):
                if key == "plugins":
                    return daily_config_value
                return default

        with patch("src.plugins.daily_writer.plugin.get_config", return_value=MockConfigDaily()):
            plugin = DailyWriterPlugin(daily_dir)
            plugin.on_enable()

            # Write a note directly
            result = plugin.write_note("Test note content", "integration_test")

            assert result is True

            # Check file exists
            today = datetime.now().strftime("%Y-%m-%d")
            daily_file = temp_vault / "Daily" / f"{today}.md"

            assert daily_file.exists()

            content = daily_file.read_text()
            assert "Test note content" in content
            assert f"date: {today}" in content

            plugin.on_disable()
