"""Tests for the plugin manager.

Tests cover:
- Plugin discovery from filesystem
- Dependency ordering
- Plugin loading and lifecycle
- Error handling
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from src.core.plugin_manager import PluginInfo, PluginManager, discover_plugins
from src.plugins.base import BasePlugin
from src.plugins.manifest import PluginManifest


class TestPluginInfo:
    """Tests for PluginInfo dataclass."""

    def test_plugin_info_properties(self) -> None:
        """PluginInfo exposes manifest properties."""
        manifest = PluginManifest(name="test_plugin", version="1.0.0")
        info = PluginInfo(path=Path("/plugins/test"), manifest=manifest)

        assert info.name == "test_plugin"
        assert not info.is_loaded
        assert info.is_enabled  # enabled by default

    def test_plugin_info_disabled(self) -> None:
        """PluginInfo reflects disabled state."""
        manifest = PluginManifest(name="test_plugin", enabled=False)
        info = PluginInfo(path=Path("/plugins/test"), manifest=manifest)

        assert not info.is_enabled


class TestPluginManager:
    """Tests for PluginManager class."""

    def setup_method(self) -> None:
        """Clear state before each test."""
        from src.core.capabilities import clear_registry
        from src.core.event_bus import disconnect_all, input_received

        clear_registry()
        disconnect_all(input_received)

    def test_discover_empty_directory(self) -> None:
        """Discovery returns empty list for empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PluginManager(Path(tmpdir))
            discovered = manager.discover_plugins()

            assert discovered == []

    def test_discover_nonexistent_directory(self) -> None:
        """Discovery returns empty list for nonexistent directory."""
        manager = PluginManager(Path("/nonexistent/plugins"))
        discovered = manager.discover_plugins()

        assert discovered == []

    def test_discover_single_plugin(self) -> None:
        """Discover a single plugin directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            plugin_path = plugin_dir / "test_plugin"
            plugin_path.mkdir()

            # Create manifest
            manifest_data = {"name": "test_plugin", "version": "1.0.0"}
            with open(plugin_path / "plugin.yaml", "w") as f:
                yaml.dump(manifest_data, f)

            manager = PluginManager(plugin_dir)
            discovered = manager.discover_plugins()

            assert len(discovered) == 1
            assert discovered[0].name == "test_plugin"

    def test_discover_multiple_plugins(self) -> None:
        """Discover multiple plugin directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)

            for name in ["plugin_a", "plugin_b", "plugin_c"]:
                plugin_path = plugin_dir / name
                plugin_path.mkdir()
                with open(plugin_path / "plugin.yaml", "w") as f:
                    yaml.dump({"name": name}, f)

            manager = PluginManager(plugin_dir)
            discovered = manager.discover_plugins()

            names = [p.name for p in discovered]
            assert set(names) == {"plugin_a", "plugin_b", "plugin_c"}

    def test_discover_skips_disabled_plugins(self) -> None:
        """Disabled plugins are discovered but marked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)

            enabled_path = plugin_dir / "enabled_plugin"
            enabled_path.mkdir()
            with open(enabled_path / "plugin.yaml", "w") as f:
                yaml.dump({"name": "enabled_plugin", "enabled": True}, f)

            disabled_path = plugin_dir / "disabled_plugin"
            disabled_path.mkdir()
            with open(disabled_path / "plugin.yaml", "w") as f:
                yaml.dump({"name": "disabled_plugin", "enabled": False}, f)

            manager = PluginManager(plugin_dir)
            discovered = manager.discover_plugins()

            assert len(discovered) == 2
            enabled = [p for p in discovered if p.manifest.enabled]
            disabled = [p for p in discovered if not p.manifest.enabled]
            assert len(enabled) == 1
            assert len(disabled) == 1

    def test_discover_ignores_non_plugin_directories(self) -> None:
        """Directories without plugin.yaml are ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)

            # Plugin directory
            plugin_path = plugin_dir / "real_plugin"
            plugin_path.mkdir()
            with open(plugin_path / "plugin.yaml", "w") as f:
                yaml.dump({"name": "real_plugin"}, f)

            # Non-plugin directory
            non_plugin = plugin_dir / "just_a_folder"
            non_plugin.mkdir()
            with open(non_plugin / "readme.txt", "w") as f:
                f.write("Not a plugin")

            # File at root level
            with open(plugin_dir / "file.txt", "w") as f:
                f.write("Also not a plugin")

            manager = PluginManager(plugin_dir)
            discovered = manager.discover_plugins()

            assert len(discovered) == 1
            assert discovered[0].name == "real_plugin"

    def test_discover_invalid_manifest_logged(self) -> None:
        """Invalid manifest is logged but doesn't crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)

            # Plugin with invalid manifest
            plugin_path = plugin_dir / "bad_plugin"
            plugin_path.mkdir()
            with open(plugin_path / "plugin.yaml", "w") as f:
                yaml.dump({"invalid": "no name field"}, f)

            manager = PluginManager(plugin_dir)
            discovered = manager.discover_plugins()

            # Invalid plugin is not included
            assert discovered == []


class TestPluginLoadOrder:
    """Tests for dependency ordering."""

    def setup_method(self) -> None:
        """Clear state before each test."""
        from src.core.capabilities import clear_registry

        clear_registry()

    def test_no_dependencies(self) -> None:
        """Plugins without dependencies load in any order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)

            for name in ["a", "b", "c"]:
                plugin_path = plugin_dir / name
                plugin_path.mkdir()
                with open(plugin_path / "plugin.yaml", "w") as f:
                    yaml.dump({"name": name}, f)

            manager = PluginManager(plugin_dir)
            manager.discover_plugins()
            order = manager.resolve_load_order()

            assert set(order) == {"a", "b", "c"}

    def test_dependency_order(self) -> None:
        """Plugins load in dependency order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)

            # c depends on b, b depends on a
            for name, deps in [
                ("a", []),
                ("b", ["a"]),
                ("c", ["b"]),
            ]:
                plugin_path = plugin_dir / name
                plugin_path.mkdir()
                with open(plugin_path / "plugin.yaml", "w") as f:
                    yaml.dump({"name": name, "dependencies": deps}, f)

            manager = PluginManager(plugin_dir)
            manager.discover_plugins()
            order = manager.resolve_load_order()

            # a must come before b, b before c
            assert order.index("a") < order.index("b")
            assert order.index("b") < order.index("c")

    def test_priority_order(self) -> None:
        """Higher priority plugins load first (for dependencies)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)

            for name, priority in [("low", 0), ("medium", 5), ("high", 10)]:
                plugin_path = plugin_dir / name
                plugin_path.mkdir()
                with open(plugin_path / "plugin.yaml", "w") as f:
                    yaml.dump({"name": name, "priority": priority}, f)

            manager = PluginManager(plugin_dir)
            manager.discover_plugins()
            order = manager.resolve_load_order()

            # Higher priority first
            assert order.index("high") < order.index("medium")
            assert order.index("medium") < order.index("low")

    def test_circular_dependency_error(self) -> None:
        """Circular dependency raises PluginLoadError."""
        from src.plugins.base import PluginLoadError

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)

            # a -> b -> a
            for name, deps in [
                ("a", ["b"]),
                ("b", ["a"]),
            ]:
                plugin_path = plugin_dir / name
                plugin_path.mkdir()
                with open(plugin_path / "plugin.yaml", "w") as f:
                    yaml.dump({"name": name, "dependencies": deps}, f)

            manager = PluginManager(plugin_dir)
            manager.discover_plugins()

            with pytest.raises(PluginLoadError, match="Circular dependency"):
                manager.resolve_load_order()


# Test plugin implementations
class MockPlugin(BasePlugin):
    """Mock plugin for testing."""

    def __init__(self, plugin_dir: Path, manifest: PluginManifest | None = None) -> None:
        super().__init__(plugin_dir, manifest)
        self.enabled_count = 0
        self.disabled_count = 0

    def on_enable(self) -> None:
        self.enabled_count += 1

    def on_disable(self) -> None:
        self.disabled_count += 1


class TranscriberPlugin(BasePlugin):
    """Plugin that provides transcription capability."""

    def on_enable(self) -> None:
        self.register_capability("transcription", self.transcribe)

    def on_disable(self) -> None:
        pass

    def transcribe(self, audio: bytes) -> str:
        return "transcribed"


class TestPluginLoading:
    """Tests for plugin loading."""

    def setup_method(self) -> None:
        """Clear state before each test."""
        from src.core.capabilities import clear_registry
        from src.core.event_bus import disconnect_all, input_received

        clear_registry()
        disconnect_all(input_received)

    def _create_test_plugin(
        self,
        plugin_dir: Path,
        name: str,
        class_name: str = "TestPlugin",
        dependencies: list[str] | None = None,
        capabilities_provided: list[str] | None = None,
        capabilities_required: list[str] | None = None,
    ) -> Path:
        """Create a test plugin directory with module."""
        plugin_path = plugin_dir / name
        plugin_path.mkdir()

        manifest = {"name": name, "version": "1.0.0"}
        if dependencies:
            manifest["dependencies"] = dependencies
        if capabilities_provided:
            manifest["capabilities_provided"] = capabilities_provided
        if capabilities_required:
            manifest["capabilities_required"] = capabilities_required

        with open(plugin_path / "plugin.yaml", "w") as f:
            yaml.dump(manifest, f)

        # Create __init__.py with the plugin class
        init_content = f'''
from pathlib import Path
from src.plugins.base import BasePlugin
from src.plugins.manifest import PluginManifest

class {class_name}(BasePlugin):
    """Test plugin for testing."""

    def on_enable(self) -> None:
        pass

    def on_disable(self) -> None:
        pass
'''
        with open(plugin_path / "__init__.py", "w") as f:
            f.write(init_content)

        return plugin_path

    def test_load_plugins_empty(self) -> None:
        """Loading from empty directory returns empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PluginManager(Path(tmpdir))
            loaded = manager.load_plugins()

            assert loaded == []

    def test_load_single_plugin(self) -> None:
        """Load a single plugin."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            self._create_test_plugin(plugin_dir, "test_plugin")

            manager = PluginManager(plugin_dir)
            loaded = manager.load_plugins()

            assert len(loaded) == 1
            assert loaded[0].name == "test_plugin"
            assert loaded[0].is_loaded

    def test_get_plugin(self) -> None:
        """Get a loaded plugin by name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            self._create_test_plugin(plugin_dir, "test_plugin")

            manager = PluginManager(plugin_dir)
            manager.load_plugins()

            plugin = manager.get_plugin("test_plugin")
            assert plugin is not None
            assert plugin.name == "test_plugin"

    def test_get_nonexistent_plugin(self) -> None:
        """Get returns None for nonexistent plugin."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PluginManager(Path(tmpdir))
            plugin = manager.get_plugin("nonexistent")
            assert plugin is None

    def test_list_plugins(self) -> None:
        """List all discovered plugins."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            self._create_test_plugin(plugin_dir, "plugin_a")
            self._create_test_plugin(plugin_dir, "plugin_b")

            manager = PluginManager(plugin_dir)
            manager.load_plugins()
            plugins = manager.list_plugins()

            names = [p.name for p in plugins]
            assert set(names) == {"plugin_a", "plugin_b"}

    def test_load_failure_recorded(self) -> None:
        """Failed loads are recorded with error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            plugin_path = plugin_dir / "bad_plugin"
            plugin_path.mkdir()

            # Valid manifest but no __init__.py
            with open(plugin_path / "plugin.yaml", "w") as f:
                yaml.dump({"name": "bad_plugin"}, f)

            manager = PluginManager(plugin_dir)
            loaded = manager.load_plugins()

            # Plugin not loaded
            assert len(loaded) == 0

            # Error recorded
            info = manager._plugins.get("bad_plugin")
            assert info is not None
            assert info.load_error is not None

    def test_load_missing_capability_fails(self) -> None:
        """Plugin requiring missing capability fails to load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            self._create_test_plugin(
                plugin_dir,
                "dependent_plugin",
                capabilities_required=["missing_capability"],
            )

            manager = PluginManager(plugin_dir)
            loaded = manager.load_plugins()

            assert len(loaded) == 0
            info = manager._plugins.get("dependent_plugin")
            assert info is not None
            assert "missing capabilities" in str(info.load_error)

    def test_enable_disable_plugin(self) -> None:
        """Enable and disable a loaded plugin."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            self._create_test_plugin(plugin_dir, "test_plugin")

            manager = PluginManager(plugin_dir)
            manager.load_plugins()

            # Plugin is enabled after load
            plugin = manager.get_plugin("test_plugin")
            assert plugin is not None
            assert plugin.is_enabled

            # Disable
            manager.disable_plugin("test_plugin")
            assert not plugin.is_enabled

            # Re-enable
            manager.enable_plugin("test_plugin")
            assert plugin.is_enabled

    def test_reload_plugin(self) -> None:
        """Reload a plugin."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            self._create_test_plugin(plugin_dir, "test_plugin")

            manager = PluginManager(plugin_dir)
            manager.load_plugins()

            first_instance = manager.get_plugin("test_plugin")

            # Reload
            manager.reload_plugin("test_plugin")

            # New instance
            second_instance = manager.get_plugin("test_plugin")
            assert second_instance is not None
            assert second_instance is not first_instance


class TestDiscoverPlugins:
    """Tests for the convenience function."""

    def test_discover_plugins_function(self) -> None:
        """discover_plugins returns list of PluginInfo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            plugin_path = plugin_dir / "test_plugin"
            plugin_path.mkdir()

            with open(plugin_path / "plugin.yaml", "w") as f:
                yaml.dump({"name": "test_plugin"}, f)

            discovered = discover_plugins(plugin_dir)

            assert len(discovered) == 1
            assert discovered[0].name == "test_plugin"
