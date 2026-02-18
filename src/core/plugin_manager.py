"""Plugin manager with auto-discovery and lifecycle management.

Discovers plugins from the filesystem, loads them in dependency order,
and manages their lifecycle.
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Type

from src.core.capabilities import has_capability
from src.plugins.base import BasePlugin, PluginEnableError, PluginLoadError
from src.plugins.manifest import ManifestValidationError, PluginManifest

logger = logging.getLogger(__name__)


@dataclass
class PluginInfo:
    """Information about a discovered plugin.

    Attributes:
        path: Path to the plugin directory
        manifest: Plugin manifest
        plugin_class: Plugin class (None until loaded)
        instance: Plugin instance (None until instantiated)
        load_error: Error if loading failed
    """

    path: Path
    manifest: PluginManifest
    plugin_class: Optional[Type[BasePlugin]] = None
    instance: Optional[BasePlugin] = None
    load_error: Optional[Exception] = None

    @property
    def name(self) -> str:
        """Get plugin name."""
        return self.manifest.name

    @property
    def is_loaded(self) -> bool:
        """Check if plugin is loaded."""
        return self.instance is not None and self.load_error is None

    @property
    def is_enabled(self) -> bool:
        """Check if plugin should be loaded."""
        return self.manifest.enabled


class PluginManager:
    """Manages plugin discovery, loading, and lifecycle.

    Discovers plugins from a directory, loads them in dependency order,
    and provides access to loaded plugin instances.

    Example:
        manager = PluginManager(Path("plugins"))
        manager.load_plugins()

        # Get a loaded plugin
        voice_plugin = manager.get_plugin("voice_input")

        # List all plugins
        for info in manager.list_plugins():
            print(f"{info.name}: {'loaded' if info.is_loaded else 'not loaded'}")
    """

    def __init__(self, plugin_dir: Path) -> None:
        """Initialize the plugin manager.

        Args:
            plugin_dir: Directory containing plugin subdirectories
        """
        self.plugin_dir = plugin_dir
        self._plugins: dict[str, PluginInfo] = {}
        self._load_order: list[str] = []

    def discover_plugins(self) -> list[PluginInfo]:
        """Discover all plugins in the plugin directory.

        Scans for directories containing plugin.yaml files.

        Returns:
            List of PluginInfo for discovered plugins
        """
        discovered: list[PluginInfo] = []

        if not self.plugin_dir.exists():
            logger.warning(f"Plugin directory does not exist: {self.plugin_dir}")
            return discovered

        for plugin_path in self.plugin_dir.iterdir():
            if not plugin_path.is_dir():
                continue

            manifest_path = plugin_path / "plugin.yaml"
            if not manifest_path.exists():
                continue

            try:
                manifest = PluginManifest.from_yaml(manifest_path)
                info = PluginInfo(path=plugin_path, manifest=manifest)
                self._plugins[manifest.name] = info
                discovered.append(info)
                logger.debug(f"Discovered plugin: {manifest.name}")
            except ManifestValidationError as e:
                logger.error(f"Invalid manifest in {plugin_path}: {e}")
            except Exception as e:
                logger.error(f"Error loading plugin from {plugin_path}: {e}")

        return discovered

    def resolve_load_order(self) -> list[str]:
        """Resolve plugin load order based on dependencies.

        Uses topological sort to ensure dependencies are loaded first.

        Returns:
            List of plugin names in load order

        Raises:
            PluginLoadError: If circular dependency detected
        """
        enabled_plugins = {
            name: info for name, info in self._plugins.items() if info.manifest.enabled
        }

        # Build dependency graph
        # Priority: higher priority loaded first (for dependencies)
        # Dependencies: must be loaded before dependent

        order: list[str] = []
        visited: set[str] = set()
        visiting: set[str] = set()  # For cycle detection

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in visiting:
                raise PluginLoadError(f"Circular dependency detected involving: {name}")

            visiting.add(name)

            # Visit dependencies first
            info = enabled_plugins.get(name)
            if info:
                for dep in info.manifest.dependencies:
                    if dep in enabled_plugins:
                        visit(dep)
                    elif dep not in self._plugins:
                        logger.warning(f"Plugin '{name}' depends on missing plugin '{dep}'")

            visiting.remove(name)
            visited.add(name)
            order.append(name)

        # Sort by priority (higher first), then visit
        sorted_names = sorted(
            enabled_plugins.keys(),
            key=lambda n: enabled_plugins[n].manifest.priority,
            reverse=True,
        )

        for name in sorted_names:
            visit(name)

        self._load_order = order
        return order

    def load_plugins(self) -> list[PluginInfo]:
        """Discover and load all plugins.

        Returns:
            List of successfully loaded PluginInfo
        """
        # Discover if not already done
        if not self._plugins:
            self.discover_plugins()

        # Resolve load order
        try:
            load_order = self.resolve_load_order()
        except PluginLoadError as e:
            logger.error(f"Failed to resolve plugin load order: {e}")
            return []

        loaded: list[PluginInfo] = []

        for name in load_order:
            info = self._plugins.get(name)
            if info is None:
                continue

            try:
                self._load_plugin(info)
                loaded.append(info)
            except (PluginLoadError, PluginEnableError) as e:
                info.load_error = e
                logger.error(f"Failed to load plugin '{name}': {e}")

        return loaded

    def _load_plugin(self, info: PluginInfo) -> BasePlugin:
        """Load a single plugin.

        Args:
            info: Plugin info to load

        Returns:
            Loaded plugin instance

        Raises:
            PluginLoadError: If loading fails
        """
        # Check required capabilities
        missing_caps = [
            cap for cap in info.manifest.capabilities_required if not has_capability(cap)
        ]
        if missing_caps:
            raise PluginLoadError(
                f"Plugin '{info.name}' requires missing capabilities: {missing_caps}"
            )

        # Load the plugin module
        plugin_class = self._load_plugin_class(info.path, info.name)
        if plugin_class is None:
            raise PluginLoadError(f"Could not find plugin class in {info.path}")

        info.plugin_class = plugin_class

        # Instantiate
        instance = plugin_class(info.path, info.manifest)
        info.instance = instance

        # Enable
        try:
            instance.enable()
        except Exception as e:
            info.instance = None
            raise PluginEnableError(f"Failed to enable plugin '{info.name}': {e}") from e

        logger.info(f"Loaded plugin: {info.name} v{info.manifest.version}")
        return instance

    def _load_plugin_class(self, plugin_path: Path, plugin_name: str) -> Optional[Type[BasePlugin]]:
        """Load the plugin class from the module.

        Looks for a BasePlugin subclass in the module.

        Args:
            plugin_path: Path to plugin directory
            plugin_name: Name of the plugin

        Returns:
            Plugin class or None if not found
        """
        # Try to load the module
        init_path = plugin_path / "__init__.py"
        if not init_path.exists():
            logger.debug(f"No __init__.py in {plugin_path}")
            return None

        try:
            spec = importlib.util.spec_from_file_location(plugin_name, init_path)
            if spec is None or spec.loader is None:
                return None

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find BasePlugin subclass
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BasePlugin)
                    and attr is not BasePlugin
                ):
                    return attr

            logger.warning(f"No BasePlugin subclass found in {plugin_path}")
            return None

        except Exception as e:
            logger.error(f"Error loading module from {plugin_path}: {e}")
            return None

    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        """Get a loaded plugin by name.

        Args:
            name: Plugin name

        Returns:
            Plugin instance or None if not loaded
        """
        info = self._plugins.get(name)
        if info is not None:
            return info.instance
        return None

    def list_plugins(self) -> list[PluginInfo]:
        """List all discovered plugins.

        Returns:
            List of PluginInfo for all plugins
        """
        return list(self._plugins.values())

    def enable_plugin(self, name: str) -> bool:
        """Enable a plugin.

        Args:
            name: Plugin name

        Returns:
            True if plugin was enabled
        """
        info = self._plugins.get(name)
        if info is None or info.instance is None:
            return False

        try:
            info.instance.enable()
            return True
        except Exception as e:
            logger.error(f"Failed to enable plugin '{name}': {e}")
            return False

    def disable_plugin(self, name: str) -> bool:
        """Disable a plugin.

        Args:
            name: Plugin name

        Returns:
            True if plugin was disabled
        """
        info = self._plugins.get(name)
        if info is None or info.instance is None:
            return False

        try:
            info.instance.disable()
            return True
        except Exception as e:
            logger.error(f"Failed to disable plugin '{name}': {e}")
            return False

    def reload_plugin(self, name: str) -> bool:
        """Reload a plugin.

        Disables, reloads the module, and re-enables.

        Args:
            name: Plugin name

        Returns:
            True if plugin was reloaded
        """
        info = self._plugins.get(name)
        if info is None:
            return False

        # Disable if loaded
        if info.instance is not None:
            info.instance.disable()
            info.instance = None

        # Clear the cached class
        info.plugin_class = None

        # Reload
        try:
            self._load_plugin(info)
            return True
        except Exception as e:
            info.load_error = e if isinstance(e, Exception) else Exception(str(e))
            logger.error(f"Failed to reload plugin '{name}': {e}")
            return False


def discover_plugins(plugin_dir: Path) -> list[PluginInfo]:
    """Convenience function to discover plugins.

    Args:
        plugin_dir: Directory containing plugin subdirectories

    Returns:
        List of PluginInfo for discovered plugins
    """
    manager = PluginManager(plugin_dir)
    return manager.discover_plugins()


__all__ = [
    "PluginManager",
    "PluginInfo",
    "discover_plugins",
]
