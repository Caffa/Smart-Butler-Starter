"""Tests for the base plugin class and manifest.

Tests cover:
- Manifest loading and validation
- BasePlugin lifecycle methods
- Capability registration
- Event connection
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from src.plugins.base import (
    BasePlugin,
    PluginEnableError,
    PluginError,
    PluginLoadError,
)
from src.plugins.manifest import (
    ManifestValidationError,
    PluginManifest,
)


class TestPluginManifest:
    """Tests for PluginManifest class."""

    def test_from_dict_minimal(self) -> None:
        """Create manifest from minimal dict."""
        data = {"name": "test_plugin"}
        manifest = PluginManifest.from_dict(data)

        assert manifest.name == "test_plugin"
        assert manifest.version == "0.0.0"
        assert manifest.description == ""
        assert manifest.enabled is True
        assert manifest.capabilities_provided == []
        assert manifest.dependencies == []

    def test_from_dict_full(self) -> None:
        """Create manifest from full dict."""
        data = {
            "name": "voice_input",
            "version": "1.2.0",
            "description": "Voice transcription plugin",
            "enabled": True,
            "capabilities_provided": ["transcription"],
            "capabilities_required": ["embeddings"],
            "events_listens": ["input.received"],
            "events_emits": ["note.routed"],
            "dependencies": ["memory_plugin"],
            "priority": 10,
        }
        manifest = PluginManifest.from_dict(data)

        assert manifest.name == "voice_input"
        assert manifest.version == "1.2.0"
        assert manifest.description == "Voice transcription plugin"
        assert manifest.enabled is True
        assert manifest.capabilities_provided == ["transcription"]
        assert manifest.capabilities_required == ["embeddings"]
        assert manifest.events_listens == ["input.received"]
        assert manifest.events_emits == ["note.routed"]
        assert manifest.dependencies == ["memory_plugin"]
        assert manifest.priority == 10

    def test_from_dict_missing_name(self) -> None:
        """Missing name raises ValidationError."""
        data = {"version": "1.0.0"}

        with pytest.raises(ManifestValidationError, match="Missing required field"):
            PluginManifest.from_dict(data)

    def test_from_dict_invalid_name(self) -> None:
        """Invalid name raises ValidationError."""
        data = {"name": "123_invalid"}

        with pytest.raises(ManifestValidationError, match="Invalid plugin name"):
            PluginManifest.from_dict(data)

    def test_from_dict_name_starts_with_number(self) -> None:
        """Name starting with number is invalid."""
        data = {"name": "123plugin"}

        with pytest.raises(ManifestValidationError, match="Invalid plugin name"):
            PluginManifest.from_dict(data)

    def test_from_dict_valid_names(self) -> None:
        """Various valid name formats."""
        valid_names = [
            "voice_input",
            "daily-writer",
            "MyPlugin",
            "plugin123",
            "a_b-c",
        ]

        for name in valid_names:
            manifest = PluginManifest.from_dict({"name": name})
            assert manifest.name == name

    def test_from_dict_invalid_enabled(self) -> None:
        """Non-boolean enabled raises ValidationError."""
        data = {"name": "test", "enabled": "yes"}

        with pytest.raises(ManifestValidationError, match="must be a boolean"):
            PluginManifest.from_dict(data)

    def test_from_dict_invalid_capabilities_list(self) -> None:
        """Non-list capabilities raises ValidationError."""
        data = {"name": "test", "capabilities_provided": "transcription"}

        with pytest.raises(ManifestValidationError, match="must be a list"):
            PluginManifest.from_dict(data)

    def test_from_dict_capabilities_with_non_strings(self) -> None:
        """Capabilities list with non-strings raises ValidationError."""
        data = {"name": "test", "capabilities_provided": ["valid", 123]}

        with pytest.raises(ManifestValidationError, match="must contain only strings"):
            PluginManifest.from_dict(data)

    def test_from_yaml(self) -> None:
        """Load manifest from YAML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "plugin.yaml"
            data = {
                "name": "test_plugin",
                "version": "1.0.0",
                "description": "A test plugin",
            }
            with open(path, "w") as f:
                yaml.dump(data, f)

            manifest = PluginManifest.from_yaml(path)
            assert manifest.name == "test_plugin"
            assert manifest.version == "1.0.0"

    def test_from_yaml_missing_file(self) -> None:
        """Missing YAML file raises ValidationError."""
        with pytest.raises(ManifestValidationError, match="Manifest file not found"):
            PluginManifest.from_yaml(Path("/nonexistent/plugin.yaml"))

    def test_from_yaml_invalid_yaml(self) -> None:
        """Invalid YAML raises ValidationError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "plugin.yaml"
            with open(path, "w") as f:
                f.write("name: [invalid\n")  # Unclosed bracket

            with pytest.raises(ManifestValidationError, match="Invalid YAML"):
                PluginManifest.from_yaml(path)

    def test_to_dict(self) -> None:
        """Convert manifest to dictionary."""
        manifest = PluginManifest(
            name="test",
            version="1.0.0",
            description="Test",
            capabilities_provided=["cap1"],
        )
        data = manifest.to_dict()

        assert data["name"] == "test"
        assert data["version"] == "1.0.0"
        assert data["description"] == "Test"
        assert data["capabilities_provided"] == ["cap1"]

    def test_to_yaml(self) -> None:
        """Save manifest to YAML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "plugin.yaml"
            manifest = PluginManifest(
                name="test",
                version="1.0.0",
                description="Test plugin",
            )
            manifest.to_yaml(path)

            # Read back
            with open(path) as f:
                data = yaml.safe_load(f)

            assert data["name"] == "test"
            assert data["version"] == "1.0.0"


class ConcretePlugin(BasePlugin):
    """Concrete implementation for testing."""

    def __init__(self, plugin_dir: Path, manifest: PluginManifest | None = None) -> None:
        super().__init__(plugin_dir, manifest)
        self.enable_called = False
        self.disable_called = False
        self.transcribe_calls: list[bytes] = []

    def on_enable(self) -> None:
        self.enable_called = True
        self.register_capability("transcription", self.transcribe)

    def on_disable(self) -> None:
        self.disable_called = True

    def transcribe(self, audio: bytes) -> str:
        self.transcribe_calls.append(audio)
        return "transcribed text"


class TestBasePlugin:
    """Tests for BasePlugin class."""

    def setup_method(self) -> None:
        """Create a fresh plugin for each test."""
        from src.core.capabilities import clear_registry

        clear_registry()

    def test_plugin_initialization(self) -> None:
        """Plugin initializes with manifest."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            manifest = PluginManifest(name="test_plugin", version="1.0.0")
            plugin = ConcretePlugin(plugin_dir, manifest)

            assert plugin.name == "test_plugin"
            assert plugin.version == "1.0.0"
            assert not plugin.is_enabled

    def test_plugin_enable(self) -> None:
        """Enable calls on_enable and registers capabilities."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            manifest = PluginManifest(
                name="test_plugin",
                capabilities_provided=["transcription"],
            )
            plugin = ConcretePlugin(plugin_dir, manifest)

            plugin.enable()

            assert plugin.enable_called
            assert plugin.is_enabled

    def test_plugin_disable(self) -> None:
        """Disable calls on_disable and unregisters capabilities."""
        from src.core.capabilities import has_capability

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            manifest = PluginManifest(
                name="test_plugin",
                capabilities_provided=["transcription"],
            )
            plugin = ConcretePlugin(plugin_dir, manifest)

            plugin.enable()
            assert has_capability("transcription")

            plugin.disable()

            assert plugin.disable_called
            assert not plugin.is_enabled
            assert not has_capability("transcription")

    def test_capability_registration(self) -> None:
        """Plugin can register capabilities."""
        from src.core.capabilities import get_capability, has_capability

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            manifest = PluginManifest(name="test_plugin")
            plugin = ConcretePlugin(plugin_dir, manifest)

            plugin.enable()

            assert has_capability("transcription")
            cap = get_capability("transcription")
            assert cap is not None
            assert cap(b"audio") == "transcribed text"

    def test_double_enable_is_safe(self) -> None:
        """Enabling twice is safe (no-op)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            manifest = PluginManifest(name="test_plugin")
            plugin = ConcretePlugin(plugin_dir, manifest)

            plugin.enable()
            first_call = plugin.enable_called

            plugin.enable()  # Second enable

            # on_enable should only be called once
            assert plugin.enable_called == first_call

    def test_double_disable_is_safe(self) -> None:
        """Disabling twice is safe (no-op)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            manifest = PluginManifest(name="test_plugin")
            plugin = ConcretePlugin(plugin_dir, manifest)

            plugin.enable()
            plugin.disable()
            first_call = plugin.disable_called

            plugin.disable()  # Second disable

            # on_disable should only be called once
            assert plugin.disable_called == first_call

    def test_plugin_repr(self) -> None:
        """Plugin has useful string representation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            manifest = PluginManifest(name="test_plugin", version="1.2.3")
            plugin = ConcretePlugin(plugin_dir, manifest)

            repr_str = repr(plugin)
            assert "ConcretePlugin" in repr_str
            assert "test_plugin" in repr_str
            assert "1.2.3" in repr_str


class MinimalPlugin(BasePlugin):
    """Minimal plugin with no capabilities."""

    def on_enable(self) -> None:
        pass

    def on_disable(self) -> None:
        pass


class TestBasePluginEvents:
    """Tests for plugin event handling."""

    def setup_method(self) -> None:
        """Clear state before each test."""
        from src.core.capabilities import clear_registry
        from src.core.event_bus import disconnect_all, input_received

        clear_registry()
        disconnect_all(input_received)

    def test_emit_event(self) -> None:
        """Plugin can emit events."""
        from src.core.event_bus import input_received

        received: list[dict] = []

        @input_received.connect
        def handler(sender, **kwargs):
            received.append({"sender": sender, **kwargs})

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            manifest = PluginManifest(name="test_plugin")
            plugin = MinimalPlugin(plugin_dir, manifest)

            plugin.emit_event(input_received, text="hello", source="test")

            assert len(received) == 1
            assert received[0]["sender"] == "test_plugin"
            assert received[0]["text"] == "hello"

    def test_manifest_loads_from_file(self) -> None:
        """Manifest can be loaded from plugin.yaml in plugin_dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            manifest_data = {
                "name": "auto_loaded",
                "version": "2.0.0",
                "description": "Auto-loaded manifest",
            }
            manifest_path = plugin_dir / "plugin.yaml"
            with open(manifest_path, "w") as f:
                yaml.dump(manifest_data, f)

            plugin = MinimalPlugin(plugin_dir)
            # Access manifest to trigger load
            assert plugin.manifest.name == "auto_loaded"
            assert plugin.manifest.version == "2.0.0"


class TestPluginExceptions:
    """Tests for plugin exception classes."""

    def test_plugin_error_is_base(self) -> None:
        """PluginError is the base exception."""
        assert issubclass(PluginLoadError, PluginError)
        assert issubclass(PluginEnableError, PluginError)

    def test_plugin_load_error_message(self) -> None:
        """PluginLoadError carries message."""
        error = PluginLoadError("Failed to load plugin")
        assert str(error) == "Failed to load plugin"

    def test_plugin_enable_error_message(self) -> None:
        """PluginEnableError carries message."""
        error = PluginEnableError("Failed to enable plugin")
        assert str(error) == "Failed to enable plugin"
