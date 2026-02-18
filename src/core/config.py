"""Configuration management system.

Loads configuration from YAML files and manages per-plugin state in JSON.
Auto-creates directory structure on first run.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False


class ConfigError(Exception):
    """Base exception for configuration errors."""

    pass


class Config:
    """Configuration manager for Smart Butler.

    Loads main config from ~/.butler/config.yaml and manages per-plugin
    configurations and state persistence.

    Example:
        config = Config()
        vault_path = config.get("vault.path", "~/Documents/Obsidian")
        config.save_plugin_data("my_plugin", {"key": "value"})
    """

    DEFAULT_CONFIG = {
        "vault": {"path": "~/Documents/Obsidian", "daily_note_format": "YYYY-MM-DD"},
        "logging": {"level": "INFO", "max_size_mb": 10, "backup_count": 3},
        "paths": {
            "plugins_dir": "~/.butler/plugins",
            "data_dir": "~/.butler/data",
            "logs_dir": "~/.butler/logs",
        },
        "features": {"auto_start": False, "menu_bar_icon": True},
    }

    def __init__(self, config_dir: str | None = None) -> None:
        """Initialize configuration.

        Args:
            config_dir: Override default config directory (default: ~/.butler)
        """
        self._config_dir = Path(config_dir or "~/.butler").expanduser()
        self._config_file = self._config_dir / "config.yaml"
        self._data: dict[str, Any] = {}

        # Ensure directory structure exists
        self._ensure_directories()

        # Load configuration
        self._load()

    @property
    def config_dir(self) -> Path:
        """Return the configuration directory path."""
        return self._config_dir

    @property
    def plugins_dir(self) -> Path:
        """Return the plugins directory path."""
        path = self._config_dir / "plugins"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def data_dir(self) -> Path:
        """Return the data directory path."""
        path = self._config_dir / "data"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def logs_dir(self) -> Path:
        """Return the logs directory path."""
        path = self._config_dir / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _ensure_directories(self) -> None:
        """Create necessary directory structure."""
        # Create main config directory
        self._config_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        for subdir in ["plugins", "data", "logs"]:
            (self._config_dir / subdir).mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        """Load configuration from file or use defaults."""
        import copy

        self._data = copy.deepcopy(self.DEFAULT_CONFIG)

        if self._config_file.exists():
            if HAS_YAML:
                try:
                    with open(self._config_file, "r") as f:
                        user_config = yaml.safe_load(f) or {}
                    self._merge_config(self._data, user_config)
                except Exception as e:
                    raise ConfigError(f"Failed to load config from {self._config_file}: {e}")
            else:
                # Fallback: try to parse as JSON if YAML not available
                try:
                    with open(self._config_file, "r") as f:
                        user_config = json.load(f)
                    self._merge_config(self._data, user_config)
                except json.JSONDecodeError:
                    raise ConfigError(
                        f"YAML not available and config is not valid JSON: {self._config_file}"
                    )
        else:
            # Create default config file
            self._save_default_config()

    def _save_default_config(self) -> None:
        """Save default configuration to file."""
        if HAS_YAML:
            try:
                with open(self._config_file, "w") as f:
                    yaml.dump(self._data, f, default_flow_style=False, sort_keys=False)
            except Exception as e:
                raise ConfigError(f"Failed to save default config: {e}")
        else:
            # Save as JSON if YAML not available
            try:
                with open(self._config_file, "w") as f:
                    json.dump(self._data, f, indent=2)
            except Exception as e:
                raise ConfigError(f"Failed to save default config: {e}")

    def _merge_config(self, base: dict[str, Any], override: dict[str, Any]) -> None:
        """Recursively merge override into base configuration."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_config(base[key], value)
            else:
                base[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value using dot notation.

        Args:
            key: Dot-separated key path (e.g., "vault.path")
            default: Default value if key not found

        Returns:
            Configuration value or default

        Example:
            config.get("vault.path")  # Returns vault path
            config.get("missing.key", "default")  # Returns "default"
        """
        keys = key.split(".")
        value = self._data

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value using dot notation.

        Args:
            key: Dot-separated key path
            value: Value to set

        Example:
            config.set("vault.path", "/new/path")
        """
        keys = key.split(".")
        data = self._data

        for k in keys[:-1]:
            if k not in data:
                data[k] = {}
            data = data[k]

        data[keys[-1]] = value

    def save(self) -> None:
        """Save current configuration to file."""
        self._save_default_config()

    def get_plugin_config(self, plugin_name: str) -> dict[str, Any]:
        """Load per-plugin configuration from YAML file.

        Args:
            plugin_name: Name of the plugin

        Returns:
            Plugin configuration dictionary
        """
        plugin_file = self.plugins_dir / f"{plugin_name}.yaml"

        if plugin_file.exists():
            if HAS_YAML:
                try:
                    with open(plugin_file, "r") as f:
                        return yaml.safe_load(f) or {}
                except Exception:
                    return {}
            else:
                try:
                    with open(plugin_file, "r") as f:
                        return json.load(f)
                except (json.JSONDecodeError, FileNotFoundError):
                    return {}

        return {}

    def save_plugin_config(self, plugin_name: str, config: dict[str, Any]) -> None:
        """Save per-plugin configuration to YAML file.

        Args:
            plugin_name: Name of the plugin
            config: Configuration dictionary to save
        """
        plugin_file = self.plugins_dir / f"{plugin_name}.yaml"

        if HAS_YAML:
            with open(plugin_file, "w") as f:
                yaml.dump(config, f, default_flow_style=False)
        else:
            with open(plugin_file, "w") as f:
                json.dump(config, f, indent=2)

    def load_plugin_data(self, plugin_name: str) -> dict[str, Any]:
        """Load per-plugin persistent state from JSON file.

        Args:
            plugin_name: Name of the plugin

        Returns:
            Plugin state dictionary
        """
        data_file = self.data_dir / plugin_name / "user-data.json"

        if data_file.exists():
            try:
                with open(data_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                return {}

        return {}

    def save_plugin_data(self, plugin_name: str, data: dict[str, Any]) -> None:
        """Save per-plugin persistent state to JSON file.

        Args:
            plugin_name: Name of the plugin
            data: State dictionary to save
        """
        plugin_data_dir = self.data_dir / plugin_name
        plugin_data_dir.mkdir(parents=True, exist_ok=True)

        data_file = plugin_data_dir / "user-data.json"

        with open(data_file, "w") as f:
            json.dump(data, f, indent=2)

    def to_dict(self) -> dict[str, Any]:
        """Return configuration as a deep copy dictionary."""
        import copy

        return copy.deepcopy(self._data)


# Global config instance
_config_instance: Config | None = None


def get_config(config_dir: str | None = None) -> Config:
    """Get or create the global configuration instance.

    Args:
        config_dir: Optional override for config directory

    Returns:
        Config instance
    """
    global _config_instance

    if _config_instance is None or config_dir is not None:
        _config_instance = Config(config_dir)

    return _config_instance


def reset_config() -> None:
    """Reset the global configuration instance (useful for testing)."""
    global _config_instance
    _config_instance = None


__all__ = ["Config", "ConfigError", "get_config", "reset_config"]
