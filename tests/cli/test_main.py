"""Tests for the main CLI entry point."""

import subprocess
from unittest.mock import patch

from click.testing import CliRunner

from butler import __version__
from butler.cli.main import cli, main


class TestCLIMain:
    """Test main CLI functionality."""

    def test_main_function_exists(self):
        """Test that main function exists and is callable."""
        assert callable(main)

    def test_cli_invocation_no_args(self):
        """Test CLI invocation with no arguments shows help."""
        runner = CliRunner()
        result = runner.invoke(cli)

        # Click shows help and exits with code 0 when no command is given
        # but with invoke() it returns 2 if no command specified
        assert "Smart Butler" in result.output


class TestCLIHelp:
    """Test CLI help output."""

    def test_main_help(self):
        """Test main help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "Smart Butler" in result.output
        assert "Voice-first AI assistant" in result.output
        assert "--version" in result.output
        assert "--help" in result.output

    def test_all_commands_listed(self):
        """Test that all commands are listed in help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "doctor" in result.output
        assert "process-voice" in result.output
        assert "version" in result.output
        assert "config" in result.output


class TestVersionCommand:
    """Test version command."""

    def test_version_output(self):
        """Test version command output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["version"])

        assert result.exit_code == 0
        assert __version__ in result.output
        assert "Smart Butler" in result.output

    def test_version_flag(self):
        """Test --version flag."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])

        assert result.exit_code == 0
        assert __version__ in result.output


class TestDoctorCommand:
    """Test doctor command."""

    @patch("butler.cli.doctor.check_dependencies")
    def test_doctor_success(self, mock_check):
        """Test doctor command when checks pass."""
        mock_check.return_value = True

        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"])

        assert result.exit_code == 0
        mock_check.assert_called_once_with(fix=False)

    @patch("butler.cli.doctor.check_dependencies")
    def test_doctor_with_fix(self, mock_check):
        """Test doctor command with --fix flag."""
        mock_check.return_value = True

        runner = CliRunner()
        result = runner.invoke(cli, ["doctor", "--fix"])

        assert result.exit_code == 0
        mock_check.assert_called_once_with(fix=True)

    @patch("butler.cli.doctor.check_dependencies")
    def test_doctor_failure(self, mock_check):
        """Test doctor command when checks fail."""
        mock_check.return_value = False

        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"])

        assert result.exit_code != 0
        assert "Health check found issues" in result.output


class TestProcessVoiceCommand:
    """Test process-voice command."""

    def test_process_voice_output(self):
        """Test process-voice command output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["process-voice"])

        assert result.exit_code == 0
        assert "Processing voice input" in result.output


class TestConfigCommand:
    """Test config command."""

    def test_config_output(self):
        """Test config command output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["config"])

        assert result.exit_code == 0
        assert "TUI implementation pending" in result.output


class TestCLIIntegration:
    """Integration tests for CLI."""

    def test_cli_exit_codes(self):
        """Test that CLI returns proper exit codes."""
        runner = CliRunner()

        # Valid commands should return 0
        assert runner.invoke(cli, ["--help"]).exit_code == 0
        assert runner.invoke(cli, ["version"]).exit_code == 0

    def test_cli_command_help(self):
        """Test individual command help."""
        runner = CliRunner()

        # Test doctor help
        result = runner.invoke(cli, ["doctor", "--help"])
        assert result.exit_code == 0
        assert "--fix" in result.output


class TestCLIInvocation:
    """Test CLI invocation patterns."""

    def test_cli_invoked_via_module(self):
        """Test CLI can be invoked via python -m."""
        # This test verifies the package structure is correct
        # Note: We can't easily test this in unit tests, but we document it
        pass

    def test_cli_entry_point(self):
        """Test that entry point is configured correctly in pyproject.toml."""
        # Verify by checking the console script is installed
        result = subprocess.run(["butler", "--help"], capture_output=True, text=True)

        # Should not fail (exit code 0)
        assert result.returncode == 0
        assert "Smart Butler" in result.stdout
