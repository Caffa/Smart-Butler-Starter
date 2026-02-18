"""Tests for the logging configuration system."""

import logging
import tempfile
from pathlib import Path

import pytest

from src.core.logging_config import (
    PluginLogAdapter,
    get_logger,
    get_plugin_logger,
    set_log_level,
    setup_logging,
)


class TestSetupLogging:
    """Test logging setup functionality."""

    def test_log_files_created(self) -> None:
        """Test that log files are created on setup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_logging(tmpdir)

            assert (Path(tmpdir) / "verbose.log").exists()
            assert (Path(tmpdir) / "error.log").exists()

    def test_log_directory_created(self) -> None:
        """Test that log directory is created if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "new_logs"
            assert not log_dir.exists()

            setup_logging(log_dir)

            assert log_dir.exists()

    def test_verbose_log_receives_debug(self) -> None:
        """Test that verbose.log receives DEBUG messages."""
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_logging(tmpdir, log_level="DEBUG")

            logger = logging.getLogger("test")
            logger.debug("Debug message")

            # Check verbose.log contains the message
            log_content = (Path(tmpdir) / "verbose.log").read_text()
            assert "Debug message" in log_content

    def test_error_log_only_warnings(self) -> None:
        """Test that error.log only receives WARNING and above."""
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_logging(tmpdir)

            logger = logging.getLogger("test")
            logger.info("Info message")
            logger.warning("Warning message")
            logger.error("Error message")

            # Check error.log only has warning and error
            error_content = (Path(tmpdir) / "error.log").read_text()
            assert "Warning message" in error_content
            assert "Error message" in error_content
            assert "Info message" not in error_content

    def test_verbose_log_has_all_levels(self) -> None:
        """Test that verbose.log has all log levels."""
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_logging(tmpdir)

            logger = logging.getLogger("test")
            logger.debug("Debug message")
            logger.info("Info message")
            logger.warning("Warning message")
            logger.error("Error message")

            verbose_content = (Path(tmpdir) / "verbose.log").read_text()
            assert "Debug message" in verbose_content
            assert "Info message" in verbose_content
            assert "Warning message" in verbose_content
            assert "Error message" in verbose_content


class TestPluginLogAdapter:
    """Test plugin attribution in logs."""

    def test_plugin_prefix_in_message(self) -> None:
        """Test that plugin name appears in log message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_logging(tmpdir)

            logger = get_logger("test", plugin="voice_capture")
            logger.info("Recording started")

            log_content = (Path(tmpdir) / "verbose.log").read_text()
            assert "[voice_capture] Recording started" in log_content

    def test_default_plugin_is_core(self) -> None:
        """Test that default plugin name is 'core'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_logging(tmpdir)

            logger = get_logger("test")  # No plugin specified
            logger.info("Core message")

            log_content = (Path(tmpdir) / "verbose.log").read_text()
            assert "[core] Core message" in log_content

    def test_different_plugins(self) -> None:
        """Test that different plugins have different prefixes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_logging(tmpdir)

            voice_logger = get_logger("test", plugin="voice")
            text_logger = get_logger("test", plugin="text")

            voice_logger.info("Voice input")
            text_logger.info("Text input")

            log_content = (Path(tmpdir) / "verbose.log").read_text()
            assert "[voice] Voice input" in log_content
            assert "[text] Text input" in log_content


class TestGetPluginLogger:
    """Test get_plugin_logger convenience function."""

    def test_plugin_logger_function(self) -> None:
        """Test get_plugin_logger creates properly attributed logger."""
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_logging(tmpdir)

            logger = get_plugin_logger("transcription")
            logger.info("Model loaded")

            log_content = (Path(tmpdir) / "verbose.log").read_text()
            assert "[transcription] Model loaded" in log_content


class TestLogRotation:
    """Test log rotation functionality."""

    def test_rotation_creates_backups(self) -> None:
        """Test that log rotation creates backup files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Set very small max size to trigger rotation
            setup_logging(tmpdir, max_bytes=100)

            logger = logging.getLogger("test")

            # Write enough to trigger rotation
            for i in range(20):
                logger.info(f"This is a long message that will fill up the log file quickly {i}")

            # Check for backup files
            log_dir = Path(tmpdir)
            backup_files = list(log_dir.glob("verbose.log.*"))

            # Should have created at least one backup
            assert len(backup_files) >= 1


class TestSetLogLevel:
    """Test dynamic log level changes."""

    def test_change_log_level(self) -> None:
        """Test that log level can be changed dynamically."""
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_logging(tmpdir, log_level="INFO")

            logger = logging.getLogger("test")

            # verbose.log always captures DEBUG+, so test with console behavior
            # First verify setup worked
            logger.info("Test message")

            verbose_content = (Path(tmpdir) / "verbose.log").read_text()
            assert "Test message" in verbose_content

            # Verify set_log_level doesn't error
            set_log_level("DEBUG")
            logger.debug("Debug after level change")

            verbose_content = (Path(tmpdir) / "verbose.log").read_text()
            assert "Debug after level change" in verbose_content


class TestLogFormat:
    """Test log message format."""

    def test_timestamp_in_logs(self) -> None:
        """Test that timestamps are included in logs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_logging(tmpdir)

            logger = logging.getLogger("test")
            logger.info("Test message")

            log_content = (Path(tmpdir) / "verbose.log").read_text()

            # Should have timestamp format YYYY-MM-DD HH:MM:SS
            import re

            timestamp_pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
            assert re.search(timestamp_pattern, log_content)

    def test_loglevel_in_logs(self) -> None:
        """Test that log level is included in logs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_logging(tmpdir)

            logger = logging.getLogger("test")
            logger.info("Info test")
            logger.error("Error test")

            log_content = (Path(tmpdir) / "verbose.log").read_text()

            assert "[INFO]" in log_content
            assert "[ERROR]" in log_content


class TestConsoleOutput:
    """Test console output option."""

    def test_console_output_disabled_by_default(self, capsys) -> None:
        """Test that console output is disabled by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_logging(tmpdir)

            logger = logging.getLogger("test")
            logger.info("Console test")

            # Should not appear in stderr
            captured = capsys.readouterr()
            assert "Console test" not in captured.err

    def test_console_output_enabled(self, capsys) -> None:
        """Test that console output can be enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_logging(tmpdir, console_output=True)

            logger = logging.getLogger("test")
            logger.info("Console enabled test")

            # Should appear in stderr
            captured = capsys.readouterr()
            assert "Console enabled test" in captured.err
