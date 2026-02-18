"""Audio feedback module using macOS system sounds via afplay.

Provides audio cues for Butler activity states:
- Success: Glass.aiff (pleasant, confirmation)
- Waiting: Pop.aiff (neutral, attention)
- Error: Basso.aiff (attention, failure)

Uses subprocess to call afplay (built into macOS) with graceful degradation
when the tool or sound files are unavailable.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# System sounds location on macOS
SYSTEM_SOUNDS_PATH = Path("/System/Library/Sounds")

# Sound mappings for different states
SUCCESS_SOUND = "Glass"  # Pleasant, confirmation sound
WAITING_SOUND = "Pop"  # Neutral, attention sound
ERROR_SOUND = "Basso"  # Attention, failure sound


def _check_afplay_available() -> bool:
    """Check if afplay is available on the system.

    Returns:
        True if afplay is in PATH, False otherwise
    """
    return shutil.which("afplay") is not None


def _get_sound_path(sound_name: str) -> Optional[Path]:
    """Get the full path to a system sound file.

    Args:
        sound_name: Name of the sound without extension (e.g., 'Glass', 'Pop')

    Returns:
        Path to the sound file if it exists, None otherwise
    """
    sound_path = SYSTEM_SOUNDS_PATH / f"{sound_name}.aiff"
    if sound_path.exists():
        return sound_path

    # Try .wav extension as fallback
    wav_path = SYSTEM_SOUNDS_PATH / f"{sound_name}.wav"
    if wav_path.exists():
        return wav_path

    return None


def play_sound(sound_name: str, muted: bool = False) -> bool:
    """Play a system sound via afplay.

    Args:
        sound_name: Name of the sound without extension
                   Valid options: 'Glass', 'Pop', 'Basso', etc.
        muted: If True, skip playing (respects global mute)

    Returns:
        True if sound played successfully, False otherwise
    """
    if muted:
        logger.debug("Audio muted, skipping sound playback")
        return True

    # Check if afplay is available
    if not _check_afplay_available():
        logger.warning("afplay not found in PATH - audio feedback disabled")
        return False

    # Get sound file path
    sound_path = _get_sound_path(sound_name)
    if sound_path is None:
        logger.warning(f"Sound file not found: {sound_name}")
        return False

    try:
        result = subprocess.run(
            ["afplay", str(sound_path)],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.warning(f"Timeout playing sound: {sound_name}")
        return False
    except Exception as e:
        logger.warning(f"Failed to play sound {sound_name}: {e}")
        return False


def play_success_sound(muted: bool = False) -> bool:
    """Play the success sound (Glass).

    Args:
        muted: If True, skip playing

    Returns:
        True if sound played successfully, False otherwise
    """
    return play_sound(SUCCESS_SOUND, muted=muted)


def play_waiting_sound(muted: bool = False) -> bool:
    """Play the waiting sound (Pop).

    Args:
        muted: If True, skip playing

    Returns:
        True if sound played successfully, False otherwise
    """
    return play_sound(WAITING_SOUND, muted=muted)


def play_error_sound(muted: bool = False) -> bool:
    """Play the error sound (Basso).

    Args:
        muted: If True, skip playing

    Returns:
        True if sound played successfully, False otherwise
    """
    return play_sound(ERROR_SOUND, muted=muted)


__all__ = [
    "play_sound",
    "play_success_sound",
    "play_waiting_sound",
    "play_error_sound",
    "SYSTEM_SOUNDS_PATH",
    "SUCCESS_SOUND",
    "WAITING_SOUND",
    "ERROR_SOUND",
]
