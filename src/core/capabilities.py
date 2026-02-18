"""Capability registry for loose plugin coupling.

Provides a thread-safe registry where plugins can register capabilities
they provide and consume capabilities from other plugins without hard
dependencies.

Usage:
    # Register a capability
    register_capability("transcription", transcribe_func)

    # Check if capability exists
    if has_capability("transcription"):
        transcriber = get_capability("transcription")

    # Graceful degradation
    embeddings = get_capability("embeddings", default=None)
    if embeddings is None:
        # Fall back to simpler approach
        pass
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from blinker import Signal


class CapabilityRegistry:
    """Thread-safe registry for plugin capabilities.

    Capabilities are named functions or objects that plugins can provide
    and consume. This enables loose coupling - plugins don't need to
    import each other directly.

    Example:
        registry = CapabilityRegistry()

        # Plugin A registers a capability
        registry.register("classifier", classify_text)

        # Plugin B uses it without importing Plugin A
        if registry.has("classifier"):
            classifier = registry.get("classifier")
            result = classifier("some text")
    """

    def __init__(self) -> None:
        self._capabilities: dict[str, Any] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

        # Signal emitted when a capability is registered
        self.capability_registered = Signal("capability.registered")

    def register(
        self,
        name: str,
        capability: Any,
        *,
        metadata: Optional[dict[str, Any]] = None,
        overwrite: bool = False,
    ) -> None:
        """Register a capability by name.

        Args:
            name: Unique capability identifier
            capability: The capability object/function
            metadata: Optional metadata (provider, version, description)
            overwrite: If True, allow overwriting existing capability

        Raises:
            ValueError: If capability already exists and overwrite=False
        """
        with self._lock:
            if name in self._capabilities and not overwrite:
                raise ValueError(
                    f"Capability '{name}' already registered. Use overwrite=True to replace."
                )

            self._capabilities[name] = capability
            self._metadata[name] = metadata or {}
            self._metadata[name]["name"] = name

            # Emit signal for listeners
            self.capability_registered.send(
                self, name=name, capability=capability, metadata=metadata
            )

    def unregister(self, name: str) -> bool:
        """Remove a capability from the registry.

        Args:
            name: Capability to remove

        Returns:
            True if capability was removed, False if not found
        """
        with self._lock:
            if name in self._capabilities:
                del self._capabilities[name]
                del self._metadata[name]
                return True
            return False

    def get(self, name: str, default: Any = None) -> Any:
        """Get a capability by name.

        Args:
            name: Capability to retrieve
            default: Value to return if not found (default: None)

        Returns:
            The capability object or default value
        """
        with self._lock:
            return self._capabilities.get(name, default)

    def has(self, name: str) -> bool:
        """Check if a capability is registered.

        Args:
            name: Capability to check

        Returns:
            True if capability exists
        """
        with self._lock:
            return name in self._capabilities

    def get_metadata(self, name: str) -> Optional[dict[str, Any]]:
        """Get metadata for a capability.

        Args:
            name: Capability name

        Returns:
            Metadata dict or None if not found
        """
        with self._lock:
            return self._metadata.get(name)

    def list_capabilities(self) -> list[str]:
        """List all registered capability names.

        Returns:
            List of capability names
        """
        with self._lock:
            return list(self._capabilities.keys())

    def clear(self) -> None:
        """Remove all capabilities from the registry.

        Useful for testing or resetting state.
        """
        with self._lock:
            self._capabilities.clear()
            self._metadata.clear()

    def __contains__(self, name: str) -> bool:
        """Support 'in' operator for checking capabilities."""
        return self.has(name)

    def __len__(self) -> int:
        """Return number of registered capabilities."""
        with self._lock:
            return len(self._capabilities)


# Global registry instance
_global_registry: Optional[CapabilityRegistry] = None
_registry_lock = threading.Lock()


def get_registry() -> CapabilityRegistry:
    """Get the global capability registry.

    Creates the registry on first access (lazy initialization).

    Returns:
        The global CapabilityRegistry instance
    """
    global _global_registry
    if _global_registry is None:
        with _registry_lock:
            if _global_registry is None:
                _global_registry = CapabilityRegistry()
    return _global_registry


def register_capability(
    name: str,
    capability: Any,
    *,
    metadata: Optional[dict[str, Any]] = None,
    overwrite: bool = False,
) -> None:
    """Register a capability in the global registry.

    Args:
        name: Unique capability identifier
        capability: The capability object/function
        metadata: Optional metadata (provider, version, description)
        overwrite: If True, allow overwriting existing capability

    Raises:
        ValueError: If capability already exists and overwrite=False
    """
    get_registry().register(name, capability, metadata=metadata, overwrite=overwrite)


def get_capability(name: str, default: Any = None) -> Any:
    """Get a capability from the global registry.

    Args:
        name: Capability to retrieve
        default: Value to return if not found (default: None)

    Returns:
        The capability object or default value
    """
    return get_registry().get(name, default)


def has_capability(name: str) -> bool:
    """Check if a capability is registered in the global registry.

    Args:
        name: Capability to check

    Returns:
        True if capability exists
    """
    return get_registry().has(name)


def unregister_capability(name: str) -> bool:
    """Remove a capability from the global registry.

    Args:
        name: Capability to remove

    Returns:
        True if capability was removed, False if not found
    """
    return get_registry().unregister(name)


def list_capabilities() -> list[str]:
    """List all capabilities in the global registry.

    Returns:
        List of capability names
    """
    return get_registry().list_capabilities()


def clear_registry() -> None:
    """Clear the global registry.

    Useful for testing or resetting state.
    """
    get_registry().clear()


__all__ = [
    "CapabilityRegistry",
    "get_registry",
    "register_capability",
    "get_capability",
    "has_capability",
    "unregister_capability",
    "list_capabilities",
    "clear_registry",
]
