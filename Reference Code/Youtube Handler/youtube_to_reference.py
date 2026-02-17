#!/usr/bin/env python3
"""
YouTube to Obsidian Reference Note
Triggered by Alfred workflow with YouTube URL as argument.

Foreground: Download audio, transcribe via parakeet_mlx with VAD-based chunking
Background (queued): LLM processing for cleanup + summary, then write Reference Note

Audio Pipeline:
1. Download audio via yt-dlp
2. Preprocess: volume normalization + convert to 16kHz mono WAV
3. VAD chunking: split at speech boundaries (Silero VAD)
4. Transcribe each chunk via parakeet_mlx (MLX - Apple Silicon optimized)
5. Merge transcripts with fuzzy overlap deduplication
"""

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Import ASR helper for preprocessing and VAD chunking
from asr_helper import (
    chunk_audio_vad,
    fuzzy_dedup_overlap,
    get_audio_duration,
    mechanical_cleanup,
    preprocess_audio,
)
from src.transcript_cleanup import apply_transcription_dictionary
from src.memory import log_debug, log_run_start
from src import workflow_status


# ==============================================================================
# TEXT SANITIZATION
# ==============================================================================


def light_sanitize_text(text: str) -> str:
    """Light sanitization for display/logging - normalize quotes, strip control chars."""
    if not text:
        return text
    # Normalize smart quotes/apostrophes to ASCII
    replacements = {
        '\u2018': "'", '\u2019': "'",  # curly single quotes
        '\u201C': '"', '\u201D': '"',  # curly double quotes
        '\u2013': '-', '\u2014': '-',  # en/em dashes
        '\u00A0': ' ',                  # non-breaking space
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Strip control characters (but keep newlines/tabs for now)
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    return text.strip()


# ==============================================================================
# CONFIGURATION
# ==============================================================================

# Staging folders
STAGING_ROOT = Path("/Users/caffae/Automation Folders/Youtube-Transcription")
STAGING_URL_TO_WAV = STAGING_ROOT / "1-Url-to-Wav"
STAGING_WAV_TO_TEXT = STAGING_ROOT / "2-Wav-to-Text"
STAGING_CHUNKS = STAGING_ROOT / "3-Chunks"  # Temp folder for VAD chunks

# Cache configuration
CACHE_DIR = STAGING_ROOT / "wav-cache"
CACHE_MAX_AGE_DAYS = 2

# Output folder
REFERENCE_NOTES_DIR = Path(
    "/Users/caffae/Notes/ZettelPublish (Content Creator V2 April 2025)/02 Reference Notes"
)

# Parakeet model (MLX - Apple Silicon optimized, NOT torch/MPS)
PARAKEET_MODEL_ID = "mlx-community/parakeet-tdt-0.6b-v2"


# ==============================================================================
# LOGGING HELPERS
# ==============================================================================


def log_youtube(message: str):
    """Log with [YouTube] prefix for filtering."""
    log_debug(f"[YouTube] {message}")


def notify_user(title: str, message: str):
    """Show macOS notification."""
    # Escape special characters for AppleScript string literals
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")
    safe_message = message.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")
    subprocess.run(
        [
            "osascript",
            "-e",
            f'display notification "{safe_message}" with title "{safe_title}"',
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ==============================================================================
# URL VALIDATION
# ==============================================================================


def validate_youtube_url(url: str) -> str | None:
    """Check if URL looks like a YouTube video URL. Returns extracted URL or None.

    Supports:
    - Direct URLs: https://www.youtube.com/watch?v=...
    - Short URLs: https://youtu.be/...
    - Shorts: https://www.youtube.com/shorts/...
    - Wiki links: [Title - YouTube](https://www.youtube.com/watch?v=...)
    """
    # Extract URL from wiki link format: [Title](url)
    wiki_match = re.search(r"\[.*?\]\((https?://[^\)]+)\)", url)
    if wiki_match:
        url = wiki_match.group(1)

    patterns = [
        r"^https?://(www\.)?youtube\.com/watch\?v=[\w-]+",
        r"^https?://youtu\.be/[\w-]+",
        r"^https?://(www\.)?youtube\.com/shorts/[\w-]+",
    ]
    return url if any(re.match(p, url) for p in patterns) else None


# ==============================================================================
# CACHE MANAGEMENT
# ==============================================================================


def cleanup_cache():
    """Remove cached WAV and transcript files older than CACHE_MAX_AGE_DAYS."""
    if not CACHE_DIR.exists():
        return

    cutoff = time.time() - (CACHE_MAX_AGE_DAYS * 24 * 60 * 60)
    removed_count = 0
    for cached_file in CACHE_DIR.glob("*"):
        if (
            cached_file.suffix in (".wav", ".txt")
            and cached_file.stat().st_mtime < cutoff
        ):
            cached_file.unlink()
            log_youtube(f"Cache cleanup: removed {cached_file.name}")
            removed_count += 1

    if removed_count > 0:
        log_youtube(f"Cache cleanup: removed {removed_count} expired file(s)")


def get_cached_wav(video_id: str) -> tuple[Path, float] | None:
    """Check if preprocessed WAV exists in cache.

    Returns:
        Tuple of (wav_path, duration_sec) on cache hit, None on miss.
    """
    cached_path = CACHE_DIR / f"{video_id}.wav"
    if cached_path.exists():
        # Refresh mtime to extend cache life on re-use
        cached_path.touch()
        duration_sec = get_audio_duration(cached_path)
        log_youtube(f"Cache HIT: {video_id}.wav ({duration_sec / 60:.1f} min)")
        return cached_path, duration_sec
    return None


def cache_wav(wav_path: Path, video_id: str) -> Path:
    """Move WAV to cache directory.

    Args:
        wav_path: Path to the preprocessed WAV file.
        video_id: YouTube video ID (used as cache key).

    Returns:
        Path to the cached WAV file.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached_path = CACHE_DIR / f"{video_id}.wav"
    shutil.copy2(wav_path, cached_path)  # copy2 preserves metadata
    wav_path.unlink()  # remove original from staging
    log_youtube(f"Cached: {video_id}.wav")
    return cached_path


def get_cached_transcript(video_id: str) -> str | None:
    """Check if transcript exists in cache.

    If transcript exists AND a WAV file exists, delete the WAV file.

    Returns:
        Transcript text on cache hit, None on miss.
    """
    cached_path = CACHE_DIR / f"{video_id}.txt"
    if cached_path.exists():
        # Clean up WAV file if it still exists
        wav_path = CACHE_DIR / f"{video_id}.wav"
        if wav_path.exists():
            wav_path.unlink()
            log_youtube(f"Cache cleanup: removed {video_id}.wav (transcript exists)")

        cached_path.touch()  # Refresh mtime
        transcript = cached_path.read_text()
        log_youtube(f"Cache HIT: {video_id}.txt ({len(transcript)} chars)")
        return transcript
    return None


def cache_transcript(transcript: str, video_id: str):
    """Save transcript to cache and delete WAV file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached_path = CACHE_DIR / f"{video_id}.txt"
    cached_path.write_text(transcript)

    # Delete WAV file since we have the transcript
    wav_path = CACHE_DIR / f"{video_id}.wav"
    if wav_path.exists():
        wav_path.unlink()
        log_youtube(f"Cleaned up: {video_id}.wav (transcript cached)")

    log_youtube(f"Cached: {video_id}.txt")


# ==============================================================================
# YT-DLP: DOWNLOAD + METADATA
# ==============================================================================


def extract_metadata(url: str) -> dict:
    """Extract uploader and title from YouTube URL."""
    log_youtube("Fetching video metadata...")
    try:
        # Use ||| as delimiter since | can appear in uploader names
        result = subprocess.run(
            ["yt-dlp", "--print", "%(uploader)s|||%(title)s|||%(id)s", url],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            log_youtube(f"❌ yt-dlp metadata failed: {result.stderr}")
            return None

        parts = result.stdout.strip().split("|||")
        if len(parts) >= 3:
            metadata = {
                "uploader": parts[0],
                "title": parts[1],
                "video_id": parts[2],
            }
            log_youtube(f"Metadata: {metadata['uploader']} - {metadata['title']}")
            return metadata
        return None
    except subprocess.TimeoutExpired:
        log_youtube("❌ yt-dlp metadata timed out after 60s")
        return None
    except Exception as e:
        log_youtube(f"❌ yt-dlp metadata error: {e}")
        return None


def download_audio(url: str, video_id: str, title: str) -> Path:
    """Download audio as mp3 to staging folder."""
    output_template = str(STAGING_URL_TO_WAV / f"{video_id}.%(ext)s")
    log_youtube(f"Downloading audio for: {title[:60]}...")

    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "-x",
                "--audio-format",
                "mp3",
                "-o",
                output_template,
                url,
            ],
            capture_output=True,
            text=True,
            timeout=600,  # 10 minutes max
        )
        if result.returncode != 0:
            log_youtube(f"❌ yt-dlp download failed: {result.stderr}")
            return None

        # Find the downloaded file
        mp3_path = STAGING_URL_TO_WAV / f"{video_id}.mp3"
        if mp3_path.exists():
            log_youtube(
                f"Download complete: {mp3_path.name} ({mp3_path.stat().st_size / 1024 / 1024:.1f} MB)"
            )
            return mp3_path

        # Sometimes extension varies
        for ext in [".mp3", ".m4a", ".webm", ".opus"]:
            p = STAGING_URL_TO_WAV / f"{video_id}{ext}"
            if p.exists():
                log_youtube(
                    f"Download complete: {p.name} ({p.stat().st_size / 1024 / 1024:.1f} MB)"
                )
                return p

        log_youtube(f"❌ Downloaded file not found for {video_id}")
        return None
    except subprocess.TimeoutExpired:
        log_youtube("❌ yt-dlp download timed out after 600s")
        return None
    except Exception as e:
        log_youtube(f"❌ yt-dlp download error: {e}")
        return None


# ==============================================================================
# AUDIO PREPROCESSING (Volume Normalization + WAV Conversion)
# ==============================================================================


def preprocess_audio_for_transcription(
    input_path: Path, video_id: str
) -> tuple[Path, float] | None:
    """Preprocess audio: volume normalization + convert to 16kHz mono WAV.

    Uses asr_helper.preprocess_audio for:
    - Volume normalization (ffmpeg loudnorm: -16 LUFS)
    - Format conversion (mono 16kHz PCM WAV)

    After preprocessing, the WAV is moved to the cache directory.

    Returns:
        Tuple of (cached_wav_path, duration_sec) on success, None on failure.
    """
    wav_path = STAGING_WAV_TO_TEXT / f"{video_id}.wav"
    log_youtube(f"Preprocessing audio: {input_path.name}...")
    log_youtube("  - Volume normalization (loudnorm -16 LUFS)")
    log_youtube("  - Converting to 16kHz mono WAV")

    try:
        # Use asr_helper preprocessing (volume norm + WAV conversion)
        result = preprocess_audio(input_path, wav_path, normalize=True)

        # Cleanup original file
        input_path.unlink(missing_ok=True)

        if result and wav_path.exists():
            duration_sec = get_audio_duration(wav_path)
            log_youtube(
                f"Preprocessing complete: {wav_path.name} (~{duration_sec / 60:.1f} min)"
            )
            # Move to cache for reuse
            cached_path = cache_wav(wav_path, video_id)
            return cached_path, duration_sec
        log_youtube("❌ Preprocessing failed - WAV file not created")
        return None
    except Exception as e:
        log_youtube(f"❌ Preprocessing error: {e}")
        return None


# ==============================================================================
# PARAKEET: TRANSCRIBE WITH VAD-BASED CHUNKING
# ==============================================================================

# Use miniforge3 Python where parakeet_mlx is installed
# Note: parakeet_mlx uses MLX (Apple Silicon framework), NOT PyTorch/MPS
# MINIFORGE_PYTHON = "/Users/caffae/miniforge3/bin/python"
MINIFORGE_PYTHON = "/opt/homebrew/opt/python@3.10/bin/python3.10"


def transcribe_audio(wav_path: Path, duration_sec: float) -> str:
    """Transcribe WAV file using VAD-based chunking + parakeet_mlx.

    Pipeline:
    1. VAD chunking: Split audio at speech boundaries (Silero VAD)
       - Target chunk duration: 12-15s (optimal for ASR accuracy)
       - Min: 3s, Max: 20s
       - 300ms overlap for deduplication
    2. Transcribe each chunk via parakeet_mlx (MLX - Apple Silicon)
    3. Merge transcripts with fuzzy overlap deduplication

    Args:
        wav_path: Path to the preprocessed WAV file (16kHz mono).
        duration_sec: Duration of the audio in seconds.

    Returns:
        Full transcript, or None on failure.
    """
    log_youtube(f"🎤 Starting transcription: {wav_path.name}")
    log_youtube(f"  Model: {PARAKEET_MODEL_ID} (MLX - Apple Silicon)")
    log_youtube(f"  Audio duration: {duration_sec / 60:.1f} min")

    # Create temp directory for chunks
    STAGING_CHUNKS.mkdir(parents=True, exist_ok=True)
    chunk_dir = STAGING_CHUNKS / wav_path.stem
    chunk_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Step 1: VAD-based chunking
        log_youtube("Step 1: VAD chunking (Silero VAD)...")
        log_youtube("  Target chunk: 12-15s (min 3s, max 20s)")
        log_youtube("  Overlap: 300ms for deduplication")

        try:
            chunks = list(chunk_audio_vad(wav_path, output_dir=chunk_dir))
        except Exception as vad_error:
            print(f"VAD chunking error: {vad_error}")
            log_youtube(f"❌ VAD chunking exception: {vad_error}")
            import traceback

            log_youtube(f"  VAD traceback: {traceback.format_exc()}")
            return None

        if not chunks:
            print("VAD chunking produced no audio chunks")
            log_youtube("❌ VAD chunking produced no chunks")
            return None

        log_youtube(f"  Created {len(chunks)} chunks")
        print(f"Created {len(chunks)} audio chunks for transcription")

        # Step 2: Transcribe each chunk
        log_youtube(f"Step 2: Transcribing {len(chunks)} chunks...")

        # Load model once via subprocess that handles all chunks
        # This is more efficient than loading model per-chunk
        chunk_paths_str = "|".join(str(c[0]) for c in chunks)
        script = f'''
import sys
from parakeet_mlx import from_pretrained

print("Loading model...", file=sys.stderr, flush=True)
model = from_pretrained("{PARAKEET_MODEL_ID}")

chunk_paths = "{chunk_paths_str}".split("|")
print(f"Transcribing {{len(chunk_paths)}} chunks...", file=sys.stderr, flush=True)

results = []
for i, path in enumerate(chunk_paths):
    try:
        result = model.transcribe(path)
        text = result.text.strip() if result.text else ""
        results.append(text)
        # print(f"  Chunk {{i+1}}/{{len(chunk_paths)}} done", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"  Chunk {{i+1}} failed: {{e}}", file=sys.stderr, flush=True)
        results.append("")

# Output results separated by special delimiter
print("|||CHUNK_SEP|||".join(results))
'''
        log_youtube("  Loading model and transcribing all chunks...")

        result = subprocess.run(
            [MINIFORGE_PYTHON, "-c", script],
            capture_output=True,
            text=True,
            timeout=1800,  # 30 min max
        )

        # Log stderr for debugging (visible in terminal)
        if result.stderr:
            for line in result.stderr.strip().split("\n"):
                if line.strip():
                    print(f"  [parakeet] {line.strip()}")
                    log_youtube(f"  [parakeet] {line.strip()}")

        if result.returncode != 0:
            print(f"❌ Transcription subprocess failed (exit code {result.returncode})")
            log_youtube(f"❌ Transcription failed (exit code {result.returncode})")
            return None

        # Parse chunk transcripts
        chunk_texts = result.stdout.strip().split("|||CHUNK_SEP|||")
        if len(chunk_texts) != len(chunks):
            log_youtube(f"⚠️ Chunk count mismatch: {len(chunk_texts)} vs {len(chunks)}")

        # Build transcript tuples with timestamps
        transcripts = []
        for i, (chunk_path, start_sec, end_sec) in enumerate(chunks):
            text = chunk_texts[i] if i < len(chunk_texts) else ""
            if text:
                transcripts.append((text, start_sec, end_sec))
            # Clean up chunk file
            chunk_path.unlink(missing_ok=True)

        if not transcripts:
            print("❌ No transcripts produced from chunks")
            log_youtube("❌ No transcripts produced")
            return None

        log_youtube(
            f"  Transcribed {len(transcripts)}/{len(chunks)} chunks successfully"
        )

        # Step 3: Merge with cleanup pipeline
        log_youtube("Step 3: Merging transcripts...")
        log_youtube("  - Mechanical cleanup (fillers, stutters)")
        log_youtube("  - Fuzzy overlap deduplication")

        # Use cleanup pipeline (stages 1 & 2 only - skip LLM refinement here,
        # since we'll do LLM processing in the background task)
        cleaned_transcripts = [
            (
                mechanical_cleanup(apply_transcription_dictionary(text)),
                start,
                end,
            )
            for text, start, end in transcripts
        ]
        transcript = fuzzy_dedup_overlap(cleaned_transcripts)

        log_youtube(f"Transcription complete: {len(transcript)} chars")

        # Cleanup chunk directory (WAV is cached, not deleted)
        try:
            chunk_dir.rmdir()  # Remove empty chunk dir
        except OSError:
            pass  # Directory not empty, that's fine
        log_youtube("  Chunk files cleaned up")

        return transcript

    except subprocess.TimeoutExpired:
        log_youtube("❌ Transcription timed out after 1800s (30 min)")
        return None
    except Exception as e:
        log_youtube(f"❌ Transcription error: {e}")
        import traceback

        log_youtube(f"  Traceback: {traceback.format_exc()}")
        return None


# ==============================================================================
# MAIN
# ==============================================================================


def main():
    """Main entry point for Alfred workflow."""
    title = None  # Track for error notifications

    # expected usage:
    # /opt/homebrew/opt/python@3.10/bin/python3.10 youtube_to_reference.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    # Check arguments
    if len(sys.argv) < 2:
        print("Error: No YouTube URL provided")
        log_youtube("❌ FAILED: No URL provided")
        notify_user("❌ YouTube Error", "No URL provided")
        sys.exit(1)

    raw_input = sys.argv[1].strip()

    # Log run start with proper border format
    log_run_start(f"YouTube Transcription | Input: {raw_input[:60]}...")

    # Validate and extract URL (handles wiki links like [Title](url))
    url = validate_youtube_url(raw_input)
    if not url:
        print("Error: Invalid YouTube URL")
        log_youtube(f"❌ Invalid URL format: {raw_input}")
        notify_user("❌ YouTube Error", "Invalid YouTube URL format")
        sys.exit(1)

    log_youtube(f"Extracted URL: {url}")

    wid = workflow_status.workflow_start("youtube", label=raw_input[:50])
    try:
        # Ensure staging folders exist
        STAGING_URL_TO_WAV.mkdir(parents=True, exist_ok=True)
        STAGING_WAV_TO_TEXT.mkdir(parents=True, exist_ok=True)

        # Cleanup expired cache entries
        cleanup_cache()

        # Step 1: Extract metadata
        workflow_status.workflow_step(wid, "Fetching metadata")
        print("Fetching video info...")
        metadata = extract_metadata(url)
        if not metadata:
            workflow_status.workflow_end(wid, success=False, summary="Metadata fetch failed")
            print("Error: Could not fetch video metadata")
            log_youtube(f"❌ FAILED: Could not fetch metadata for {url[:50]}")
            notify_user("❌ YouTube Error", "Could not fetch video metadata")
            sys.exit(1)

        uploader = light_sanitize_text(metadata["uploader"])
        title = light_sanitize_text(metadata["title"])
        video_id = metadata["video_id"]  # video_id is safe (alphanumeric)

        # Step 2: Check cache for transcript first (skips all audio processing)
        cached_transcript = get_cached_transcript(video_id)
        if cached_transcript:
            print("Using cached transcript (skipping audio processing)...")
            transcript = cached_transcript
        else:
            # Step 2a: Check cache for preprocessed WAV
            cached = get_cached_wav(video_id)
            if cached:
                print("Using cached audio (skipping download)...")
                wav_path, duration_sec = cached
            else:
                # Step 2b: Download audio
                workflow_status.workflow_step(wid, "Downloading audio")
                print("Downloading audio...")
                audio_path = download_audio(url, video_id, title)
                if not audio_path:
                    workflow_status.workflow_end(wid, success=False, summary="Download failed")
                    print("Error: Download failed")
                    log_youtube(f"❌ FAILED: Download failed - {title[:50]}")
                    notify_user("❌ YouTube Error", f"Download failed: {title[:40]}...")
                    sys.exit(1)

                # Step 2c: Preprocess audio (volume norm + WAV conversion + cache)
                print("Preprocessing audio...")
                wav_result = preprocess_audio_for_transcription(audio_path, video_id)
                if not wav_result:
                    workflow_status.workflow_end(wid, success=False, summary="Preprocess failed")
                    print("Error: Audio preprocessing failed")
                    log_youtube(f"❌ FAILED: Audio preprocessing - {title[:50]}")
                    notify_user(
                        "❌ YouTube Error", f"Preprocessing failed: {title[:40]}..."
                    )
                    sys.exit(1)
                wav_path, duration_sec = wav_result

            # Step 3: Transcribe with VAD-based chunking
            workflow_status.workflow_step(wid, "Transcribing")
            print("Transcribing audio with VAD chunking (this may take several minutes)...")
            transcript = transcribe_audio(wav_path, duration_sec)
            if not transcript:
                workflow_status.workflow_end(wid, success=False, summary="Transcription failed")
                print("Error: Transcription failed or empty")
                log_youtube(f"❌ FAILED: Transcription failed - {title[:50]}")
                notify_user("❌ YouTube Error", f"Transcription failed: {title[:40]}...")
                sys.exit(1)

            # Cache the transcript (also cleans up WAV file)
            cache_transcript(transcript, video_id)

        # Step 4: Enqueue LLM processing
        workflow_status.workflow_step(wid, "Queued (AI)")
        print("Queuing AI processing...")
        try:
            from src.task_queue import enqueue_youtube_reference

            enqueue_youtube_reference(transcript, uploader, title, video_id, url)
            log_youtube("Task enqueued for LLM processing")
        except Exception as e:
            workflow_status.workflow_end(wid, success=False, summary=f"Queue failed: {e}"[:80])
            log_youtube(f"❌ Enqueue failed: {e}")
            print(f"Error: Could not queue processing: {e}")
            notify_user("❌ YouTube Error", f"Queue failed: {str(e)[:40]}")
            sys.exit(1)

        workflow_status.workflow_end(wid, success=True, summary=f"Queued: {title[:40]}...")
        # Success!
        print("Transcription complete. Processing queued.")
        log_youtube(f"YT Transcribed and queued - {uploader[:20]} - {title[:40]}")
        notify_user("YouTube Transcription", f"Queued: {title[:50]}...")
    except Exception as e:
        workflow_status.workflow_end(wid, success=False, summary=str(e)[:80])
        raise


if __name__ == "__main__":
    main()
