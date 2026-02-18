"""Transcriber module using parakeet-mlx for local speech-to-text on Apple Silicon.

Provides lazy-loaded model initialization, confidence threshold filtering,
and error handling for audio transcription.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    """Raised when transcription fails."""

    pass


@dataclass
class TranscriptionResult:
    """Result of a transcription operation."""

    text: str
    confidence: float
    duration: float  # Duration of audio in seconds
    language: Optional[str] = None

    def __post_init__(self):
        """Validate result fields."""
        if not isinstance(self.text, str):
            raise TranscriptionError(f"text must be string, got {type(self.text)}")
        if not 0.0 <= self.confidence <= 1.0:
            raise TranscriptionError(f"confidence must be 0.0-1.0, got {self.confidence}")
        if self.duration < 0:
            raise TranscriptionError(f"duration must be non-negative, got {self.duration}")


class Transcriber:
    """Lazy-loading wrapper for parakeet-mlx transcription.

    Model is loaded on first transcription to avoid startup delay.
    Model instance is cached to avoid repeated loading.
    """

    DEFAULT_CONFIDENCE_THRESHOLD = 0.5
    DEFAULT_MODEL_NAME = "mlx-community/parakeet-ctc-1.1b"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        lazy: bool = True,
    ):
        """Initialize transcriber.

        Args:
            model_name: Name of parakeet-mlx model to use
            confidence_threshold: Minimum confidence to accept (0.0-1.0)
            lazy: If True, delay model loading until first transcription
        """
        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self.lazy = lazy

        self._model = None
        self._processor = None
        self._is_loaded = False
        self._lock = __import__("threading").Lock()

    def _load_model(self) -> None:
        """Load the parakeet-mlx model and processor.

        Raises:
            TranscriptionError: If model loading fails
        """
        with self._lock:
            if self._is_loaded:
                return

            try:
                import mlx.core as mx
                from transformers import AutoProcessor, AutoModelForCTC

                logger.info(f"Loading parakeet-mlx model: {self.model_name}")

                # Load processor
                self._processor = AutoProcessor.from_pretrained(self.model_name)

                # Load model (MLX optimized)
                self._model = AutoModelForCTC.from_pretrained(self.model_name)

                self._is_loaded = True
                logger.info("parakeet-mlx model loaded successfully")

            except ImportError as e:
                raise TranscriptionError(f"MLX or transformers not available: {e}") from e
            except Exception as e:
                raise TranscriptionError(f"Failed to load model: {e}") from e

    def _ensure_loaded(self) -> None:
        """Ensure model is loaded."""
        if not self._is_loaded:
            self._load_model()

    @property
    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self._is_loaded

    def warmup(self) -> None:
        """Load the model immediately (for dev/testing)."""
        self._load_model()

    def transcribe(self, audio_path: str | Path) -> TranscriptionResult:
        """Transcribe an audio file.

        Args:
            audio_path: Path to audio file

        Returns:
            TranscriptionResult with text, confidence, and duration

        Raises:
            TranscriptionError: If transcription fails
        """
        audio_path = Path(audio_path)

        # Validate file exists
        if not audio_path.exists():
            raise TranscriptionError(f"Audio file not found: {audio_path}")

        # Validate file is readable
        if not os.access(audio_path, os.R_OK):
            raise TranscriptionError(f"Audio file not readable: {audio_path}")

        # Load model if needed
        self._ensure_loaded()

        try:
            import mlx.core as mx
            import numpy as np
            import torch
            import torchaudio
            from transformers import AutoProcessor, AutoModelForCTC

            # Load and preprocess audio
            waveform, sample_rate = torchaudio.load(str(audio_path))

            # Convert to mono if stereo
            if waveform.shape[0] > 1:
                waveform = torch.mean(waveform, dim=0, keepdim=True)

            # Resample if needed (parakeet expects 16kHz)
            if sample_rate != 16000:
                resampler = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=16000)
                waveform = resampler(waveform)

            # Get duration
            duration = waveform.shape[1] / 16000.0

            # Process audio
            input_values = self._processor(
                waveform.squeeze().numpy(),
                sampling_rate=16000,
                return_tensors="pt",
            ).input_values

            # Run inference with MLX
            with torch.no_grad():
                logits = self._model(input_values).logits

            # Decode
            predicted_ids = torch.argmax(logits, dim=-1)
            transcription = self._processor.batch_decode(predicted_ids)[0]

            # Calculate confidence (average probability of predicted tokens)
            probs = torch.softmax(logits, dim=-1)
            confidence = float(probs[0, torch.arange(probs.shape[1]), predicted_ids[0]].mean())

            # Check confidence threshold
            if confidence < self.confidence_threshold:
                logger.warning(
                    f"Transcription confidence {confidence:.2f} below threshold "
                    f"{self.confidence_threshold}, skipping"
                )
                raise TranscriptionError(
                    f"Confidence {confidence:.2f} below threshold {self.confidence_threshold}"
                )

            return TranscriptionResult(
                text=transcription,
                confidence=confidence,
                duration=duration,
            )

        except TranscriptionError:
            raise
        except ImportError as e:
            raise TranscriptionError(f"Required package not available: {e}") from e
        except Exception as e:
            raise TranscriptionError(f"Transcription failed: {e}") from e

    def transcribe_mock(
        self, audio_path: str | Path, mock_text: str = "Mock transcription"
    ) -> TranscriptionResult:
        """Transcribe using mock data (for testing without model).

        Args:
            audio_path: Path to audio file (used for duration calculation)
            mock_text: Text to return

        Returns:
            Mock TranscriptionResult
        """
        audio_path = Path(audio_path)

        if not audio_path.exists():
            raise TranscriptionError(f"Audio file not found: {audio_path}")

        # Estimate duration from file size (rough approximation)
        file_size = audio_path.stat().st_size
        # Assume ~16kbps for compressed audio -> duration in seconds
        duration = file_size / 2000  # Conservative estimate

        return TranscriptionResult(
            text=mock_text,
            confidence=0.95,
            duration=duration,
            language="en",
        )

    def __repr__(self) -> str:
        return (
            f"Transcriber(model={self.model_name}, "
            f"loaded={self._is_loaded}, threshold={self.confidence_threshold})"
        )
