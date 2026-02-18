"""Logging configuration with plugin attribution.

Provides structured logging with separate verbose and error logs,
plugin attribution via LoggerAdapter, and log rotation.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any


class PluginLogAdapter(logging.LoggerAdapter):
    """Logger adapter that adds plugin attribution to log messages.

    Format: [timestamp] [level] [plugin] message
    """

    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        """Process log message to add plugin prefix."""
        plugin_name = self.extra.get("plugin", "core")
        return f"[{plugin_name}] {msg}", kwargs


def setup_logging(
    logs_dir: str | Path,
    log_level: str = "INFO",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 3,
    console_output: bool = False,
) -> None:
    """Set up logging infrastructure.

    Creates two log files:
    - verbose.log: All messages at DEBUG level and above
    - error.log: Only WARNING level and above

    Args:
        logs_dir: Directory for log files
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        max_bytes: Maximum log file size before rotation
        backup_count: Number of backup files to keep
        console_output: Also output to console (stderr)
    """
    logs_path = Path(logs_dir)
    logs_path.mkdir(parents=True, exist_ok=True)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture all messages

    # Clear existing handlers
    root_logger.handlers.clear()

    # Define format
    log_format = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Verbose log - all messages at DEBUG and above
    verbose_handler = logging.handlers.RotatingFileHandler(
        logs_path / "verbose.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    verbose_handler.setLevel(logging.DEBUG)
    verbose_handler.setFormatter(log_format)
    root_logger.addHandler(verbose_handler)

    # Error log - only WARNING and above
    error_handler = logging.handlers.RotatingFileHandler(
        logs_path / "error.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(log_format)
    root_logger.addHandler(error_handler)

    # Optional console output
    if console_output:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(getattr(logging, log_level.upper()))
        console_handler.setFormatter(log_format)
        root_logger.addHandler(console_handler)

    # Log setup completion
    root_logger.info(f"Logging initialized: verbose.log (DEBUG+), error.log (WARNING+)")


def get_logger(name: str, plugin: str = "core") -> PluginLogAdapter:
    """Get a logger with plugin attribution.

    Args:
        name: Logger name (typically __name__)
        plugin: Plugin identifier for attribution

    Returns:
        Logger adapter with plugin prefix

    Example:
        logger = get_logger(__name__, plugin="voice_capture")
        logger.info("Started recording")  # Logs: [voice_capture] Started recording
    """
    logger = logging.getLogger(name)
    return PluginLogAdapter(logger, {"plugin": plugin})


def get_plugin_logger(plugin_name: str) -> PluginLogAdapter:
    """Get a logger specifically for a plugin.

    Convenience function that creates a logger with the plugin name
    as both the logger name and plugin attribution.

    Args:
        plugin_name: Name of the plugin

    Returns:
        Logger adapter for the plugin

    Example:
        logger = get_plugin_logger("transcription")
        logger.info("Model loaded")  # Logs: [transcription] Model loaded
    """
    return get_logger(f"butler.plugins.{plugin_name}", plugin=plugin_name)


def set_log_level(level: str) -> None:
    """Change the log level for all handlers.

    Args:
        level: New log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    root_logger = logging.getLogger()
    new_level = getattr(logging, level.upper())

    for handler in root_logger.handlers:
        # Only change file handlers if they're not the error log
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            if handler.baseFilename.endswith("verbose.log"):
                handler.setLevel(new_level)
        else:
            handler.setLevel(new_level)

    root_logger.info(f"Log level changed to {level}")


__all__ = [
    "setup_logging",
    "get_logger",
    "get_plugin_logger",
    "set_log_level",
    "PluginLogAdapter",
]
