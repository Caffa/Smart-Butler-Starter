#!/usr/bin/env python3
"""
ASR Helper: Audio preprocessing for Parakeet transcription.

Features:
- Volume normalization (ffmpeg loudnorm)
- Format conversion (mono 16kHz PCM WAV)
- VAD-based chunking (Silero VAD)
- Overlap for deduplication

Usage:
    from asr_helper import preprocess_audio, chunk_audio_vad

    # Full preprocessing pipeline
    wav_path = preprocess_audio(input_path)

    # VAD chunking with overlap
    chunks = chunk_audio_vad(wav_path)
    for chunk_path, start_sec, end_sec in chunks:
        transcript = transcribe(chunk_path)
"""

import os

# Fix OpenMP duplicate library error on macOS (PyTorch + other ML libs conflict)
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Generator

import numpy as np
import soundfile as sf

# Try to use rapidfuzz for faster fuzzy matching (10-100x faster than difflib)
# Falls back to difflib.SequenceMatcher if not installed
try:
    from rapidfuzz import fuzz as _rapidfuzz

    _USE_RAPIDFUZZ = True
except ImportError:
    from difflib import SequenceMatcher as _SequenceMatcher

    _USE_RAPIDFUZZ = False

# Add parent directory to path for imports (src.memory, src.types, src.transcript_cleanup)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ==============================================================================
# CONFIGURATION
# ==============================================================================

# Chunking parameters
MIN_CHUNK_DURATION = 3.0  # Minimum chunk length (seconds)
TARGET_CHUNK_DURATION = 13.5  # Ideal chunk length (seconds) - middle of 12-15
MAX_CHUNK_DURATION = 20.0  # Hard cap (seconds)
OVERLAP_DURATION = 0.3  # Overlap between chunks (seconds) - 300ms

# VAD parameters
VAD_THRESHOLD = 0.5  # Speech probability threshold (0.0-1.0)
VAD_MIN_SILENCE_MS = 300  # Minimum silence duration to consider as boundary (ms)
VAD_SPEECH_PAD_MS = 100  # Padding around detected speech (ms)

# When to use VAD-based chunking:
# Only use VAD chunking for audio longer than 4 minutes
CHUNK_THRESHOLD_SECONDS = 240

# Skip smart chunking if VAD segments are already reasonable
# Parakeet-MLX handles segments up to ~90s efficiently on Apple Silicon
SKIP_SMART_CHUNKING_THRESHOLD = (
    90.0  # seconds - pass VAD segments directly if under this
)
# FFmpeg settings
SAMPLE_RATE = 16000
CHANNELS = 1

# Text cleanup settings
OVERLAP_SIMILARITY_THRESHOLD = 0.7  # Fuzzy match threshold for de-dup
OVERLAP_WINDOW_WORDS = 10  # Words to compare at chunk boundaries

# LLM prompt for transcript cleanup (Stage 3)
PROMPT_TRANSCRIPT_CLEANUP = """
Clean up this voice transcript. Rules:
1. Fix punctuation and capitalization
2. Do NOT change wording
3. Do NOT summarize
4. Keep exact words - only fix formatting
Output ONLY the cleaned text.
"""


# ==============================================================================
# TEXT CLEANUP PIPELINE
# ==============================================================================


def mechanical_cleanup(text: str) -> str:
    """
    Stage 1: Mechanical text cleanup using regex.
    Delegates to src.transcript_cleanup for shared logic.
    """
    from src.transcript_cleanup import mechanical_cleanup as _mechanical_cleanup
    return _mechanical_cleanup(text)


# ==============================================================================
# FFMPEG PREPROCESSING
# ==============================================================================


def normalize_volume(input_path: Path, output_path: Path) -> bool:
    """
    Normalize audio volume using ffmpeg's loudnorm filter.

    Uses two-pass loudnorm for accurate normalization:
    - Target integrated loudness: -16 LUFS (good for speech)
    - True peak: -1.5 dBTP

    Args:
        input_path: Input audio file
        output_path: Output normalized audio file

    Returns:
        True on success, False on failure
    """
    try:
        # Single-pass loudnorm (faster, slightly less accurate but fine for speech)
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(input_path),
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                str(CHANNELS),
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Volume normalization error: {e}")
        return False


def convert_to_wav(input_path: Path, output_path: Path) -> bool:
    """
    Convert audio to mono 16kHz PCM WAV format for parakeet.

    Args:
        input_path: Input audio file (any format ffmpeg supports)
        output_path: Output WAV file

    Returns:
        True on success, False on failure
    """
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(input_path),
                "-ac",
                str(CHANNELS),
                "-ar",
                str(SAMPLE_RATE),
                "-c:a",
                "pcm_s16le",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"WAV conversion error: {e}")
        return False


def preprocess_audio(
    input_path: Path | str,
    output_path: Path | str | None = None,
    normalize: bool = True,
) -> Path | None:
    """
    Full preprocessing pipeline: normalize + convert to clean WAV.

    Args:
        input_path: Input audio file
        output_path: Output path (optional, creates temp file if not provided)
        normalize: Whether to apply volume normalization

    Returns:
        Path to preprocessed WAV file, or None on failure
    """
    input_path = Path(input_path)

    if output_path is None:
        output_path = input_path.with_suffix(".clean.wav")
    else:
        output_path = Path(output_path)

    if normalize:
        # Normalize volume (also converts to WAV)
        if not normalize_volume(input_path, output_path):
            print(
                "Warning: Volume normalization failed, falling back to simple conversion"
            )
            if not convert_to_wav(input_path, output_path):
                return None
    else:
        # Just convert to WAV
        if not convert_to_wav(input_path, output_path):
            return None

    return output_path if output_path.exists() else None


# ==============================================================================
# VAD-BASED CHUNKING (SILERO VAD)
# ==============================================================================


def _load_silero_vad():
    """
    Load Silero VAD model.

    Returns:
        Tuple of (model, get_speech_timestamps, read_audio)
    """
    try:
        import torch
        from silero_vad import get_speech_timestamps, load_silero_vad, read_audio

        torch.set_num_threads(1)  # Silero VAD is lightweight, single thread is fine

        model = load_silero_vad()
        return model, get_speech_timestamps, read_audio
    except ImportError:
        raise ImportError(
            "Silero VAD requires silero-vad package. Install with: pip install silero-vad"
        )
    except Exception as e:
        raise RuntimeError(f"Failed to load Silero VAD: {e}") from e


def get_speech_segments(
    wav_path: Path | str,
    threshold: float = VAD_THRESHOLD,
    min_silence_ms: int = VAD_MIN_SILENCE_MS,
    speech_pad_ms: int = VAD_SPEECH_PAD_MS,
    return_audio: bool = False,
) -> list[dict] | tuple[list[dict], np.ndarray]:
    """
    Detect speech segments in audio using Silero VAD.

    Args:
        wav_path: Path to WAV file (must be 16kHz mono)
        threshold: Speech probability threshold (0.0-1.0)
        min_silence_ms: Minimum silence duration to split on
        speech_pad_ms: Padding around detected speech
        return_audio: If True, also return audio data as numpy array (avoids reloading)

    Returns:
        List of dicts with 'start' and 'end' keys (in samples at 16kHz)
        If return_audio=True, returns tuple of (segments, audio_numpy_array)
    """
    try:
        print("  Loading Silero VAD model...")
        model, get_speech_timestamps, read_audio = _load_silero_vad()
        print("  Silero VAD model loaded successfully")
    except Exception as e:
        print(f"  Error loading Silero VAD: {e}")
        raise RuntimeError(f"Failed to load Silero VAD model: {e}") from e

    try:
        print(f"  Reading audio file: {wav_path}")
        wav = read_audio(str(wav_path), sampling_rate=SAMPLE_RATE)
        print(f"  Audio loaded: {len(wav)} samples ({len(wav) / SAMPLE_RATE:.1f}s)")
    except Exception as e:
        print(f"  Error reading audio file: {e}")
        raise RuntimeError(f"Failed to read audio file {wav_path}: {e}") from e

    try:
        print("  Running VAD inference...")
        speech_timestamps = get_speech_timestamps(
            wav,
            model,
            threshold=threshold,
            sampling_rate=SAMPLE_RATE,
            min_silence_duration_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
        )
        print(f"  VAD inference complete: {len(speech_timestamps)} segments")

        if return_audio:
            # Convert torch tensor to numpy for downstream use (avoids reloading)
            wav_numpy = wav.numpy()
            return speech_timestamps, wav_numpy
        return speech_timestamps
    except Exception as e:
        print(f"  Error during VAD inference: {e}")
        raise RuntimeError(f"VAD inference failed: {e}") from e


def _samples_to_seconds(samples: int) -> float:
    """Convert samples to seconds at 16kHz."""
    return samples / SAMPLE_RATE


def _seconds_to_samples(seconds: float) -> int:
    """Convert seconds to samples at 16kHz."""
    return int(seconds * SAMPLE_RATE)


def _emit_chunk_with_force_split(
    chunks: list,
    start: float,
    end: float,
    target_duration: float,
    max_duration: float,
    overlap: float,
) -> None:
    """
    Emit a chunk, force-splitting if it exceeds max_duration.
    Modifies chunks list in-place.
    """
    duration = end - start
    if duration <= max_duration:
        chunks.append((start, end))
    else:
        # Force split into smaller chunks
        pos = start
        while pos < end:
            chunk_end = min(pos + target_duration, end)
            chunks.append((pos, chunk_end))
            if chunk_end >= end:
                break  # Reached the end, stop creating chunks
            pos = chunk_end - overlap if overlap > 0 else chunk_end


def create_smart_chunks(
    speech_segments: list[dict],
    audio_duration_sec: float,
    min_duration: float = MIN_CHUNK_DURATION,
    target_duration: float = TARGET_CHUNK_DURATION,
    max_duration: float = MAX_CHUNK_DURATION,
    overlap: float = OVERLAP_DURATION,
) -> list[tuple[float, float]]:
    """
    Create intelligent chunks from speech segments.

    Strategy:
    1. Merge adjacent speech segments into chunks
    2. Split at silence boundaries when approaching target duration
    3. Force split if chunk exceeds max duration (handled inline)
    4. Add overlap between chunks for deduplication

    Optimized with NumPy vectorization and single-pass algorithm.

    Args:
        speech_segments: List of {'start': samples, 'end': samples} from VAD
        audio_duration_sec: Total audio duration in seconds
        min_duration: Minimum chunk duration
        target_duration: Target chunk duration
        max_duration: Maximum chunk duration (hard cap)
        overlap: Overlap duration between chunks

    Returns:
        List of (start_sec, end_sec) tuples
    """
    if not speech_segments:
        # No speech detected, return single chunk of entire audio
        return [(0.0, audio_duration_sec)]

    # NumPy vectorized conversion from samples to seconds
    starts = (
        np.array([s["start"] for s in speech_segments], dtype=np.float64) / SAMPLE_RATE
    )
    ends = np.array([s["end"] for s in speech_segments], dtype=np.float64) / SAMPLE_RATE

    # Pre-compute gaps between segments (vectorized)
    gaps = np.empty(len(starts), dtype=np.float64)
    gaps[0] = 0.0  # No gap before first segment
    gaps[1:] = starts[1:] - ends[:-1]

    chunks = []
    current_start = max(0.0, starts[0] - 0.1)  # Small padding before first speech
    current_end = ends[0]

    # Single-pass: merge segments and emit chunks with force-split inline
    for i in range(1, len(starts)):
        seg_start = starts[i]
        seg_end = ends[i]
        gap = gaps[i]
        current_duration = current_end - current_start
        chunk_duration_if_extended = seg_end - current_start

        # Decision: extend current chunk or start new one?
        should_split = (
            # Case 1: Current chunk at/exceeding target with silence gap
            (current_duration >= target_duration and gap > 0.1)
            or
            # Case 2: Adding segment would exceed max duration
            (chunk_duration_if_extended > max_duration)
            or
            # Case 3: Large silence gap (natural boundary)
            (gap > 1.0 and current_duration >= min_duration)
        )

        if should_split:
            # Emit current chunk (with force-split if needed)
            if current_duration >= min_duration:
                _emit_chunk_with_force_split(
                    chunks,
                    current_start,
                    current_end,
                    target_duration,
                    max_duration,
                    overlap,
                )

            # Start new chunk (with overlap from previous if available)
            if chunks and overlap > 0:
                current_start = max(0.0, current_end - overlap)
            else:
                current_start = max(0.0, seg_start - 0.1)

        current_end = seg_end

    # Handle final chunk
    final_end = min(current_end + 0.1, audio_duration_sec)
    final_duration = final_end - current_start

    if final_duration >= min_duration:
        _emit_chunk_with_force_split(
            chunks, current_start, final_end, target_duration, max_duration, overlap
        )
    elif chunks:
        # Merge tiny last segment with previous chunk
        prev_start, _ = chunks[-1]
        chunks[-1] = (prev_start, final_end)
    else:
        # Only segment is too short, but include it anyway
        chunks.append((current_start, final_end))

    return chunks


def extract_chunk_memory(
    wav_data: np.ndarray,
    sample_rate: int,
    start_sec: float,
    end_sec: float,
    output_path: Path,
) -> bool:
    """
    Extract a chunk using numpy array slicing - no subprocess overhead.

    Args:
        wav_data: Audio data as numpy array (loaded once, sliced many times)
        sample_rate: Sample rate of the audio
        start_sec: Start time in seconds
        end_sec: End time in seconds
        output_path: Output chunk file

    Returns:
        True on success, False on failure
    """
    try:
        start_sample = int(start_sec * sample_rate)
        end_sample = int(end_sec * sample_rate)
        # Clamp to valid range
        start_sample = max(0, start_sample)
        end_sample = min(len(wav_data), end_sample)
        chunk_data = wav_data[start_sample:end_sample]
        sf.write(str(output_path), chunk_data, sample_rate, subtype="PCM_16")
        return True
    except Exception as e:
        print(f"Chunk extraction error: {e}")
        return False


def extract_chunk(
    wav_path: Path,
    start_sec: float,
    end_sec: float,
    output_path: Path,
) -> bool:
    """
    Extract a chunk from a WAV file using ffmpeg (fallback method).

    Args:
        wav_path: Source WAV file
        start_sec: Start time in seconds
        end_sec: End time in seconds
        output_path: Output chunk file

    Returns:
        True on success, False on failure
    """
    duration = end_sec - start_sec
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(wav_path),
                "-ss",
                str(start_sec),
                "-t",
                str(duration),
                "-c:a",
                "pcm_s16le",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0 and output_path.exists()
    except Exception as e:
        print(f"Chunk extraction error: {e}")
        return False


def get_audio_duration(wav_path: Path) -> float:
    """Get audio duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(wav_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return float(result.stdout.strip())
    except Exception:
        # Fallback: estimate from file size (16kHz mono 16-bit = 32000 bytes/sec)
        return wav_path.stat().st_size / 32000


def chunk_audio_vad(
    wav_path: Path | str,
    output_dir: Path | str | None = None,
    min_duration: float = MIN_CHUNK_DURATION,
    target_duration: float = TARGET_CHUNK_DURATION,
    max_duration: float = MAX_CHUNK_DURATION,
    overlap: float = OVERLAP_DURATION,
) -> Generator[tuple[Path, float, float], None, None]:
    """
    Split audio into chunks based on VAD (Voice Activity Detection).

    Chunks are created at natural speech boundaries (silence) with:
    - Minimum duration: 3 seconds
    - Target duration: 12-15 seconds
    - Maximum duration: 20 seconds (hard cap)
    - Overlap: 300ms between chunks for deduplication

    Args:
        wav_path: Path to preprocessed WAV file (16kHz mono)
        output_dir: Directory for chunk files (uses temp dir if None)
        min_duration: Minimum chunk duration
        target_duration: Target chunk duration
        max_duration: Maximum chunk duration
        overlap: Overlap between consecutive chunks

    Yields:
        Tuple of (chunk_path, start_sec, end_sec) for each chunk
    """
    wav_path = Path(wav_path)

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="asr_chunks_"))
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    # Get audio duration
    audio_duration = get_audio_duration(wav_path)

    # Skip VAD chunking for short audio (< 4 minutes)
    if audio_duration < CHUNK_THRESHOLD_SECONDS:
        print(
            f"Audio is {audio_duration:.1f}s (< {CHUNK_THRESHOLD_SECONDS}s), skipping VAD chunking"
        )
        yield wav_path, 0.0, audio_duration
        return

    # Get speech segments from VAD (also returns audio data to avoid reloading)
    print(f"Running VAD on {wav_path.name} ({audio_duration:.1f}s)...")
    speech_segments, wav_data = get_speech_segments(wav_path, return_audio=True)
    print(f"  Found {len(speech_segments)} speech segments")

    # Convert VAD segments to seconds for analysis
    vad_segments_sec = [
        (s["start"] / SAMPLE_RATE, s["end"] / SAMPLE_RATE) for s in speech_segments
    ]

    # Check if VAD segments are already reasonable sizes (skip smart chunking)
    max_vad_duration = (
        max((end - start) for start, end in vad_segments_sec) if vad_segments_sec else 0
    )

    if max_vad_duration <= SKIP_SMART_CHUNKING_THRESHOLD:
        # VAD segments are all under threshold - use them directly
        # This avoids unnecessary ffmpeg extractions for already-reasonable segments
        print(
            f"  VAD segments all under {SKIP_SMART_CHUNKING_THRESHOLD}s (max: {max_vad_duration:.1f}s)"
        )
        print(
            f"  Skipping smart chunking - using {len(vad_segments_sec)} VAD segments directly"
        )

        # Handle empty VAD segments (no speech detected) - return whole audio
        if not vad_segments_sec:
            print("  No speech segments detected, using entire audio")
            chunks = [(0.0, audio_duration)]
        else:
            # Add small padding and create chunks from VAD segments
            chunks = []
            for start, end in vad_segments_sec:
                chunk_start = max(0.0, start - 0.1)
                chunk_end = min(end + 0.1, audio_duration)
                if (chunk_end - chunk_start) >= min_duration:
                    chunks.append((chunk_start, chunk_end))
                elif chunks:
                    # Merge tiny segment with previous
                    prev_start, _ = chunks[-1]
                    chunks[-1] = (prev_start, chunk_end)
                else:
                    # First segment is tiny but include it anyway
                    chunks.append((chunk_start, chunk_end))
    else:
        # Some segments exceed threshold - apply smart chunking
        print(
            f"  Some VAD segments exceed {SKIP_SMART_CHUNKING_THRESHOLD}s (max: {max_vad_duration:.1f}s)"
        )
        print("  Applying smart chunking...")
        t0 = time.perf_counter()
        chunks = create_smart_chunks(
            speech_segments,
            audio_duration,
            min_duration=min_duration,
            target_duration=target_duration,
            max_duration=max_duration,
            overlap=overlap,
        )
        print(f"  create_smart_chunks took {time.perf_counter() - t0:.3f}s")

    print(f"  Created {len(chunks)} chunks")

    # Audio already loaded by VAD - reuse for fast slicing (no subprocess per chunk)
    # Extract each chunk using in-memory slicing
    for i, (start_sec, end_sec) in enumerate(chunks):
        chunk_name = f"{wav_path.stem}_chunk_{i:03d}.wav"
        chunk_path = output_dir / chunk_name

        if extract_chunk_memory(wav_data, SAMPLE_RATE, start_sec, end_sec, chunk_path):
            # print(
            #     f"  Chunk {i + 1}/{len(chunks)}: {start_sec:.1f}s - {end_sec:.1f}s ({end_sec - start_sec:.1f}s)"
            # )
            # silenced the print
            yield chunk_path, start_sec, end_sec
        else:
            print(f"  Warning: Failed to extract chunk {i + 1}")


# ==============================================================================
# TRANSCRIPT DEDUPLICATION (Post-processing)
# ==============================================================================


def _normalize_word(word: str) -> str:
    """Normalize a word for comparison (lowercase, strip punctuation)."""
    return word.lower().strip(".,!?;:'\"()-")


def _word_similarity(words1: list[str], words2: list[str]) -> float:
    """
    Calculate similarity between two word lists.

    Uses rapidfuzz if available (10-100x faster), falls back to difflib.

    Args:
        words1: First list of words
        words2: Second list of words

    Returns:
        Similarity ratio (0.0 to 1.0)
    """
    if not words1 or not words2:
        return 0.0

    # Normalize words for comparison
    norm1 = " ".join(_normalize_word(w) for w in words1)
    norm2 = " ".join(_normalize_word(w) for w in words2)

    if _USE_RAPIDFUZZ:
        # rapidfuzz.fuzz.ratio returns 0-100, normalize to 0-1
        return _rapidfuzz.ratio(norm1, norm2) / 100.0
    else:
        return _SequenceMatcher(None, norm1, norm2).ratio()


def fuzzy_dedup_overlap(
    transcripts: list[tuple[str, float, float]],
    similarity_threshold: float = OVERLAP_SIMILARITY_THRESHOLD,
    window_words: int = OVERLAP_WINDOW_WORDS,
) -> str:
    """
    Stage 2: Merge transcripts from overlapping chunks using fuzzy matching.

    Strategy:
    - Compare last N words of chunk with first N words of next chunk
    - Use fuzzy matching (rapidfuzz if available, else difflib) to handle ASR variations
    - Remove overlap when similarity exceeds threshold

    Args:
        transcripts: List of (text, start_sec, end_sec) tuples
        similarity_threshold: Minimum similarity to consider as overlap (0.0-1.0)
        window_words: Number of words to compare at boundaries

    Returns:
        Merged transcript with duplicates removed
    """
    if not transcripts:
        return ""

    if len(transcripts) == 1:
        return transcripts[0][0]

    def find_fuzzy_overlap(text1: str, text2: str) -> int:
        """
        Find where text2 should start to avoid overlap with text1.
        Uses fuzzy matching to handle ASR variations.

        Returns the word index in text2 where unique content begins.
        """
        words1 = text1.split()
        words2 = text2.split()

        if not words1 or not words2:
            return 0

        # Get the comparison windows
        end_words1 = words1[-window_words:] if len(words1) >= window_words else words1
        start_words2 = words2[:window_words] if len(words2) >= window_words else words2

        best_match_len = 0
        best_similarity = 0.0

        # Try different overlap lengths, looking for best fuzzy match
        max_check = min(len(end_words1), len(start_words2), window_words)

        for overlap_len in range(1, max_check + 1):
            # Compare last N words of text1 with first N words of text2
            end_slice = end_words1[-overlap_len:]
            start_slice = start_words2[:overlap_len]

            similarity = _word_similarity(end_slice, start_slice)

            # Accept if above threshold, prefer longer matches
            if similarity >= similarity_threshold:
                if overlap_len > best_match_len or similarity > best_similarity:
                    best_match_len = overlap_len
                    best_similarity = similarity

        return best_match_len

    # Merge transcripts
    result_words = transcripts[0][0].split()

    for i in range(1, len(transcripts)):
        current_text = transcripts[i][0]
        overlap_idx = find_fuzzy_overlap(
            " ".join(result_words[-window_words * 2 :]),  # Only check recent words
            current_text,
        )

        # Add non-overlapping portion
        new_words = current_text.split()[overlap_idx:]
        result_words.extend(new_words)

    return " ".join(result_words)


# Keep old function name as alias for backwards compatibility
def remove_overlap_duplicates(
    transcripts: list[tuple[str, float, float]],
    overlap_duration: float = OVERLAP_DURATION,
) -> str:
    """
    Legacy alias for fuzzy_dedup_overlap().

    Args:
        transcripts: List of (text, start_sec, end_sec) tuples
        overlap_duration: Ignored (kept for API compatibility)

    Returns:
        Merged transcript with duplicates removed
    """
    return fuzzy_dedup_overlap(transcripts)


# ==============================================================================
# LLM REFINEMENT (Post-processing)
# ==============================================================================


def _get_llm_client():
    """
    Lazy import of LLM client to avoid import errors when LLM not needed.

    Returns:
        Tuple of (call_llm function, MODEL_FAST constant)
    """
    try:
        from src.memory import call_llm
        from src.types import MODEL_FAST

        return call_llm, MODEL_FAST
    except ImportError as e:
        print(f"Warning: Could not import LLM client: {e}")
        return None, None


def llm_refine_transcript(
    text: str,
    max_chunk_chars: int = 4000,
) -> str:
    """
    Stage 3: LLM-based transcript refinement.

    Uses a small, fast model (gemma3:4b) to clean up punctuation and
    capitalization while preserving exact wording.

    Args:
        text: Transcript text to refine
        max_chunk_chars: Maximum characters per LLM call (splits if longer)

    Returns:
        Refined transcript, or original text if LLM unavailable
    """
    if not text or not text.strip():
        return text

    call_llm, model = _get_llm_client()
    if call_llm is None:
        print("Warning: LLM not available, skipping refinement")
        return text

    # For short texts, process in one call
    if len(text) <= max_chunk_chars:
        try:
            result = call_llm(PROMPT_TRANSCRIPT_CLEANUP, text, model)
            return result.strip() if result else text
        except Exception as e:
            print(f"Warning: LLM refinement failed: {e}")
            return text

    # For long texts, split by sentences and process in chunks
    # Simple sentence splitting (could be improved)
    sentences = re.split(r"(?<=[.!?])\s+", text)

    chunks = []
    current_chunk = []
    current_len = 0

    for sentence in sentences:
        if current_len + len(sentence) > max_chunk_chars and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = [sentence]
            current_len = len(sentence)
        else:
            current_chunk.append(sentence)
            current_len += len(sentence) + 1

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    # Process each chunk
    refined_chunks = []
    for i, chunk in enumerate(chunks):
        try:
            result = call_llm(PROMPT_TRANSCRIPT_CLEANUP, chunk, model)
            refined_chunks.append(result.strip() if result else chunk)
        except Exception as e:
            print(f"Warning: LLM refinement failed for chunk {i + 1}: {e}")
            refined_chunks.append(chunk)

    return " ".join(refined_chunks)


# ==============================================================================
# CONVENIENCE FUNCTIONS
# ==============================================================================


def process_and_chunk(
    input_path: Path | str,
    output_dir: Path | str | None = None,
    normalize: bool = True,
) -> Generator[tuple[Path, float, float], None, None]:
    """
    Full pipeline: preprocess audio and split into VAD-based chunks.

    Args:
        input_path: Input audio file (any format)
        output_dir: Directory for output files
        normalize: Whether to apply volume normalization

    Yields:
        Tuple of (chunk_path, start_sec, end_sec) for each chunk
    """
    input_path = Path(input_path)

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="asr_"))
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    # Preprocess
    clean_wav = output_dir / f"{input_path.stem}.clean.wav"
    print(f"Preprocessing {input_path.name}...")

    result = preprocess_audio(input_path, clean_wav, normalize=normalize)
    if result is None:
        raise RuntimeError(f"Failed to preprocess {input_path}")

    # Chunk
    yield from chunk_audio_vad(clean_wav, output_dir)


def cleanup_transcript_pipeline(
    transcripts: list[tuple[str, float, float]],
    use_llm: bool = True,
) -> str:
    """
    Full 3-stage text cleanup pipeline for ASR transcripts.

    Pipeline stages:
    1. Mechanical cleanup: regex-based removal of fillers, stutters, whitespace
    2. Fuzzy de-dup: merge overlapping chunks using fuzzy matching
    3. LLM refinement: fix punctuation/capitalization (optional)

    Args:
        transcripts: List of (text, start_sec, end_sec) tuples from ASR
        use_llm: Whether to apply LLM refinement (Stage 3)

    Returns:
        Cleaned and merged transcript
    """
    if not transcripts:
        return ""

    # Stage 1: Dictionary replacements + mechanical cleanup on each chunk
    print("Stage 1: Dictionary + mechanical cleanup...")
    from src.transcript_cleanup import apply_transcription_dictionary
    cleaned_transcripts = [
        (
            mechanical_cleanup(apply_transcription_dictionary(text)),
            start,
            end,
        )
        for text, start, end in transcripts
    ]

    # Stage 2: Fuzzy de-dup overlap stitching
    print("Stage 2: De-dup overlap stitching...")
    merged = fuzzy_dedup_overlap(cleaned_transcripts)

    # Stage 3: LLM refinement (optional)
    if use_llm:
        print("Stage 3: LLM refinement...")
        merged = llm_refine_transcript(merged)
    else:
        print("Stage 3: Skipped (use_llm=False)")

    return merged


# ==============================================================================
# EXAMPLE USAGE
# ==============================================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python asr-helper.py <audio_file> [--no-llm]")
        print()
        print("Example:")
        print("  python asr-helper.py recording.m4a")
        print("  python asr-helper.py recording.m4a --no-llm")
        print()
        print("This will:")
        print("  1. Normalize volume")
        print("  2. Convert to 16kHz mono WAV")
        print("  3. Split into VAD-based chunks (3-20s each)")
        print("  4. Save chunks to a temp directory")
        print()
        print("Text cleanup pipeline (for transcripts):")
        print("  Stage 1: Mechanical cleanup (fillers, stutters, whitespace)")
        print("  Stage 2: Fuzzy de-dup overlap stitching")
        print("  Stage 3: LLM refinement (punctuation, capitalization)")
        sys.exit(1)

    input_file = Path(sys.argv[1])
    use_llm = "--no-llm" not in sys.argv

    if not input_file.exists():
        print(f"Error: File not found: {input_file}")
        sys.exit(1)

    print(f"Processing: {input_file}")
    print("-" * 50)

    chunks = list(process_and_chunk(input_file))

    print("-" * 50)
    print(f"Created {len(chunks)} chunks:")
    for chunk_path, start, end in chunks:
        print(f"  {chunk_path.name}: {start:.1f}s - {end:.1f}s ({end - start:.1f}s)")

    print()
    print("Chunks saved to:", chunks[0][0].parent if chunks else "N/A")

    # Demo: Show how to use the text cleanup pipeline
    print()
    print("-" * 50)
    print("TEXT CLEANUP PIPELINE DEMO")
    print("-" * 50)
    print()
    print("After transcribing chunks, use cleanup_transcript_pipeline():")
    print()
    print("  # Example with mock transcripts:")
    print("  transcripts = [")
    print('      ("Um, I think we should go ahead", 0.0, 5.0),')
    print('      ("we should go ahead and, uh, start the project", 4.7, 10.0),')
    print("  ]")
    print(f"  cleaned = cleanup_transcript_pipeline(transcripts, use_llm={use_llm})")
    print()

    # Actually run the demo with mock data
    demo_transcripts = [
        ("Um, I think we should go ahead", 0.0, 5.0),
        ("we should go ahead and, uh, start the project", 4.7, 10.0),
    ]
    print("Running demo...")
    cleaned_demo = cleanup_transcript_pipeline(demo_transcripts, use_llm=use_llm)
    print(f"Result: {cleaned_demo}")
