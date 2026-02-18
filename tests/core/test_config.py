"""Tests for the configuration system."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from src.core.config import Config, ConfigError, get_config, reset_config


class TestConfigBasics:
    """Test basic configuration functionality."""

    def test_default_config_creation(self) -> None:
        """Test that default config is created on first run."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)

            # Check default values
            assert config.get("vault.path") == "~/Documents/Obsidian"
            assert config.get("logging.level") == "INFO"
            assert config.get("features.auto_start") is False

    def test_config_file_created(self) -> None:
        """Test that config file is created if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.yaml"
            assert not config_file.exists()

            config = Config(config_dir=tmpdir)

            # File should be created with defaults
            assert config_file.exists()

    def test_directories_created(self) -> None:
        """Test that directory structure is auto-created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)

            assert (Path(tmpdir) / "plugins").exists()
            assert (Path(tmpdir) / "data").exists()
            assert (Path(tmpdir) / "logs").exists()

    def test_nested_access(self) -> None:
        """Test dot notation access to nested values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)

            # Nested access
            assert config.get("vault.path") == "~/Documents/Obsidian"
            assert config.get("vault.daily_note_format") == "YYYY-MM-DD"
            assert config.get("logging.level") == "INFO"

    def test_default_fallback(self) -> None:
        """Test that missing keys return default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)

            assert config.get("missing.key") is None
            assert config.get("missing.key", "default") == "default"
            assert config.get("vault.missing", 42) == 42


class TestConfigModification:
    """Test configuration modification."""

    def test_set_value(self) -> None:
        """Test setting configuration values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)

            config.set("vault.path", "/new/path")
            assert config.get("vault.path") == "/new/path"

    def test_set_nested_value(self) -> None:
        """Test setting nested configuration values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)

            config.set("custom.nested.key", "value")
            assert config.get("custom.nested.key") == "value"

    def test_save_and_reload(self) -> None:
        """Test that config persists across reloads."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create and modify config
            config1 = Config(config_dir=tmpdir)
            config1.set("vault.path", "/persisted/path")
            config1.save()

            # Load fresh config
            config2 = Config(config_dir=tmpdir)
            assert config2.get("vault.path") == "/persisted/path"


class TestPluginConfig:
    """Test per-plugin configuration."""

    def test_load_missing_plugin_config(self) -> None:
        """Test loading config for non-existent plugin."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)
            plugin_config = config.get_plugin_config("nonexistent")
            assert plugin_config == {}

    def test_save_and_load_plugin_config(self) -> None:
        """Test saving and loading plugin config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)

            plugin_data = {"api_key": "secret123", "enabled": True, "threshold": 0.5}
            config.save_plugin_config("my_plugin", plugin_data)

            loaded = config.get_plugin_config("my_plugin")
            assert loaded["api_key"] == "secret123"
            assert loaded["enabled"] is True
            assert loaded["threshold"] == 0.5

    def test_plugin_config_isolated(self) -> None:
        """Test that plugin configs don't interfere."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)

            config.save_plugin_config("plugin_a", {"key": "a"})
            config.save_plugin_config("plugin_b", {"key": "b"})

            assert config.get_plugin_config("plugin_a")["key"] == "a"
            assert config.get_plugin_config("plugin_b")["key"] == "b"


class TestPluginData:
    """Test per-plugin state persistence."""

    def test_load_missing_plugin_data(self) -> None:
        """Test loading data for plugin without saved state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)
            data = config.load_plugin_data("new_plugin")
            assert data == {}

    def test_save_and_load_plugin_data(self) -> None:
        """Test saving and loading plugin state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)

            state = {
                "last_run": "2024-01-15",
                "count": 42,
                "items": ["a", "b"],
                "settings": {"x": 1},
            }
            config.save_plugin_data("my_plugin", state)

            loaded = config.load_plugin_data("my_plugin")
            assert loaded["last_run"] == "2024-01-15"
            assert loaded["count"] == 42
            assert loaded["items"] == ["a", "b"]
            assert loaded["settings"]["x"] == 1

    def test_plugin_data_directory_created(self) -> None:
        """Test that plugin data directory is auto-created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)

            config.save_plugin_data("test_plugin", {"key": "value"})

            data_dir = Path(tmpdir) / "data" / "test_plugin"
            assert data_dir.exists()
            assert (data_dir / "user-data.json").exists()

    def test_plugin_data_persistence(self) -> None:
        """Test that plugin data persists across config instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Save data
            config1 = Config(config_dir=tmpdir)
            config1.save_plugin_data("persistent_plugin", {"counter": 100})

            # Load in new instance
            config2 = Config(config_dir=tmpdir)
            loaded = config2.load_plugin_data("persistent_plugin")
            assert loaded["counter"] == 100


class TestConfigPaths:
    """Test configuration path properties."""

    def test_config_dir_property(self) -> None:
        """Test config_dir property."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)
            assert config.config_dir == Path(tmpdir)

    def test_plugins_dir_property(self) -> None:
        """Test plugins_dir property."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)
            assert config.plugins_dir == Path(tmpdir) / "plugins"
            assert config.plugins_dir.exists()

    def test_data_dir_property(self) -> None:
        """Test data_dir property."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)
            assert config.data_dir == Path(tmpdir) / "data"
            assert config.data_dir.exists()

    def test_logs_dir_property(self) -> None:
        """Test logs_dir property."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)
            assert config.logs_dir == Path(tmpdir) / "logs"
            assert config.logs_dir.exists()


class TestGlobalConfig:
    """Test global config instance."""

    def test_get_config_singleton(self) -> None:
        """Test that get_config returns singleton."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reset_config()
            config1 = get_config(tmpdir)
            config2 = get_config()

            assert config1 is config2

    def test_reset_config(self) -> None:
        """Test that reset_config clears singleton."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reset_config()
            config1 = get_config(tmpdir)
            reset_config()
            config2 = get_config(tmpdir)

            assert config1 is not config2


class TestConfigToDict:
    """Test config serialization."""

    def test_to_dict(self) -> None:
        """Test that to_dict returns copy of config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)
            data = config.to_dict()

            assert isinstance(data, dict)
            assert "vault" in data
            assert "logging" in data
            assert "paths" in data

    def test_to_dict_is_copy(self) -> None:
        """Test that to_dict returns a copy, not reference."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(config_dir=tmpdir)
            data = config.to_dict()

            # Modify returned dict
            data["vault"]["path"] = "/modified"

            # Original config should be unchanged
            assert config.get("vault.path") == "~/Documents/Obsidian"
