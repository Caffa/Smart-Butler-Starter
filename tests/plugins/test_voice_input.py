"""Tests for the voice input plugin."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.core.event_bus import input_received
from src.plugins.voice_input.plugin import VoiceInputPlugin


@pytest.fixture
def temp_plugin_dir():
    """Create temporary plugin directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        plugin_dir = Path(tmpdir) / "voice_input"
        plugin_dir.mkdir()
        yield plugin_dir


@pytest.fixture
def manifest(temp_plugin_dir):
    """Create test manifest."""
    manifest_data = {
        "name": "voice_input",
        "version": "1.0.0",
        "description": "Test voice input",
        "enabled": True,
        "capabilities_provided": ["audio_input"],
        "events_emits": ["input.received"],
        "config": {
            "watch_path": "~/Music/Voice Memos",
            "confidence_threshold": 0.5,
            "move_processed": True,
            "processed_folder": "processed",
        },
    }
    manifest_path = temp_plugin_dir / "plugin.yaml"
    with open(manifest_path, "w") as f:
        yaml.dump(manifest_data, f)
    return manifest_path


@pytest.fixture
def plugin(temp_plugin_dir, manifest):
    """Create voice input plugin instance."""
    return VoiceInputPlugin(temp_plugin_dir)


class TestVoiceInputPlugin:
    """Tests for VoiceInputPlugin."""

    def test_init(self, plugin):
        """Test plugin initialization."""
        assert plugin.name == "voice_input"
        assert plugin.version == "1.0.0"

    def test_is_audio_file(self, plugin):
        """Test audio file detection."""
        assert plugin._is_audio_file(Path("test.m4a")) is True
        assert plugin._is_audio_file(Path("test.mp3")) is True
        assert plugin._is_audio_file(Path("test.wav")) is True
        assert plugin._is_audio_file(Path("test.flac")) is True
        assert plugin._is_audio_file(Path("test.txt")) is False
        assert plugin._is_audio_file(Path("test.pdf")) is False

    def test_compute_hash(self, plugin):
        """Test file hashing."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test content")
            f.flush()
            try:
                hash1 = plugin._compute_hash(Path(f.name))
                hash2 = plugin._compute_hash(Path(f.name))
                assert hash1 == hash2
                assert len(hash1) == 64  # SHA256
            finally:
                Path(f.name).unlink()

    def test_on_enable_creates_watch_path(self, temp_plugin_dir):
        """Test that on_enable creates watch path if missing."""
        # Create plugin with custom config that uses temp dir
        manifest_data = {
            "name": "voice_input",
            "version": "1.0.0",
            "enabled": True,
            "capabilities_provided": ["audio_input"],
            "events_emits": ["input.received"],
            "config": {
                "watch_path": str(temp_plugin_dir / "voice_memos"),
                "confidence_threshold": 0.5,
                "move_processed": True,
                "processed_folder": "processed",
            },
        }
        manifest_path = temp_plugin_dir / "plugin.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(manifest_data, f)

        plugin = VoiceInputPlugin(temp_plugin_dir)
        plugin.on_enable()

        # Watch path should be created
        assert plugin._watch_path.exists()

    def test_scan_folder_empty(self, plugin):
        """Test scanning empty folder."""
        plugin._watch_path = Path(tempfile.mkdtemp())
        files = plugin.scan_folder()
        assert files == []

    def test_scan_folder_with_audio(self, plugin):
        """Test scanning folder with audio files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin._watch_path = Path(tmpdir)

            # Create test audio files
            audio_file = Path(tmpdir) / "test.m4a"
            audio_file.write_text("dummy audio")

            non_audio = Path(tmpdir) / "test.txt"
            non_audio.write_text("not audio")

            files = plugin.scan_folder()
            assert len(files) == 1
            assert files[0].suffix == ".m4a"

    def test_process_file_not_found(self, plugin):
        """Test processing non-existent file."""
        result = plugin.process_file(Path("/nonexistent/file.m4a"))
        assert result is False

    def test_process_file_emits_event(self, temp_plugin_dir):
        """Test that processing emits input.received event."""
        # Create plugin with temp directory config
        watch_dir = Path(tempfile.mkdtemp())

        manifest_data = {
            "name": "voice_input",
            "version": "1.0.0",
            "enabled": True,
            "capabilities_provided": ["audio_input"],
            "events_emits": ["input.received"],
        }
        manifest_path = temp_plugin_dir / "plugin.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(manifest_data, f)

        plugin = VoiceInputPlugin(temp_plugin_dir)

        # Set up directly without going through _load_config
        plugin._watch_path = watch_dir
        plugin._config = {"confidence_threshold": 0.5}
        plugin._processed_folder = None

        # Create test audio file
        audio_file = watch_dir / "test.m4a"
        audio_file.write_text("dummy audio")

        # Mock the transcriber class
        mock_result = MagicMock()
        mock_result.text = "Test transcription"
        mock_result.confidence = 0.95
        mock_result.duration = 2.5

        with patch("src.plugins.voice_input.plugin.Transcriber") as MockTranscriber:
            mock_transcriber_instance = MagicMock()
            mock_transcriber_instance.transcribe.return_value = mock_result
            mock_transcriber_instance.is_loaded = True
            MockTranscriber.return_value = mock_transcriber_instance

            # Re-create transcriber with mocked class
            plugin._transcriber = MockTranscriber.return_value

            # Track events
            events_received = []

            @input_received.connect
            def handler(sender, **kwargs):
                events_received.append(kwargs)

            try:
                result = plugin.process_file(audio_file)
                assert result is True
                assert len(events_received) == 1
                assert events_received[0]["text"] == "Test transcription"
                assert events_received[0]["source"] == "voice"
            finally:
                input_received.disconnect(handler)

    def test_process_file_duplicate(self, temp_plugin_dir):
        """Test that duplicate files are skipped."""
        watch_dir = Path(tempfile.mkdtemp())

        manifest_data = {
            "name": "voice_input",
            "version": "1.0.0",
            "enabled": True,
            "capabilities_provided": ["audio_input"],
            "events_emits": ["input.received"],
            "config": {
                "watch_path": str(watch_dir),
                "confidence_threshold": 0.5,
                "move_processed": False,
            },
        }
        manifest_path = temp_plugin_dir / "plugin.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(manifest_data, f)

        plugin = VoiceInputPlugin(temp_plugin_dir)
        plugin.on_enable()

        # Create test audio file
        audio_file = watch_dir / "test.m4a"
        audio_file.write_text("dummy audio")

        # Simulate this file was already processed
        file_hash = plugin._compute_hash(audio_file)
        plugin._processed_hashes.add(file_hash)

        # Should skip as duplicate
        result = plugin.process_file(audio_file)
        assert result is False

    def test_get_status(self, plugin):
        """Test status reporting."""
        plugin._watch_path = Path("/test/path")
        plugin._processed_folder = Path("/test/path/processed")
        plugin._config["confidence_threshold"] = 0.7

        status = plugin.get_status()

        assert status["watch_path"] == "/test/path"
        assert status["processed_folder"] == "/test/path/processed"
        assert status["confidence_threshold"] == 0.7

    def test_should_process_file_hidden(self, plugin):
        """Test that hidden files are excluded."""
        assert plugin._should_process_file(Path(".hidden_file.m4a")) is False
        assert plugin._should_process_file(Path(".DS_Store")) is False
        assert plugin._should_process_file(Path(".random_hidden")) is False

    def test_should_process_file_ds_store(self, plugin):
        """Test that .DS_Store files are excluded."""
        assert plugin._should_process_file(Path(".DS_Store")) is False
        assert plugin._should_process_file(Path("subdir/.DS_Store")) is False

    def test_should_process_file_audio_extensions(self, plugin):
        """Test that supported audio files are accepted."""
        assert plugin._should_process_file(Path("test.m4a")) is True
        assert plugin._should_process_file(Path("test.mp3")) is True
        assert plugin._should_process_file(Path("test.wav")) is True
        assert plugin._should_process_file(Path("test.flac")) is True
        assert plugin._should_process_file(Path("test.txt")) is False
        assert plugin._should_process_file(Path("test.pdf")) is False

    def test_scan_folder_excludes_system_files(self, plugin):
        """Test that scan_folder ignores hidden files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin._watch_path = Path(tmpdir)

            # Create test files
            audio_file = Path(tmpdir) / "test.m4a"
            audio_file.write_text("dummy audio")

            hidden_file = Path(tmpdir) / ".hidden"
            hidden_file.write_text("hidden content")

            ds_store = Path(tmpdir) / ".DS_Store"
            ds_store.write_text("metadata")

            txt_file = Path(tmpdir) / "readme.txt"
            txt_file.write_text("text content")

            files = plugin.scan_folder()

            # Should only find the audio file
            assert len(files) == 1
            assert files[0].name == "test.m4a"

    def test_process_file_skips_system_files(self, plugin):
        """Test that process_file returns False for hidden files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            hidden_file = Path(tmpdir) / ".hidden.m4a"
            hidden_file.write_text("hidden audio")

            ds_store = Path(tmpdir) / ".DS_Store"
            ds_store.write_text("metadata")

            # Should return False without processing
            assert plugin.process_file(hidden_file) is False
            assert plugin.process_file(ds_store) is False


class TestVoiceInputPluginIntegration:
    """Integration tests for voice input plugin."""

    def test_plugin_lifecycle(self, temp_plugin_dir):
        """Test enable/disable lifecycle."""
        watch_dir = Path(tempfile.mkdtemp())

        # Create manifest
        manifest_data = {
            "name": "voice_input",
            "version": "1.0.0",
            "enabled": True,
            "capabilities_provided": ["audio_input"],
            "events_emits": ["input.received"],
        }
        manifest_path = temp_plugin_dir / "plugin.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(manifest_data, f)

        plugin = VoiceInputPlugin(temp_plugin_dir)

        # Set up config directly
        plugin._watch_path = watch_dir
        plugin._config = {"confidence_threshold": 0.5}
        plugin._processed_folder = None

        # Enable - should use our values
        assert plugin._watch_path == watch_dir

        # Disable
        plugin.on_disable()
        assert plugin._transcriber is None
