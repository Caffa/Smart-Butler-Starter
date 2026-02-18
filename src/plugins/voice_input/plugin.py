"""Voice input plugin for automatic voice memo transcription.

Watches a configured folder for new audio files and transcribes them
using the parakeet-mlx model. Emits input.received events with transcribed text.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Optional

from src.core.config import get_config
from src.core.event_bus import input_received, emit
from src.core.safe_write import safe_write
from src.core.transcriber import TranscriptionError, Transcriber
from src.plugins.base import BasePlugin
from src.plugins.manifest import PluginManifest

logger = logging.getLogger(__name__)


class VoiceInputPlugin(BasePlugin):
    """Plugin that watches for voice memos and transcribes them.

    Features:
    - Watch configured folder for new audio files
    - Transcribe using parakeet-mlx
    - Filter by confidence threshold
    - Move processed files to subfolder
    - Detect duplicate files via SHA hash
    """

    # Supported audio extensions
    SUPPORTED_EXTENSIONS = {".m4a", ".mp3", ".wav", ".aac", ".flac"}

    def __init__(self, plugin_dir: Path, manifest: Optional[PluginManifest] = None) -> None:
        """Initialize the voice input plugin."""
        super().__init__(plugin_dir, manifest)
        self._transcriber: Optional[Transcriber] = None
        self._watch_path: Optional[Path] = None
        self._processed_folder: Optional[Path] = None
        self._processed_hashes: set[str] = set()
        self._config: dict[str, Any] = {}

    @property
    def transcriber(self) -> Transcriber:
        """Get or create the transcriber instance."""
        if self._transcriber is None:
            confidence = self._config.get("confidence_threshold", 0.5)
            self._transcriber = Transcriber(confidence_threshold=confidence)
        return self._transcriber

    def _load_config(self) -> None:
        """Load plugin configuration."""
        plugin_config = get_config().get("plugins", {}).get("voice_input", {})

        # Default config values
        default_watch_path = "~/Music/Voice Memos"
        default_confidence_threshold = 0.5
        default_move_processed = True
        default_processed_folder = "processed"

        # Get watch path from config or default
        watch_path = plugin_config.get("watch_path", default_watch_path)
        self._watch_path = Path(os.path.expanduser(watch_path))

        # Get processed folder
        move_processed = plugin_config.get("move_processed", default_move_processed)

        if move_processed:
            processed_name = plugin_config.get("processed_folder", default_processed_folder)
            self._processed_folder = self._watch_path / processed_name
            self._processed_folder.mkdir(parents=True, exist_ok=True)
        else:
            self._processed_folder = None

        # Confidence threshold
        self._config["confidence_threshold"] = plugin_config.get(
            "confidence_threshold", default_confidence_threshold
        )

        logger.info(
            f"Voice input configured: watch={self._watch_path}, "
            f"processed={self._processed_folder}, "
            f"threshold={self._config['confidence_threshold']}"
        )

    def on_enable(self) -> None:
        """Enable the plugin and start watching."""
        self._load_config()

        # Validate watch path exists
        if self._watch_path and not self._watch_path.exists():
            logger.warning(f"Watch path does not exist: {self._watch_path}")
            # Create it if it doesn't exist
            self._watch_path.mkdir(parents=True, exist_ok=True)

        # Load existing processed files to avoid re-processing
        self._load_processed_hashes()

        logger.info(f"Voice input plugin enabled, watching: {self._watch_path}")

    def on_disable(self) -> None:
        """Disable the plugin."""
        self._transcriber = None
        logger.info("Voice input plugin disabled")

    def _load_processed_hashes(self) -> None:
        """Load hashes of already processed files."""
        if self._processed_folder and self._processed_folder.exists():
            for file_path in self._processed_folder.iterdir():
                if file_path.is_file():
                    try:
                        hash_val = self._compute_hash(file_path)
                        self._processed_hashes.add(hash_val)
                    except Exception as e:
                        logger.warning(f"Could not hash {file_path}: {e}")

    def _compute_hash(self, file_path: Path) -> str:
        """Compute SHA256 hash of file."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _is_audio_file(self, path: Path) -> bool:
        """Check if file is a supported audio file."""
        return path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def _is_duplicate(self, file_path: Path) -> bool:
        """Check if file has already been processed."""
        try:
            file_hash = self._compute_hash(file_path)
            return file_hash in self._processed_hashes
        except Exception as e:
            logger.warning(f"Could not compute hash for {file_path}: {e}")
            return False

    def _move_to_processed(self, file_path: Path) -> None:
        """Move processed file to processed folder."""
        if not self._processed_folder:
            return

        try:
            dest = self._processed_folder / file_path.name
            # Handle name collisions
            counter = 1
            while dest.exists():
                stem = file_path.stem
                suffix = file_path.suffix
                dest = self._processed_folder / f"{stem}_{counter}{suffix}"
                counter += 1

            shutil.move(str(file_path), str(dest))

            # Add to processed hashes
            try:
                hash_val = self._compute_hash(dest)
                self._processed_hashes.add(hash_val)
            except Exception as e:
                logger.warning(f"Could not hash moved file: {e}")

            logger.info(f"Moved processed file to: {dest}")
        except Exception as e:
            logger.error(f"Failed to move file to processed: {e}")

    def process_file(self, file_path: Path) -> bool:
        """Process a single audio file.

        Args:
            file_path: Path to audio file

        Returns:
            True if file was processed successfully, False otherwise
        """
        file_path = Path(file_path)

        # Validate file
        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            return False

        if not self._is_audio_file(file_path):
            logger.debug(f"Not an audio file: {file_path}")
            return False

        # Check for duplicates
        if self._is_duplicate(file_path):
            logger.info(f"Skipping duplicate file: {file_path}")
            self._move_to_processed(file_path)
            return False

        # Transcribe
        try:
            logger.info(f"Transcribing: {file_path}")
            result = self.transcriber.transcribe(file_path)

            logger.info(
                f"Transcription complete: {result.text[:50]}... "
                f"(confidence: {result.confidence:.2f})"
            )

            # Emit input received event
            emit(
                input_received,
                sender="voice_input",
                text=result.text,
                source="voice",
                confidence=result.confidence,
                duration=result.duration,
            )

            # Move to processed
            self._move_to_processed(file_path)

            return True

        except TranscriptionError as e:
            logger.warning(f"Transcription failed for {file_path}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            return False

    def scan_folder(self) -> list[Path]:
        """Scan the watch folder for new audio files.

        Returns:
            List of audio files found
        """
        if not self._watch_path or not self._watch_path.exists():
            return []

        audio_files = []
        for file_path in self._watch_path.iterdir():
            if file_path.is_file() and self._is_audio_file(file_path):
                if not self._is_duplicate(file_path):
                    audio_files.append(file_path)

        return sorted(audio_files)

    def get_status(self) -> dict[str, Any]:
        """Get plugin status information."""
        return {
            "watch_path": str(self._watch_path) if self._watch_path else None,
            "processed_folder": str(self._processed_folder) if self._processed_folder else None,
            "transcriber_loaded": self._transcriber.is_loaded if self._transcriber else False,
            "processed_count": len(self._processed_hashes),
            "confidence_threshold": self._config.get("confidence_threshold", 0.5),
        }
