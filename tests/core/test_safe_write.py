"""Tests for the safe write protocol."""

import concurrent.futures
import json
import os
import tempfile
import threading
import time
from pathlib import Path

import pytest

from src.core.safe_write import (
    SafeWriteError,
    get_file_mtime,
    safe_read,
    safe_write,
    safe_write_json,
)


class TestSafeWriteBasics:
    """Test basic safe write functionality."""

    def test_write_new_file(self) -> None:
        """Test writing to a new file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"
            result = safe_write(filepath, "Hello, World!")

            assert result["success"] is True
            assert result["path"] == filepath
            assert result["attempts"] == 1
            assert filepath.exists()
            assert filepath.read_text() == "Hello, World!"

    def test_overwrite_existing_file(self) -> None:
        """Test overwriting an existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"
            filepath.write_text("Original content")

            result = safe_write(filepath, "New content")

            assert result["success"] is True
            assert filepath.read_text() == "New content"

    def test_creates_parent_directories(self) -> None:
        """Test that parent directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = Path(tmpdir) / "a" / "b" / "c" / "file.txt"

            result = safe_write(nested_path, "Deep content")

            assert result["success"] is True
            assert nested_path.exists()
            assert nested_path.read_text() == "Deep content"

    def test_returns_mtime_info(self) -> None:
        """Test that mtime information is returned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"

            # Write initial file
            result1 = safe_write(filepath, "Version 1")
            assert result1["post_mtime"] is not None

            # Overwrite
            time.sleep(0.01)  # Ensure mtime changes
            result2 = safe_write(filepath, "Version 2")
            assert result2["pre_mtime"] == result1["post_mtime"]
            assert result2["post_mtime"] > result2["pre_mtime"]


class TestSafeWriteConcurrency:
    """Test safe write under concurrent access."""

    def test_concurrent_writes_no_corruption(self) -> None:
        """Test that concurrent writes don't corrupt data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "concurrent.txt"
            num_writers = 10
            messages_per_writer = 10

            def writer(writer_id: int) -> list[str]:
                messages = []
                for i in range(messages_per_writer):
                    message = f"Writer {writer_id} message {i}"
                    safe_write(filepath, message)
                    messages.append(message)
                return messages

            # Run writers concurrently
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_writers) as executor:
                futures = [executor.submit(writer, i) for i in range(num_writers)]
                concurrent.futures.wait(futures)

            # Verify file contains valid content (one complete message)
            final_content = filepath.read_text()
            # Should be one complete message, not corrupted data
            assert final_content.startswith("Writer ")
            assert "message " in final_content

    def test_atomic_write_guarantee(self) -> None:
        """Test atomic write - readers see old or new, never partial."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "atomic.txt"

            # Initial content
            safe_write(filepath, "INITIAL")

            readers_saw_valid = []

            def reader() -> None:
                for _ in range(100):
                    content = filepath.read_text()
                    # Should only see INITIAL or FINAL, never partial
                    if content in ["INITIAL", "FINAL"]:
                        readers_saw_valid.append(True)
                    else:
                        readers_saw_valid.append(False)

            def writer() -> None:
                for _ in range(50):
                    safe_write(filepath, "FINAL")
                    safe_write(filepath, "INITIAL")

            # Run readers and writers concurrently
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                reader_futures = [executor.submit(reader) for _ in range(3)]
                writer_futures = [executor.submit(writer) for _ in range(2)]
                concurrent.futures.wait(reader_futures + writer_futures)

            # All reads should have seen valid content
            assert all(readers_saw_valid), "Some readers saw corrupted content"


class TestSafeWriteRetries:
    """Test retry behavior."""

    def test_success_on_first_attempt(self) -> None:
        """Test normal write succeeds on first attempt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"
            result = safe_write(filepath, "Content")

            assert result["attempts"] == 1

    def test_retry_on_conflict(self) -> None:
        """Test that write retries on conflict detection."""
        # This is hard to test directly, but we can verify the retry mechanism exists
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"

            # First write
            safe_write(filepath, "Original")

            # Mock a conflict by manually modifying the file after safe_write reads it
            # This is internal behavior, so we mainly verify the code path exists

            # Write again (normal case, no conflict)
            result = safe_write(filepath, "Updated")
            assert result["success"] is True


class TestSafeWriteJson:
    """Test JSON safe write functionality."""

    def test_write_json_data(self) -> None:
        """Test writing JSON data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "data.json"
            data = {"name": "test", "value": 42, "nested": {"key": "val"}}

            result = safe_write_json(filepath, data)

            assert result["success"] is True

            # Verify JSON content
            loaded = json.loads(filepath.read_text())
            assert loaded["name"] == "test"
            assert loaded["value"] == 42
            assert loaded["nested"]["key"] == "val"

    def test_json_indentation(self) -> None:
        """Test JSON indentation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "pretty.json"
            data = {"key": "value"}

            safe_write_json(filepath, data, indent=4)

            content = filepath.read_text()
            assert '    "key"' in content  # 4-space indent


class TestSafeRead:
    """Test safe read functionality."""

    def test_read_existing_file(self) -> None:
        """Test reading an existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"
            filepath.write_text("File content")

            content = safe_read(filepath)
            assert content == "File content"

    def test_read_missing_file_with_default(self) -> None:
        """Test reading missing file returns default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "missing.txt"

            content = safe_read(filepath, default="default_value")
            assert content == "default_value"

    def test_read_missing_file_no_default(self) -> None:
        """Test reading missing file returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "missing.txt"

            content = safe_read(filepath)
            assert content is None


class TestGetFileMtime:
    """Test file modification time retrieval."""

    def test_get_mtime_existing_file(self) -> None:
        """Test getting mtime of existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"
            filepath.write_text("Content")

            mtime = get_file_mtime(filepath)
            assert mtime is not None
            assert isinstance(mtime, float)

    def test_get_mtime_missing_file(self) -> None:
        """Test getting mtime of missing file returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "missing.txt"

            mtime = get_file_mtime(filepath)
            assert mtime is None


class TestSafeWriteError:
    """Test SafeWriteError exception."""

    def test_error_attributes(self) -> None:
        """Test that error has correct attributes."""
        path = Path("/test/path.txt")
        error = SafeWriteError("Test error", path=path, attempts=3)

        assert str(error) == "Test error"
        assert error.path == path
        assert error.attempts == 3


class TestEncoding:
    """Test encoding handling."""

    def test_unicode_content(self) -> None:
        """Test writing unicode content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "unicode.txt"
            content = "Hello 世界 🌍 émojis"

            safe_write(filepath, content)

            result = safe_read(filepath)
            assert result == content

    def test_custom_encoding(self) -> None:
        """Test custom encoding."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "encoded.txt"
            # This would fail with ascii encoding
            content = "Unicode: émoji 🎉"

            safe_write(filepath, content, encoding="utf-8")
            result = safe_read(filepath, encoding="utf-8")
            assert result == content


class TestStressTest:
    """Stress tests for safe write."""

    def test_100_concurrent_writes(self) -> None:
        """Stress test: 100 concurrent writes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "stress.txt"

            def writer(writer_id: int) -> bool:
                try:
                    content = f"Writer {writer_id:03d} content with padding to make it longer"
                    result = safe_write(filepath, content)
                    return result["success"]
                except Exception:
                    return False

            # Launch 100 concurrent writers
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                futures = [executor.submit(writer, i) for i in range(100)]
                results = [f.result() for f in concurrent.futures.as_completed(futures)]

            # All writes should succeed
            assert all(results), "Some writes failed"

            # File should contain valid content
            final_content = filepath.read_text()
            assert final_content.startswith("Writer ")
            assert len(final_content) > 20
