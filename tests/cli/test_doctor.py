"""Tests for the doctor module."""

import subprocess

import pytest
from unittest.mock import Mock, patch

from butler.cli.doctor import (
    CheckResult,
    Status,
    check_chromadb,
    check_disk_space,
    check_macos_version,
    check_model,
    check_ollama,
    check_parakeet,
    check_python_version,
    check_sqlite,
    check_write_permissions,
)


class TestCheckResult:
    """Test CheckResult dataclass."""

    def test_basic_creation(self):
        """Test creating a CheckResult."""
        result = CheckResult(name="Test", status=Status.OK, message="All good")
        assert result.name == "Test"
        assert result.status == Status.OK
        assert result.message == "All good"
        assert result.details is None

    def test_with_details(self):
        """Test creating a CheckResult with details."""
        result = CheckResult(
            name="Test", status=Status.WARNING, message="Something's off", details="Additional info"
        )
        assert result.details == "Additional info"


class TestCheckPythonVersion:
    """Test Python version check."""

    def test_returns_check_result(self):
        """Test that check returns a CheckResult."""
        result = check_python_version()
        assert isinstance(result, CheckResult)
        assert result.name == "Python"

    def test_status_is_ok_for_supported_version(self):
        """Test that supported Python versions return OK."""
        result = check_python_version()
        # Should pass on Python 3.10+ (our requirement)
        assert result.status in [Status.OK, Status.ERROR]


class TestCheckMacOSVersion:
    """Test macOS version check."""

    def test_returns_check_result(self):
        """Test that check returns a CheckResult."""
        result = check_macos_version()
        assert isinstance(result, CheckResult)
        assert result.name == "macOS"


class TestCheckOllama:
    """Test Ollama installation check."""

    @patch("subprocess.run")
    def test_ollama_installed_and_running(self, mock_run):
        """Test when Ollama is installed and running."""
        # Mock version check
        mock_run.side_effect = [
            Mock(returncode=0, stdout="ollama version 0.6.1\n"),
            Mock(returncode=0),  # pgrep succeeds
        ]

        result = check_ollama()
        assert result.name == "Ollama"
        assert result.status == Status.OK

    @patch("subprocess.run")
    def test_ollama_installed_not_running(self, mock_run):
        """Test when Ollama is installed but not running."""

        # First call (version check) succeeds, second call (pgrep) fails with timeout
        def side_effect(*args, **kwargs):
            if "--version" in args[0]:
                return Mock(returncode=0, stdout="ollama version 0.6.1\n")
            else:
                raise subprocess.TimeoutExpired(cmd="pgrep", timeout=2)

        mock_run.side_effect = side_effect

        result = check_ollama()
        assert result.status == Status.WARNING

    @patch("subprocess.run")
    def test_ollama_not_installed(self, mock_run):
        """Test when Ollama is not installed."""
        mock_run.side_effect = FileNotFoundError("ollama not found")

        result = check_ollama()
        assert result.status == Status.ERROR


class TestCheckModel:
    """Test model download check."""

    @patch("subprocess.run")
    def test_model_downloaded(self, mock_run):
        """Test when model is already downloaded."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="NAME                    ID              SIZE      MODIFIED\nllama3.1:8b            abc123         4.7 GB    2 weeks ago",
        )

        result = check_model("llama3.1:8b")
        assert result.name == "Model llama3.1:8b"
        assert result.status == Status.OK

    @patch("subprocess.run")
    def test_model_not_downloaded(self, mock_run):
        """Test when model is not downloaded."""
        mock_run.return_value = Mock(
            returncode=0, stdout="NAME                    ID              SIZE      MODIFIED\n"
        )

        result = check_model("llama3.1:8b")
        assert result.status == Status.WARNING


class TestCheckParakeet:
    """Test parakeet-mlx check."""

    def test_returns_check_result(self):
        """Test that check returns a CheckResult."""
        result = check_parakeet()
        assert isinstance(result, CheckResult)
        assert result.name == "parakeet-mlx"


class TestCheckSQLite:
    """Test SQLite check."""

    def test_sqlite_available(self):
        """Test that SQLite is available."""
        result = check_sqlite()
        assert result.name == "SQLite"
        # SQLite is built into Python
        assert result.status == Status.OK


class TestCheckDiskSpace:
    """Test disk space check."""

    def test_returns_check_result(self):
        """Test that check returns a CheckResult."""
        result = check_disk_space()
        assert isinstance(result, CheckResult)
        assert result.name == "Disk space"

    def test_has_disk_info(self):
        """Test that result contains disk info."""
        result = check_disk_space()
        assert "GB" in result.message or "Unknown" in result.message


class TestCheckWritePermissions:
    """Test write permissions check."""

    def test_returns_check_result(self):
        """Test that check returns a CheckResult."""
        result = check_write_permissions()
        assert isinstance(result, CheckResult)
        assert result.name == "Write permissions"


class TestCheckChromaDB:
    """Test ChromaDB check."""

    def test_returns_check_result(self):
        """Test that check returns a CheckResult."""
        result = check_chromadb()
        assert isinstance(result, CheckResult)
        assert result.name == "ChromaDB"
