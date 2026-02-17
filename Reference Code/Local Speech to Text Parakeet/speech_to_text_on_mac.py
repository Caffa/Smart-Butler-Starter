#!/usr/bin/env python3
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

from parakeet_mlx import from_pretrained

from asr_helper import (
    audio_has_significant_energy,
    chunk_audio_vad,
    fuzzy_dedup_overlap,
    get_audio_duration,
    mechanical_cleanup,
    preprocess_audio,
)

MODEL_ID = "mlx-community/parakeet-tdt-0.6b-v2"

INPUT_DIR = Path("/Users/caffae/Automation Folders/VoiceMemo-To-Text")
OUTPUT_DIR = Path("/Users/caffae/Automation Folders/Text-To-Butler")

# Only use VAD chunking for audio longer than 4 minutes
CHUNK_THRESHOLD_SECONDS = 240


def cleanup(wav_path: Path, input_path: Path, chunk_dir: Path | None = None):
    """Clean up temporary files."""
    # Try to send to trash first
    try:
        from send2trash import send2trash

        if wav_path.exists():
            send2trash(wav_path)
        if input_path.exists():
            send2trash(input_path)
        if chunk_dir and chunk_dir.exists():
            send2trash(chunk_dir)
    except ImportError as e:
        # log error to  '/Users/caffae/Local Projects/AI Memories/Debug/System Logs/main.log'
        with open(
            "/Users/caffae/Local Projects/AI Memories/Debug/System Logs/main.log", "a"
        ) as f:
            f.write(
                f"[Local Parakeet Transcription] ⚠️ Error cleaning up temporary files (send2trash not available, falling back to unlink so the audio files are deleted without being sent to trash): {e}\n{traceback.format_exc()}\n"
            )

        with open("/Users/caffae/Desktop/llm_router_audit.log", "a") as f:
            f.write(
                "[Local Parakeet Transcription] ⚠️ Error cleaning up transcription audio files (There may be an issue with send2trash library, falling back to unlink so the audio files are deleted without being sent to trash)"
            )

        try:
            # Fallback to unlink if send2trash is not available
            if wav_path.exists():
                wav_path.unlink(missing_ok=True)
            if input_path.exists():
                input_path.unlink(missing_ok=True)
            if chunk_dir and chunk_dir.exists():
                shutil.rmtree(chunk_dir, ignore_errors=True)
        except Exception as e:
            # '/Users/caffae/Desktop/llm_router_audit.log' is the filtered log file for this script
            with open("/Users/caffae/Desktop/llm_router_audit.log", "a") as f:
                f.write(
                    f"[Local Parakeet Transcription] ⚠️ Error cleaning up transcription (both send2trash and unlink failed): {e}\n{traceback.format_exc()}\n"
                )
            with open(
                "/Users/caffae/Local Projects/AI Memories/Debug/System Logs/main.log",
                "a",
            ) as f:
                f.write(
                    f"[Local Parakeet Transcription] ⚠️ Error cleaning up transcription (both send2trash and unlink failed): {e}\n{traceback.format_exc()}\n"
                )


def main():
    input_path = Path(sys.argv[1])

    if not input_path.exists():
        return

    chunk_dir = None

    # Preprocess: normalize volume + convert to 16kHz mono WAV
    wav_path = preprocess_audio(input_path)
    if wav_path is None:
        subprocess.run([
            "osascript",
            "-e",
            'display notification "Audio preprocessing failed" with title "🔴 Transcription Error"',
        ])
        return

    try:
        # Load model (cached after first run)
        model = from_pretrained(MODEL_ID)

        # Check duration to decide if chunking is needed
        duration = get_audio_duration(wav_path)

        if duration > CHUNK_THRESHOLD_SECONDS:
            # Long audio: use VAD chunking
            transcripts = []
            chunk_dir = wav_path.parent / f"{wav_path.stem}_chunks"

            for chunk_path, start_sec, end_sec in chunk_audio_vad(wav_path, chunk_dir):
                chunk_text = model.transcribe(str(chunk_path)).text.strip()
                if chunk_text:
                    transcripts.append((chunk_text, start_sec, end_sec))

            # Merge transcripts with fuzzy dedup
            if transcripts:
                result = fuzzy_dedup_overlap(transcripts)
            else:
                result = ""
        else:
            # Short audio: transcribe directly
            result = model.transcribe(str(wav_path)).text.strip()

        # Apply mechanical cleanup (remove fillers, stutters, etc.)
        result = mechanical_cleanup(result)

        # Do not write output if result is empty
        if not result:
            if audio_has_significant_energy(wav_path):
                msg = f"[Local Parakeet Transcription] ⚠️ Audio has bad static (no discernable speech): {input_path}\n"
                with open(
                    "/Users/caffae/Local Projects/AI Memories/Debug/System Logs/main.log",
                    "a",
                ) as f:
                    f.write(msg)
                with open("/Users/caffae/Desktop/llm_router_audit.log", "a") as f:
                    f.write(msg)
                subprocess.run([
                    "osascript",
                    "-e",
                    'display notification "Audio has bad static" with title "⚠️ Transcription Error"',
                ])
            else:
                subprocess.run([
                    "osascript",
                    "-e",
                    'display notification "Recording was empty" with title "⚠️ Recording Empty"',
                ])
                with open("/Users/caffae/Desktop/llm_router_audit.log", "a") as f:
                    f.write(f"Recording was empty: {input_path}\n")
            return

        # Do not write output to the OUTPUT_DIR directly, write to a temp file first
        temp_path = Path("~/tmp/parakeet-output.txt").expanduser()
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(result)

        # Write output
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_path), OUTPUT_DIR / f"{input_path.stem}.txt")
    finally:
        cleanup(wav_path, input_path, chunk_dir)


if __name__ == "__main__":
    main()
