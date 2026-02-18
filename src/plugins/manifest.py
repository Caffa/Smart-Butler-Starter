"""Plugin manifest schema and validation.

Defines the plugin.yaml structure and provides loading/validation utilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class PluginManifest:
    """Plugin manifest loaded from plugin.yaml.

    Attributes:
        name: Unique plugin identifier (alphanumeric, underscores, hyphens)
        version: Semantic version string
        description: Human-readable description
        enabled: Whether plugin should be loaded
        capabilities_provided: List of capabilities this plugin provides
        capabilities_required: List of capabilities this plugin needs
        events_listens: List of event signals this plugin subscribes to
        events_emits: List of event signals this plugin emits
        dependencies: List of other plugin names this plugin depends on
        priority: Loading priority (higher = loaded first)
    """

    name: str
    version: str = "0.0.0"
    description: str = ""
    enabled: bool = True
    capabilities_provided: list[str] = field(default_factory=list)
    capabilities_required: list[str] = field(default_factory=list)
    events_listens: list[str] = field(default_factory=list)
    events_emits: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    priority: int = 0

    @classmethod
    def from_yaml(cls, path: Path) -> PluginManifest:
        """Load manifest from a YAML file.

        Args:
            path: Path to plugin.yaml file

        Returns:
            PluginManifest instance

        Raises:
            ManifestValidationError: If file is invalid or missing required fields
        """
        if not path.exists():
            raise ManifestValidationError(f"Manifest file not found: {path}")

        try:
            with open(path) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ManifestValidationError(f"Invalid YAML in {path}: {e}") from e

        if not isinstance(data, dict):
            raise ManifestValidationError(f"Manifest must be a YAML mapping: {path}")

        return cls.from_dict(data, path)

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: Optional[Path] = None) -> PluginManifest:
        """Create manifest from dictionary.

        Args:
            data: Dictionary with manifest data
            source: Optional source file path for error messages

        Returns:
            PluginManifest instance

        Raises:
            ManifestValidationError: If required fields are missing or invalid
        """
        errors = []

        # Required fields
        name = data.get("name")
        if not name:
            errors.append("Missing required field: 'name'")
        elif not isinstance(name, str):
            errors.append("Field 'name' must be a string")
        elif not _is_valid_name(name):
            errors.append(
                f"Invalid plugin name '{name}': must be alphanumeric with "
                "underscores and hyphens only"
            )

        if errors:
            source_str = f" in {source}" if source else ""
            raise ManifestValidationError(
                f"Invalid manifest{source_str}:\n" + "\n".join(f"  - {e}" for e in errors)
            )

        # Optional fields with defaults
        version = data.get("version", "0.0.0")
        if not isinstance(version, str):
            errors.append("Field 'version' must be a string")

        description = data.get("description", "")
        if not isinstance(description, str):
            errors.append("Field 'description' must be a string")

        enabled = data.get("enabled", True)
        if not isinstance(enabled, bool):
            errors.append("Field 'enabled' must be a boolean")

        # List fields
        capabilities_provided = _ensure_string_list(
            data.get("capabilities_provided", []), "capabilities_provided", errors
        )
        capabilities_required = _ensure_string_list(
            data.get("capabilities_required", []), "capabilities_required", errors
        )
        events_listens = _ensure_string_list(
            data.get("events_listens", []), "events_listens", errors
        )
        events_emits = _ensure_string_list(data.get("events_emits", []), "events_emits", errors)
        dependencies = _ensure_string_list(data.get("dependencies", []), "dependencies", errors)

        priority = data.get("priority", 0)
        if not isinstance(priority, int):
            errors.append("Field 'priority' must be an integer")

        if errors:
            source_str = f" in {source}" if source else ""
            raise ManifestValidationError(
                f"Invalid manifest{source_str}:\n" + "\n".join(f"  - {e}" for e in errors)
            )

        return cls(
            name=name,
            version=version,
            description=description,
            enabled=enabled,
            capabilities_provided=capabilities_provided,
            capabilities_required=capabilities_required,
            events_listens=events_listens,
            events_emits=events_emits,
            dependencies=dependencies,
            priority=priority,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert manifest to dictionary.

        Returns:
            Dictionary representation of manifest
        """
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "enabled": self.enabled,
            "capabilities_provided": self.capabilities_provided,
            "capabilities_required": self.capabilities_required,
            "events_listens": self.events_listens,
            "events_emits": self.events_emits,
            "dependencies": self.dependencies,
            "priority": self.priority,
        }

    def to_yaml(self, path: Path) -> None:
        """Save manifest to a YAML file.

        Args:
            path: Path to write the manifest
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, sort_keys=False)


def _is_valid_name(name: str) -> bool:
    """Check if a plugin name is valid.

    Valid names are alphanumeric with underscores and hyphens.
    Must start with a letter.
    """
    if not name:
        return False
    if not name[0].isalpha():
        return False
    return all(c.isalnum() or c in "_-" for c in name)


def _ensure_string_list(value: Any, field_name: str, errors: list[str]) -> list[str]:
    """Ensure a value is a list of strings.

    Args:
        value: The value to check
        field_name: Field name for error messages
        errors: List to append errors to

    Returns:
        List of strings, or empty list if invalid
    """
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"Field '{field_name}' must be a list")
        return []
    result = []
    for item in value:
        if isinstance(item, str):
            result.append(item)
        else:
            errors.append(f"Field '{field_name}' must contain only strings")
            return []
    return result


class ManifestValidationError(Exception):
    """Raised when a plugin manifest fails validation."""

    pass


__all__ = [
    "PluginManifest",
    "ManifestValidationError",
]
