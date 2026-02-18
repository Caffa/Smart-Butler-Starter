"""Tests for the capability registry.

Tests cover:
- Register/get/has operations
- Thread-safe concurrent access
- Multiple capabilities
- Graceful degradation when capability missing
- Signal emission on registration
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.core.capabilities import (
    CapabilityRegistry,
    clear_registry,
    get_capability,
    get_registry,
    has_capability,
    list_capabilities,
    register_capability,
    unregister_capability,
)


class TestCapabilityRegistry:
    """Tests for CapabilityRegistry class."""

    def setup_method(self) -> None:
        """Create a fresh registry for each test."""
        self.registry = CapabilityRegistry()

    def test_register_and_get(self) -> None:
        """Register a capability and retrieve it."""

        def transcribe(audio: bytes) -> str:
            return "transcribed text"

        self.registry.register("transcription", transcribe)
        result = self.registry.get("transcription")

        assert result is transcribe
        assert result(b"audio data") == "transcribed text"

    def test_register_with_metadata(self) -> None:
        """Register capability with metadata."""

        def classify(text: str) -> str:
            return "category"

        self.registry.register(
            "classifier", classify, metadata={"provider": "ai_plugin", "version": "1.0.0"}
        )

        assert self.registry.has("classifier")
        metadata = self.registry.get_metadata("classifier")
        assert metadata is not None
        assert metadata["provider"] == "ai_plugin"
        assert metadata["version"] == "1.0.0"

    def test_has_capability(self) -> None:
        """Check if capability exists."""
        assert not self.registry.has("transcription")

        self.registry.register("transcription", lambda x: x)

        assert self.registry.has("transcription")
        assert "transcription" in self.registry  # Test __contains__

    def test_get_missing_capability_returns_none(self) -> None:
        """Getting missing capability returns None by default."""
        result = self.registry.get("nonexistent")
        assert result is None

    def test_get_missing_capability_returns_default(self) -> None:
        """Getting missing capability returns provided default."""
        default_func = lambda: "default"
        result = self.registry.get("nonexistent", default=default_func)
        assert result is default_func

    def test_register_duplicate_raises_error(self) -> None:
        """Registering duplicate capability raises ValueError."""
        self.registry.register("transcription", lambda x: x)

        with pytest.raises(ValueError, match="already registered"):
            self.registry.register("transcription", lambda x: "different")

    def test_register_duplicate_with_overwrite(self) -> None:
        """Can overwrite existing capability with overwrite=True."""
        original = lambda x: "original"
        replacement = lambda x: "replacement"

        self.registry.register("transcription", original)
        self.registry.register("transcription", replacement, overwrite=True)

        result = self.registry.get("transcription")
        assert result is replacement

    def test_unregister(self) -> None:
        """Unregister removes capability."""
        self.registry.register("transcription", lambda x: x)

        assert self.registry.unregister("transcription")
        assert not self.registry.has("transcription")

    def test_unregister_nonexistent_returns_false(self) -> None:
        """Unregistering nonexistent capability returns False."""
        assert not self.registry.unregister("nonexistent")

    def test_list_capabilities(self) -> None:
        """List all registered capabilities."""
        self.registry.register("transcription", lambda x: x)
        self.registry.register("classifier", lambda x: x)
        self.registry.register("embeddings", lambda x: x)

        caps = self.registry.list_capabilities()
        assert set(caps) == {"transcription", "classifier", "embeddings"}

    def test_clear(self) -> None:
        """Clear removes all capabilities."""
        self.registry.register("a", lambda: 1)
        self.registry.register("b", lambda: 2)
        self.registry.register("c", lambda: 3)

        self.registry.clear()

        assert len(self.registry) == 0
        assert self.registry.list_capabilities() == []

    def test_len(self) -> None:
        """Len returns number of capabilities."""
        assert len(self.registry) == 0

        self.registry.register("a", lambda: 1)
        assert len(self.registry) == 1

        self.registry.register("b", lambda: 2)
        assert len(self.registry) == 2

    def test_signal_emitted_on_register(self) -> None:
        """Signal is emitted when capability is registered."""
        received: list[dict] = []

        def on_register(sender, name, capability, metadata, **kwargs):
            received.append(
                {
                    "name": name,
                    "capability": capability,
                    "metadata": metadata,
                }
            )

        self.registry.capability_registered.connect(on_register)

        func = lambda x: x
        self.registry.register("test", func, metadata={"version": "1.0"})

        assert len(received) == 1
        assert received[0]["name"] == "test"
        assert received[0]["capability"] is func
        # Metadata includes the provided version plus the name added by register()
        assert received[0]["metadata"]["version"] == "1.0"
        assert received[0]["metadata"]["name"] == "test"


class TestCapabilityRegistryThreadSafety:
    """Tests for thread-safe concurrent access."""

    def test_concurrent_registration(self) -> None:
        """Multiple threads can register capabilities concurrently."""
        registry = CapabilityRegistry()
        num_threads = 50

        def register_capability(index: int) -> None:
            registry.register(f"capability_{index}", lambda i=index: i)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(register_capability, i) for i in range(num_threads)]
            for future in futures:
                future.result()  # Raise any exceptions

        assert len(registry) == num_threads
        # Verify all capabilities are accessible
        for i in range(num_threads):
            assert registry.has(f"capability_{i}")

    def test_concurrent_read_write(self) -> None:
        """Concurrent reads and writes don't cause race conditions."""
        registry = CapabilityRegistry()
        errors: list[Exception] = []

        def writer() -> None:
            for i in range(100):
                try:
                    registry.register(f"cap_{threading.current_thread().name}_{i}", lambda: i)
                except Exception as e:
                    errors.append(e)

        def reader() -> None:
            for _ in range(100):
                try:
                    registry.list_capabilities()
                    registry.has("some_capability")
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=writer, name=f"writer_{i}") for i in range(5)] + [
            threading.Thread(target=reader, name=f"reader_{i}") for i in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_registration_is_atomic(self) -> None:
        """Each registration is atomic - no partial state."""
        registry = CapabilityRegistry()
        num_threads = 10
        barrier = threading.Barrier(num_threads)

        def register_same_capability(thread_id: int) -> None:
            barrier.wait()  # All threads start at same time
            try:
                registry.register("same_cap", lambda tid=thread_id: tid)
            except ValueError:
                pass  # Expected - one thread wins

        threads = [
            threading.Thread(target=register_same_capability, args=(i,)) for i in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one registration should succeed
        assert len(registry) == 1
        cap = registry.get("same_cap")
        assert cap is not None


class TestGlobalRegistry:
    """Tests for global registry functions."""

    def setup_method(self) -> None:
        """Clear global registry before each test."""
        clear_registry()

    def test_get_registry_returns_singleton(self) -> None:
        """get_registry returns the same instance."""
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_register_capability(self) -> None:
        """register_capability registers in global registry."""

        def transcribe(audio: bytes) -> str:
            return "text"

        register_capability("transcription", transcribe)

        assert has_capability("transcription")
        result = get_capability("transcription")
        assert result is transcribe

    def test_get_capability_default(self) -> None:
        """get_capability returns default for missing."""
        result = get_capability("missing", default="fallback")
        assert result == "fallback"

    def test_unregister_capability(self) -> None:
        """unregister_capability removes from global registry."""
        register_capability("test", lambda: "test")
        assert has_capability("test")

        result = unregister_capability("test")
        assert result is True
        assert not has_capability("test")

    def test_list_capabilities(self) -> None:
        """list_capabilities returns all registered."""
        register_capability("a", lambda: 1)
        register_capability("b", lambda: 2)

        caps = list_capabilities()
        assert set(caps) == {"a", "b"}

    def test_clear_registry(self) -> None:
        """clear_registry removes all capabilities."""
        register_capability("a", lambda: 1)
        register_capability("b", lambda: 2)

        clear_registry()

        assert len(list_capabilities()) == 0


class TestCapabilityUseCases:
    """Tests demonstrating real-world use cases."""

    def setup_method(self) -> None:
        """Clear registry before each test."""
        clear_registry()

    def test_router_gets_classifier_from_ai_layer(self) -> None:
        """Router plugin gets classifier capability from AI plugin."""

        # AI plugin registers classifier
        def classify_text(text: str) -> str:
            if "meeting" in text.lower():
                return "calendar"
            return "note"

        register_capability("classifier", classify_text, metadata={"provider": "ai_plugin"})

        # Router plugin uses classifier without importing AI plugin
        classifier = get_capability("classifier")
        assert classifier is not None

        result = classifier("Schedule a meeting for tomorrow")
        assert result == "calendar"

    def test_memory_gets_embeddings_from_chromadb(self) -> None:
        """Memory plugin gets embeddings capability from ChromaDB plugin."""

        # ChromaDB plugin registers embeddings
        def create_embedding(text: str) -> list[float]:
            # Simplified mock embedding
            return [0.1, 0.2, 0.3]

        register_capability(
            "embeddings", create_embedding, metadata={"provider": "chromadb_plugin"}
        )

        # Memory plugin uses embeddings
        embedding_func = get_capability("embeddings")
        assert embedding_func is not None

        embedding = embedding_func("some text")
        assert embedding == [0.1, 0.2, 0.3]

    def test_graceful_degradation_when_capability_unavailable(self) -> None:
        """Plugin falls back gracefully when capability missing."""
        # No embeddings registered
        embeddings = get_capability("embeddings", default=None)

        if embeddings is None:
            # Fall back to simpler approach
            def simple_hash(text: str) -> int:
                return hash(text)

            embeddings = simple_hash

        result = embeddings("some text")
        assert isinstance(result, int)

    def test_multiple_capabilities_from_different_plugins(self) -> None:
        """Multiple plugins register different capabilities."""
        register_capability(
            "transcription", lambda x: "text", metadata={"provider": "voice_plugin"}
        )
        register_capability("classifier", lambda x: "note", metadata={"provider": "ai_plugin"})
        register_capability("storage", lambda x: "saved", metadata={"provider": "obsidian_plugin"})

        caps = list_capabilities()
        assert len(caps) == 3

        # Check each capability has correct metadata
        for cap_name in caps:
            metadata = get_registry().get_metadata(cap_name)
            assert metadata is not None
            assert "provider" in metadata
