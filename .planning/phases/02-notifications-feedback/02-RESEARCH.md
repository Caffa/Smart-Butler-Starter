# Phase 2: Notifications & Feedback - Research

**Researched:** 2026-02-19
**Domain:** macOS native notifications + audio feedback via Python
**Confidence:** HIGH

## Summary

Phase 2 implements user feedback via macOS notifications and system sounds. The key findings:

1. **Notifications**: Use `terminal-notifier` CLI (installed via Homebrew) - it's the standard for macOS notifications from command-line tools. Python wrapper `pync` exists but adds dependency; direct subprocess call to terminal-notifier is simpler and more robust.

2. **System Sounds**: Located in `/System/Library/Sounds/` (Basso.aiff, Glass.aiff, Hero.aiff, Pop.aiff, etc.). Play via `afplay` which is built into macOS - no additional installation needed.

3. **Event Subscription**: Phase 1's blinker-based `event_bus.py` already defines `note_written` and `pipeline_error` signals that this phase will subscribe to.

4. **Zero Hard Dependencies**: The notifications plugin can use subprocess for terminal-notifier and afplay (both system tools), with graceful degradation if tools aren't available.

**Primary recommendation:** Use subprocess to call `terminal-notifier` directly for notifications and `afplay` for sounds. This avoids Python package dependencies while maintaining full functionality.

---

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **Audio tone design:**
  - Use macOS system sounds (Glass, Hero, Pop, Basso, etc.) — no custom audio files needed for MVP
  - Distinct sounds per state: different system sound for success, waiting, and failure
  - Follow system volume — no separate Butler volume control
  - Global mute toggle in config that the notifications plugin respects (future plugins will also honor this)

- **Notification content:**
  - **Success notification:** Show content preview + file location
    - For Obsidian files: Display vault name + file name (not full filesystem path)
    - For Apple Notes: Display just the note name
  - **Error notification:** Simplified error message with emoji indicating what failed + "View log" button that opens log file for full details
  - **Click action:** Open in Obsidian (for success notifications)
  - **Timing:** Immediate — show as soon as note is written, no artificial delay

### Claude's Discretion

- Specific system sound choices (which sound for which state)
- Notification auto-dismiss timing
- Stacking behavior for rapid-fire notifications
- Whether "waiting" state even needs a notification (vs just audio tone)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope

</user_constraints>

---

<phase_requirements>

## Phase Requirements

| ID        | Description                                                                       | Research Support                                                                                                                                                   |
| --------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| NOTIFY-01 | macOS notification displays on configurable events (note.written, pipeline.error) | terminal-notifier supports `-sound`, `-open`, `-title`, `-message` options. Event subscription via blinker `note_written.connect()` and `pipeline_error.connect()` |
| NOTIFY-02 | Audio feedback plays via afplay for success/waiting/failure states                | afplay is built into macOS, plays .aiff/.wav files from `/System/Library/Sounds/`                                                                                  |
| NOTIFY-03 | Plugin is fully removable with zero hard dependencies                             | Use subprocess for system tools (no pip dependencies), graceful degradation when tools unavailable                                                                 |

</phase_requirements>

---

## Standard Stack

### Core

| Library             | Version           | Purpose                              | Why Standard                                         |
| ------------------- | ----------------- | ------------------------------------ | ---------------------------------------------------- |
| subprocess (stdlib) | N/A               | Execute terminal-notifier and afplay | Built into Python, no external dependencies          |
| terminal-notifier   | Latest (CLI)      | Send macOS notifications             | Standard for CLI tools on macOS, actively maintained |
| afplay              | System (built-in) | Play system sounds                   | Built into macOS, no installation needed             |

### Supporting

| Library | Version | Purpose                   | When to Use                    |
| ------- | ------- | ------------------------- | ------------------------------ |
| blinker | >=1.9.0 | Event signal subscription | Already in project for Phase 1 |

### Alternatives Considered

| Instead of        | Could Use             | Tradeoff                                                   |
| ----------------- | --------------------- | ---------------------------------------------------------- |
| terminal-notifier | pync (Python wrapper) | pync adds dependency, subprocess is simpler                |
| subprocess.run    | os.system             | subprocess.run is more secure and handles arguments better |
| afplay            | say command           | afplay plays system sounds directly; say uses TTS          |

**Installation:**

```bash
# For notifications - install terminal-notifier via Homebrew
brew install terminal-notifier

# afplay is built into macOS - no installation needed
```

---

## Architecture Patterns

### Recommended Project Structure

```
src/plugins/notifications/
├── plugin.py              # Main plugin class (subscribes to events)
├── notifier.py           # Notification delivery logic
├── sounds.py             # Audio playback logic
├── config.py             # Plugin configuration
└── plugin.yaml           # Plugin manifest
```

### Pattern 1: Event Subscription (from Phase 1)

**What:** Subscribe to blinker signals using the `@on()` decorator or `SignalSubscription` class
**When to use:** When responding to lifecycle events (note_written, pipeline_error)
**Example:**

```python
# Source: src/core/event_bus.py
from src.core.event_bus import on, note_written, pipeline_error

class NotificationsPlugin(BasePlugin):
    def on_enable(self) -> None:
        # Option 1: Decorator style
        @on(note_written)
        def handle_note_written(sender, path, **kwargs):
            self._show_success_notification(path, **kwargs)

        @on(pipeline_error)
        def handle_error(sender, error, context, **kwargs):
            self._show_error_notification(error, context)
```

### Pattern 2: Subprocess Notification

**What:** Call terminal-notifier via subprocess for macOS notifications
**When to use:** When sending native macOS notifications
**Example:**

```python
import subprocess
from pathlib import Path

def send_notification(
    title: str,
    message: str,
    sound: str = "default",
    open_url: str | None = None,
) -> bool:
    """Send macOS notification via terminal-notifier."""
    cmd = [
        "terminal-notifier",
        "-title", title,
        "-message", message,
        "-sound", sound,
    ]

    if open_url:
        cmd.extend(["-open", open_url])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False
```

### Pattern 3: System Sound Playback

**What:** Play macOS system sounds via afplay
**When to use:** When providing audio feedback for success/failure states
**Example:**

```python
import subprocess
from pathlib import Path

SYSTEM_SOUNDS_PATH = Path("/System/Library/Sounds")

def play_sound(sound_name: str) -> bool:
    """Play a system sound via afplay.

    Args:
        sound_name: Name of sound (without .aiff extension)
                   Valid: 'Glass', 'Hero', 'Pop', 'Basso', 'Tink', etc.
    """
    sound_path = SYSTEM_SOUNDS_PATH / f"{sound_name}.aiff"

    if not sound_path.exists():
        return False

    try:
        subprocess.run(
            ["afplay", str(sound_path)],
            capture_output=True,
            timeout=10,
        )
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False
```

### Pattern 4: Zero-Dependency Plugin

**What:** Make plugin work without hard dependencies using try/except and graceful degradation
**When to use:** When plugin must be removable without breaking the system
**Example:**

```python
class NotificationsPlugin(BasePlugin):
    def __init__(self, plugin_dir: Path, manifest: PluginManifest | None = None) -> None:
        super().__init__(plugin_dir, manifest)
        self._terminal_notifier_available: bool = False
        self._check_dependencies()

    def _check_dependencies(self) -> None:
        """Check if required system tools are available."""
        import shutil
        self._terminal_notifier_available = shutil.which("terminal-notifier") is not None
        self._afplay_available = shutil.which("afplay") is not None

    def on_enable(self) -> None:
        if not self._terminal_notifier_available:
            logger.warning("Notifications plugin: terminal-notifier not found, notifications disabled")
        # Continue enabling - plugin works in degraded mode
```

### Pattern 5: Global Mute Configuration

**What:** Check global mute config before sending notifications
**When to Use:** Respecting Butler-wide mute setting across all plugins
**Example:**

```python
from src.core.config import get_config

def is_muted() -> bool:
    """Check if Butler notifications are globally muted."""
    config = get_config()
    return config.get("notifications", {}).get("muted", False)
```

### Anti-Patterns to Avoid

- **Hard dependency on pync:** Adds unnecessary pip dependency; subprocess works directly
- **Blocking notification sends:** Use subprocess with timeout or run in thread pool
- **Ignoring missing tools:** Always check availability and log warnings
- **Full filesystem paths in notifications:** Parse path to show vault/folder structure only

---

## Don't Hand-Roll

| Problem             | Don't Build                 | Use Instead                  | Why                                     |
| ------------------- | --------------------------- | ---------------------------- | --------------------------------------- |
| macOS notifications | Python notification library | terminal-notifier CLI        | Native, well-maintained, no Python deps |
| Audio playback      | pygame/moviepy              | afplay                       | Built into macOS, zero dependencies     |
| Event subscription  | Custom event system         | blinker (already in project) | Phase 1 already uses it                 |

**Key insight:** The goal is zero hard dependencies. Using system tools (terminal-notifier, afplay) via subprocess achieves this while providing full functionality.

---

## Common Pitfalls

### Pitfall 1: Notification Won't Appear

**What goes wrong:** Notifications don't show up, especially when terminal-notifier isn't in PATH
**Why it happens:** Homebrew installs to /opt/homebrew/bin which may not be in PATH
**How to avoid:** Check for tool availability during plugin init, log clear warning if missing
**Warning signs:** `FileNotFoundError` when sending notification

### Pitfall 2: Sound Files Not Found

**What goes wrong:** System sounds don't play because file paths are wrong
**Why it happens:** macOS renamed sounds (e.g., Glass → Crystal in Big Sur), but files kept old names
**How to avoid:** Use known-good file names from /System/Library/Sounds/ (Basso.aiff, Glass.aiff, etc.)
**Warning signs:** afplay fails silently or exits with error

### Pitfall 3: Notifications Not Clickable

**What goes wrong:** Click action doesn't work (e.g., -open doesn't open Obsidian)
**Why it happens:** Obsidian may not have registered URL scheme, or wrong bundle ID used
**How to avoid:** Use `obsidian://` URL scheme for Obsidian, test with actual click
**Warning signs:** Notification appears but clicking does nothing

### Pitfall 4: Event Handlers Fire but Nothing Happens

**What goes wrong:** Signal connects but handler never called
**Why it happens:** Wrong signal name or missing sender specification
**How to avoid:** Use exact signal names from event_bus.py, verify sender if filtering
**Warning signs:** Handler defined but never executes

---

## Code Examples

### Complete Notification on note.written

```python
# Source: Based on terminal-notifier documentation + event_bus.py
from pathlib import Path
from src.core.event_bus import on, note_written
from src.core.config import get_config
import subprocess

SYSTEM_SOUNDS_PATH = Path("/System/Library/Sounds")

class NotificationService:
    """Handles macOS notifications and audio feedback."""

    def __init__(self):
        self._config = get_config().get("notifications", {})

    def notify_note_written(self, path: Path, source: str, word_count: int) -> None:
        """Show notification when note is successfully written."""
        if self._config.get("muted", False):
            return

        # Format display path based on source
        if source == "obsidian":
            # Show vault/folder structure, not full path
            display_path = self._format_obsidian_path(path)
        else:
            display_path = path.name

        # Build notification
        title = "Note Saved"
        message = f"{display_path}\n{word_count} words"

        # Get obsidian open URL
        obsidian_url = f"obsidian://open?path={path.absolute()}"

        # Send notification
        self._send_notification(title, message, sound="Glass", open_url=obsidian_url)

        # Play success sound
        self._play_sound("Glass")

    def notify_error(self, error: str, context: dict) -> None:
        """Show error notification."""
        if self._config.get("muted", False):
            return

        # Get log file path
        log_path = self._get_log_path()

        # Build error message with emoji
        emoji = self._get_error_emoji(context.get("stage", "unknown"))
        message = f"{emoji} {error}"

        # Send notification with log viewer action
        self._send_notification(
            title="Butler Error",
            message=message,
            sound="Basso",
            open_url=f"file://{log_path}"
        )

        # Play error sound
        self._play_sound("Basso")

    def _send_notification(
        self, title: str, message: str,
        sound: str = "default",
        open_url: str | None = None
    ) -> None:
        """Send notification via terminal-notifier."""
        cmd = [
            "terminal-notifier",
            "-title", title,
            "-message", message,
            "-sound", sound,
        ]

        if open_url:
            cmd.extend(["-open", open_url])

        try:
            subprocess.run(cmd, capture_output=True, timeout=5)
        except subprocess.TimeoutExpired:
            pass  # Silent failure for notification

    def _play_sound(self, sound_name: str) -> None:
        """Play system sound via afplay."""
        if self._config.get("muted", False):
            return

        sound_path = SYSTEM_SOUNDS_PATH / f"{sound_name}.aiff"
        if sound_path.exists():
            try:
                subprocess.run(["afplay", str(sound_path)], capture_output=True, timeout=10)
            except subprocess.TimeoutExpired:
                pass
```

### Event Handler Integration

```python
# Subscribe in plugin's connect_events method
def connect_events(self) -> None:
    from src.core.event_bus import note_written, pipeline_error
    from src.core.event_bus import SignalSubscription

    # Store subscription for cleanup
    self._event_subscriptions.append(
        SignalSubscription(note_written, self._on_note_written)
    )
    self._event_subscriptions[-1].connect()

    self._event_subscriptions.append(
        SignalSubscription(pipeline_error, self._on_pipeline_error)
    )
    self._event_subscriptions[-1].connect()

def _on_note_written(self, sender, path, timestamp, word_count, source, **kwargs):
    """Handle note.written event."""
    self._notifier.notify_note_written(Path(path), source, word_count)

def _on_pipeline_error(self, sender, error, context, **kwargs):
    """Handle pipeline.error event."""
    self._notifier.notify_error(str(error), context)
```

---

## State of the Art

| Old Approach       | Current Approach         | When Changed | Impact                                                            |
| ------------------ | ------------------------ | ------------ | ----------------------------------------------------------------- |
| Growl (deprecated) | terminal-notifier        | ~2015        | Growl no longer maintained, terminal-notifier is current standard |
| NSUserNotification | UNUserNotificationCenter | macOS 10.14+ | terminal-notifier handles this internally                         |
| Custom audio files | System sounds via afplay | Current      | No asset management needed, works out of box                      |

**Deprecated/outdated:**

- **pync library:** Adds Python dependency; subprocess is simpler
- **Growl:** Was macOS notification standard pre-2012, now deprecated
- **os.system():** Less secure than subprocess.run()

---

## Open Questions

1. **Which system sounds for which states?**
   - What we know: Available sounds are Basso, Glass, Hero, Pop, Tink, etc.
   - What's unclear: Which sound best represents each state
   - Recommendation: Use Glass for success (pleasant), Pop for waiting (neutral), Basso for error (attention)

2. **Notification auto-dismiss timing?**
   - What we know: terminal-notifier uses system default (~5 seconds)
   - What's unclear: User preference for duration
   - Recommendation: Use system default for MVP, add config option later

3. **"Waiting" state notification vs audio only?**
   - What we know: User asked to research whether waiting needs notification
   - What's unclear: If waiting happens frequently, notifications could be spammy
   - Recommendation: Audio tone only for waiting (no banner) to reduce notification fatigue

4. **How to handle rapid-fire notifications?**
   - What we know: terminal-notifier supports `-group` to replace similar notifications
   - What's unclear: Best grouping strategy
   - Recommendation: Use plugin name as group to prevent stacking

---

## Sources

### Primary (HIGH confidence)

- terminal-notifier GitHub (https://github.com/mikaelbr/terminal-notifier) - CLI tool documentation, -open and -sound options
- macOS system sounds location (/System/Library/Sounds/) - verified via bash ls
- Phase 1 event_bus.py (src/core/event_bus.py) - blinker signals implementation

### Secondary (MEDIUM confidence)

- WebSearch: "macOS system sounds list afplay" - confirms sound file locations and availability
- Stack Overflow: terminal-notifier usage patterns - common implementation approaches

### Tertiary (LOW confidence)

- WebSearch: pync vs terminal-notifier - general community preference (verified via pypi)

---

## Metadata

**Confidence breakdown:**

- Standard Stack: HIGH - verified via official docs and project context
- Architecture: HIGH - follows Phase 1 patterns exactly
- Pitfalls: MEDIUM - common issues identified, some require runtime verification

**Research date:** 2026-02-19
**Valid until:** 2026-03-19 (30 days - stable domain)
