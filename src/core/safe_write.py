"""Safe write protocol to prevent file corruption from race conditions.

Uses atomic temp+replace with mtime double-check to ensure data integrity
when writing files that may be accessed by other applications (e.g., Obsidian).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any


class SafeWriteError(Exception):
    """Exception raised when safe write fails after all retries."""

    def __init__(self, message: str, path: Path | None = None, attempts: int = 0) -> None:
        super().__init__(message)
        self.path = path
        self.attempts = attempts


def safe_write(
    filepath: str | Path,
    content: str,
    *,
    max_retries: int = 3,
    retry_delay: float = 0.1,
    encoding: str = "utf-8",
) -> dict[str, Any]:
    """Write file content atomically with race condition protection.

    Uses the following algorithm:
    1. Record pre_mtime if file exists
    2. Write to temp file in same directory
    3. Atomic move (os.rename)
    4. Verify post_mtime differs from pre_mtime (if file existed)
    5. If conflict detected, retry with exponential backoff

    Args:
        filepath: Target file path
        content: Content to write
        max_retries: Maximum number of retry attempts
        retry_delay: Initial delay between retries (doubles each retry)
        encoding: File encoding

    Returns:
        Dictionary with operation details:
        - success: True if write succeeded
        - path: Final file path
        - attempts: Number of attempts made
        - pre_mtime: Original file mtime (if file existed)
        - post_mtime: New file mtime after write

    Raises:
        SafeWriteError: If write fails after all retries

    Example:
        result = safe_write("/path/to/file.md", "# Hello\n")
        if result["success"]:
            print(f"Written in {result['attempts']} attempts")
    """
    path = Path(filepath)
    attempts = 0
    current_delay = retry_delay

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    while attempts < max_retries:
        attempts += 1

        try:
            # Step 1: Record pre_mtime if file exists
            pre_mtime = None
            if path.exists():
                pre_mtime = path.stat().st_mtime

            # Step 2: Write to temp file in same directory
            # Using same directory ensures atomic rename works across filesystems
            temp_fd, temp_path = tempfile.mkstemp(
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
            )

            try:
                # Write content to temp file
                with os.fdopen(temp_fd, "w", encoding=encoding) as f:
                    f.write(content)
                    f.flush()
                    os.fsync(temp_fd)

                # Step 3: Atomic move
                # On Unix, os.rename is atomic. On Windows, we might need to use
                # a different approach, but Python's os.rename handles this.
                if path.exists():
                    # Windows requires remove first, Unix doesn't
                    if os.name == "nt":
                        # On Windows, try replace first (atomic on NTFS)
                        try:
                            os.replace(temp_path, path)
                        except OSError:
                            # Fall back to delete + rename
                            os.remove(path)
                            os.rename(temp_path, path)
                    else:
                        os.rename(temp_path, path)
                else:
                    os.rename(temp_path, path)

                # Ensure the rename is flushed to disk
                dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)

                # Step 4: Verify post_mtime differs from pre_mtime
                post_mtime = path.stat().st_mtime

                if pre_mtime is not None and post_mtime == pre_mtime:
                    # Conflict detected - file was modified between read and write
                    if attempts < max_retries:
                        time.sleep(current_delay)
                        current_delay *= 2  # Exponential backoff
                        continue
                    else:
                        raise SafeWriteError(
                            f"File modification conflict detected after {attempts} attempts",
                            path=path,
                            attempts=attempts,
                        )

                # Success!
                return {
                    "success": True,
                    "path": path,
                    "attempts": attempts,
                    "pre_mtime": pre_mtime,
                    "post_mtime": post_mtime,
                }

            except Exception:
                # Clean up temp file on error
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except Exception:
                    pass
                raise

        except SafeWriteError:
            raise
        except Exception as e:
            if attempts < max_retries:
                time.sleep(current_delay)
                current_delay *= 2
                continue
            raise SafeWriteError(
                f"Write failed after {attempts} attempts: {e}",
                path=path,
                attempts=attempts,
            ) from e

    # Should not reach here, but just in case
    raise SafeWriteError(
        f"Write failed after {attempts} attempts",
        path=path,
        attempts=attempts,
    )


def safe_write_json(
    filepath: str | Path,
    data: Any,
    *,
    indent: int = 2,
    max_retries: int = 3,
    **kwargs,
) -> dict[str, Any]:
    """Write JSON data safely using safe_write.

    Args:
        filepath: Target file path
        data: JSON-serializable data
        indent: JSON indentation
        max_retries: Maximum retry attempts
        **kwargs: Additional arguments for safe_write

    Returns:
        Same as safe_write()
    """
    import json

    content = json.dumps(data, indent=indent, ensure_ascii=False)
    return safe_write(filepath, content, max_retries=max_retries, **kwargs)


def safe_read(
    filepath: str | Path,
    *,
    encoding: str = "utf-8",
    default: str | None = None,
) -> str | None:
    """Safely read file content.

    Args:
        filepath: File to read
        encoding: File encoding
        default: Default value if file doesn't exist

    Returns:
        File content or default value
    """
    path = Path(filepath)
    if not path.exists():
        return default

    with open(path, "r", encoding=encoding) as f:
        return f.read()


def get_file_mtime(filepath: str | Path) -> float | None:
    """Get file modification time.

    Args:
        filepath: File path

    Returns:
        Modification time (seconds since epoch) or None if file doesn't exist
    """
    path = Path(filepath)
    if path.exists():
        return path.stat().st_mtime
    return None


__all__ = [
    "safe_write",
    "safe_write_json",
    "safe_read",
    "get_file_mtime",
    "SafeWriteError",
]
