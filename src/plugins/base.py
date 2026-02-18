"""Base plugin class for all Butler plugins.

Provides lifecycle methods, event connection, and capability registration.
Plugins extend this class and implement the lifecycle hooks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from src.core.capabilities import register_capability, unregister_capability
from src.core.event_bus import emit
from src.plugins.manifest import PluginManifest


class BasePlugin(ABC):
    """Abstract base class for Butler plugins.

    Plugins must implement on_enable() and on_disable() methods.
    The base class handles:
    - Manifest loading and validation
    - Capability registration
    - Event connection
    - Lifecycle management

    Example:
        class VoiceInputPlugin(BasePlugin):
            def on_enable(self) -> None:
                # Register capabilities
                self.register_capability("transcription", self.transcribe)

                # Subscribe to events
                self.connect_events()

            def on_disable(self) -> None:
                # Cleanup resources
                self.model = None

            def transcribe(self, audio: bytes) -> str:
                return "transcribed text"
    """

    def __init__(self, plugin_dir: Path, manifest: Optional[PluginManifest] = None) -> None:
        """Initialize the plugin.

        Args:
            plugin_dir: Directory containing the plugin
            manifest: Optional pre-loaded manifest (will load from plugin_dir if not provided)
        """
        self.plugin_dir = plugin_dir
        self._manifest = manifest
        self._enabled = False
        self._event_subscriptions: list[Any] = []

    @property
    def manifest(self) -> PluginManifest:
        """Get the plugin manifest, loading if necessary."""
        if self._manifest is None:
            manifest_path = self.plugin_dir / "plugin.yaml"
            self._manifest = PluginManifest.from_yaml(manifest_path)
        return self._manifest

    @property
    def name(self) -> str:
        """Get the plugin name."""
        return self.manifest.name

    @property
    def version(self) -> str:
        """Get the plugin version."""
        return self.manifest.version

    @property
    def description(self) -> str:
        """Get the plugin description."""
        return self.manifest.description

    @property
    def is_enabled(self) -> bool:
        """Check if the plugin is enabled."""
        return self._enabled

    def enable(self) -> None:
        """Enable the plugin.

        Calls on_enable() and marks the plugin as enabled.
        Subclasses should override on_enable() instead of this method.
        """
        if self._enabled:
            return

        self.on_enable()
        self._enabled = True

        # Register declared capabilities
        self._register_capabilities()

        # Connect to events
        self.connect_events()

    def disable(self) -> None:
        """Disable the plugin.

        Calls on_disable(), unregisters capabilities, disconnects events,
        and marks the plugin as disabled.
        Subclasses should override on_disable() instead of this method.
        """
        if not self._enabled:
            return

        # Disconnect events first
        self.disconnect_events()

        # Unregister capabilities
        self._unregister_capabilities()

        self.on_disable()
        self._enabled = False

    @abstractmethod
    def on_enable(self) -> None:
        """Called when the plugin is enabled.

        Subclasses should implement this to:
        - Initialize resources
        - Register capabilities via self.register_capability()
        - Set up any required state

        This method is called before capabilities are registered
        and events are connected.
        """
        pass

    @abstractmethod
    def on_disable(self) -> None:
        """Called when the plugin is disabled.

        Subclasses should implement this to:
        - Clean up resources
        - Save state if needed
        - Close connections

        This method is called after events are disconnected
        and capabilities are unregistered.
        """
        pass

    def connect_events(self) -> None:
        """Connect to event signals declared in the manifest.

        Subclasses can override to set up custom event handlers,
        but should call super().connect_events() first.
        """
        # This is a hook - base implementation does nothing
        # Subclasses override to subscribe to specific events
        pass

    def disconnect_events(self) -> None:
        """Disconnect all event subscriptions.

        Automatically called during disable().
        """
        from src.core.event_bus import disconnect_all

        # Disconnect stored subscriptions
        for sub in self._event_subscriptions:
            try:
                sub.disconnect()
            except Exception:
                pass
        self._event_subscriptions.clear()

    def register_capability(self, name: str, capability: Any, **metadata: Any) -> None:
        """Register a capability with the global registry.

        Args:
            name: Capability name (should match manifest's capabilities_provided)
            capability: The capability function/object
            **metadata: Additional metadata for the capability
        """
        meta = {"provider": self.name, **metadata}
        register_capability(name, capability, metadata=meta)

    def _register_capabilities(self) -> None:
        """Register all declared capabilities.

        Called automatically during enable().
        Note: Subclasses must manually call register_capability()
        in their on_enable() for actual capabilities.
        """
        pass  # Capabilities are registered manually in on_enable()

    def _unregister_capabilities(self) -> None:
        """Unregister all capabilities provided by this plugin."""
        for cap_name in self.manifest.capabilities_provided:
            try:
                unregister_capability(cap_name)
            except Exception:
                pass  # Capability may not have been registered

    def emit_event(self, signal_name: str, **kwargs: Any) -> None:
        """Emit an event signal.

        Args:
            signal_name: Name of the signal to emit
            **kwargs: Signal-specific arguments
        """
        emit(signal_name, sender=self.name, **kwargs)

    def __repr__(self) -> str:
        """String representation of the plugin."""
        return f"<{self.__class__.__name__}: {self.name} v{self.version}>"


class PluginError(Exception):
    """Base exception for plugin-related errors."""

    pass


class PluginLoadError(PluginError):
    """Raised when a plugin fails to load."""

    pass


class PluginEnableError(PluginError):
    """Raised when a plugin fails to enable."""

    pass


__all__ = [
    "BasePlugin",
    "PluginError",
    "PluginLoadError",
    "PluginEnableError",
]
