# Phase 1 Research: Core Infrastructure

**Phase:** 01 - Core Infrastructure  
**Researched:** 2025-02-18  
**Source:** Existing project research (SUMMARY.md)

---

## Event Bus (blinker)

**Approach:** Use blinker library (1.9.0) - Pallets ecosystem standard, thread-safe, zero dependencies

**Implementation Pattern:**
```python
from blinker import Signal

# Define lifecycle signals
input_received = Signal('input.received')
note_routed = Signal('note.routed')
note_written = Signal('note.written')
heartbeat_tick = Signal('heartbeat.tick')
day_ended = Signal('day.ended')
pipeline_error = Signal('pipeline.error')

# Subscribe
@input_received.connect
def handle_input(sender, **kwargs):
    pass

# Emit
input_received.send('voice_plugin', text="note content", source="voice")
```

**Key Considerations:**
- Thread-safe by default
- Supports sender identification
- kwargs payload for flexible data passing
- Weak references by default (garbage collection friendly)

---

## Plugin System

**Approach:** Auto-discovery via filesystem scanning + capability registry

**Implementation Pattern:**
```python
# Plugin structure
plugins/
  voice_input/
    __init__.py
    plugin.yaml  # manifest
  daily_writer/
    __init__.py
    plugin.yaml

# Discovery
import importlib.util
from pathlib import Path

def discover_plugins(plugin_dir: Path) -> list[Plugin]:
    plugins = []
    for plugin_path in plugin_dir.iterdir():
        if (plugin_path / "plugin.yaml").exists():
            manifest = load_manifest(plugin_path / "plugin.yaml")
            if manifest.get("enabled", True):
                module = load_plugin_module(plugin_path)
                plugins.append(Plugin(manifest, module))
    return plugins
```

**Manifest Format (plugin.yaml):**
```yaml
name: voice_input
version: 1.0.0
description: Transcribe voice memos
enabled: true
capabilities:
  - input_provider
dependencies: []
events:
  listens:
    - input.received
  emits:
    - note.routed
```

**Zero Hard Dependencies:** Plugins use dependency injection via capability registry

---

## Safe Write Protocol

**Approach:** Atomic temp+replace with mtime double-check

**Implementation Pattern:**
```python
import tempfile
import shutil
from pathlib import Path

def safe_write(filepath: Path, content: str) -> bool:
    """
    Safely write content to file, preventing race conditions with Obsidian.
    Returns True if successful, False if file was modified during write.
    """
    # Check mtime before write
    if filepath.exists():
        pre_mtime = filepath.stat().st_mtime
    else:
        pre_mtime = None
    
    # Write to temp file
    temp_fd, temp_path = tempfile.mkstemp(dir=filepath.parent)
    try:
        with os.fdopen(temp_fd, 'w') as f:
            f.write(content)
        
        # Atomic rename
        shutil.move(temp_path, filepath)
        
        # Verify mtime hasn't changed (Obsidian didn't edit during our write)
        post_mtime = filepath.stat().st_mtime
        if pre_mtime and abs(post_mtime - pre_mtime) < 0.001:
            # File was modified by something else
            return False
            
        return True
    finally:
        if Path(temp_path).exists():
            Path(temp_path).unlink()
```

**Key Considerations:**
- Use same directory for temp file (atomic rename guarantee)
- mtime resolution is filesystem-dependent (1s on some systems)
- Consider file locking for additional safety
- Never write to files Obsidian is actively editing

---

## Task Queue (Huey + SQLite)

**Approach:** Huey 2.6.0 with SQLite backend - lightweight alternative to Celery

**Implementation Pattern:**
```python
from huey import SqliteHuey
from huey.api import Task

# Initialize with single SQLite file
huey = SqliteHuey(
    filename='~/.butler/data/tasks.db',
    results=True,  # Store results for recovery
    store_none=False,
)

# Define tasks
@huey.task()
def transcribe_audio(audio_path: str) -> str:
    """Transcribe audio file and return text."""
    # Implementation
    return transcription

# Schedule periodic tasks
@huey.periodic_task(crontab(minute='0', hour='23'))
def nightly_digest():
    """Generate daily summary at 23:00."""
    pass

# Consumer (background worker)
# Run: huey_consumer.py main.huey
```

**Key Features:**
- Single SQLite file, zero external dependencies
- Task results stored for crash recovery
- Periodic tasks built-in
- Smart throttling via @huey.task(retries=3, retry_delay=60)

---

## Smart Throttling

**Approach:** Decorator-based throttling checking CPU, RAM, power status

**Implementation Pattern:**
```python
import psutil
import functools
from typing import Callable

def throttled(
    max_cpu: float = 50.0,
    max_ram_percent: float = 80.0,
    require_power: bool = False
) -> Callable:
    """Decorator that defers task execution when system is busy."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Check system load
            cpu = psutil.cpu_percent(interval=0.1)
            ram = psutil.virtual_memory().percent
            power = psutil.sensors_battery()
            on_battery = power is not None and not power.power_plugged
            
            if cpu > max_cpu:
                raise ThrottledException(f"CPU {cpu}% > {max_cpu}%")
            if ram > max_ram_percent:
                raise ThrottledException(f"RAM {ram}% > {max_ram_percent}%")
            if require_power and on_battery:
                raise ThrottledException("On battery power")
            
            return func(*args, **kwargs)
        return wrapper
    return decorator

# Integration with Huey
@huey.task(retries=5, retry_delay=300)  # Retry every 5 minutes
@throttled(max_cpu=60, max_ram_percent=75)
def heavy_ai_task():
    pass
```

---

## Configuration System

**Approach:** YAML config files + per-plugin user-data.json

**Implementation Pattern:**
```python
from pathlib import Path
import yaml

class Config:
    def __init__(self, config_dir: Path = Path("~/.butler")):
        self.config_dir = config_dir.expanduser()
        self.main_config = self._load_yaml("config.yaml")
        self.plugin_configs = {}
    
    def _load_yaml(self, filename: str) -> dict:
        path = self.config_dir / filename
        if path.exists():
            with open(path) as f:
                return yaml.safe_load(f)
        return {}
    
    def get_plugin_config(self, plugin_name: str) -> dict:
        if plugin_name not in self.plugin_configs:
            path = self.config_dir / "plugins" / f"{plugin_name}.yaml"
            self.plugin_configs[plugin_name] = self._load_yaml(str(path))
        return self.plugin_configs[plugin_name]
    
    def save_plugin_data(self, plugin_name: str, data: dict):
        """Save plugin state to user-data.json."""
        path = self.config_dir / "plugins" / plugin_name / "user-data.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
```

**Directory Structure:**
```
~/.butler/
  config.yaml           # Main config
  plugins/
    voice_input.yaml    # Plugin config
    voice_input/
      user-data.json    # Plugin state
```

---

## Logging System

**Approach:** Separate verbose.log and error.log with plugin attribution

**Implementation Pattern:**
```python
import logging
from pathlib import Path

def setup_logging(log_dir: Path):
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Verbose log - everything
    verbose_handler = logging.FileHandler(log_dir / "verbose.log")
    verbose_handler.setLevel(logging.DEBUG)
    
    # Error log - warnings and above
    error_handler = logging.FileHandler(log_dir / "error.log")
    error_handler.setLevel(logging.WARNING)
    
    # Plugin attribution via LoggerAdapter
    class PluginAdapter(logging.LoggerAdapter):
        def process(self, msg, kwargs):
            plugin = self.extra.get('plugin', 'core')
            return f"[{plugin}] {msg}", kwargs
    
    # Setup
    logger = logging.getLogger('butler')
    logger.setLevel(logging.DEBUG)
    logger.addHandler(verbose_handler)
    logger.addHandler(error_handler)
    
    return logger

# Usage
logger = PluginAdapter(logging.getLogger('butler'), {'plugin': 'voice_input'})
logger.info("Transcription started")
```

---

## parakeet-mlx Transcription

**Approach:** parakeet-mlx for Apple Silicon-optimized transcription

**Implementation Pattern:**
```python
from parakeet_mlx import Parakeet

class Transcriber:
    def __init__(self):
        self.model = None
    
    def load_model(self):
        """Lazy-load model on first use."""
        if self.model is None:
            self.model = Parakeet()
    
    def transcribe(self, audio_path: str) -> str:
        self.load_model()
        result = self.model.transcribe(audio_path)
        return result.text
```

**Key Considerations:**
- Lazy-load model to avoid startup delay
- Model is ~300MB, load time ~2s on M1
- First transcription slower (model warmup)
- Returns confidence scores for threshold filtering

---

## launchd Folder Watching

**Approach:** plist file in ~/Library/LaunchAgents/ with WatchPaths

**Implementation Pattern:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.butler.voicewatch</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/butler</string>
        <string>process-voice</string>
    </array>
    <key>WatchPaths</key>
    <array>
        <string>/Users/USER/Music/Voice Memos</string>
    </array>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
```

**Key Considerations:**
- Replace USER with actual username
- launchctl load/unload to enable/disable
- FSEvents-based, low resource usage
- Triggers on any file change in directory

---

## Obsidian Daily Writer

**Approach:** Append to YYYY-MM-DD.md with frontmatter

**Implementation Pattern:**
```python
from datetime import datetime
from pathlib import Path

class DailyWriter:
    def __init__(self, vault_path: Path):
        self.vault_path = vault_path
    
    def write_note(self, text: str, source: str) -> Path:
        today = datetime.now()
        filename = today.strftime("%Y-%m-%d.md")
        filepath = self.vault_path / "Daily" / filename
        
        # Ensure directory exists
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        # Format entry
        timestamp = today.strftime("%H:%M")
        entry = f"\n## {timestamp}\n\n{text}\n\n_Source: {source}_\n"
        
        # Append with safe_write
        if filepath.exists():
            current = filepath.read_text()
            content = current + entry
        else:
            # New file with frontmatter
            frontmatter = f"---\ndate: {today.strftime('%Y-%m-%d')}\n---\n\n# {today.strftime('%A, %B %d, %Y')}\n"
            content = frontmatter + entry
        
        safe_write(filepath, content)
        
        # Emit event
        note_written.send('daily_writer', 
            path=str(filepath),
            timestamp=timestamp,
            word_count=len(text.split()),
            source=source
        )
        
        return filepath
```

---

## Critical Pitfalls (from SUMMARY.md)

1. **Performance Invisibility Failure:** App must be invisible when idle
   - Hard limits: < 100MB RAM, < 1% CPU when idle
   - Lazy-load AI models
   - Use OS-level power management

2. **File Race Condition:** Concurrent writes with Obsidian
   - Safe-write protocol with mtime check
   - Atomic temp+replace
   - Never edit files Obsidian has open

3. **Model Loading:** parakeet-mlx slow on first use
   - Lazy-load on first transcription
   - Consider background warmup

4. **Plugin Dependencies:** Avoid hard coupling
   - Use capability registry
   - Event-driven communication
   - Graceful degradation

---

## Research Complete

**Confidence:** HIGH

All core technologies (blinker, Huey, parakeet-mlx, YAML) are mature and well-documented. The main risks are:
1. Safe-write protocol needs testing with actual Obsidian usage patterns
2. parakeet-mlx API may need validation on target hardware
3. Plugin auto-discovery must handle import errors gracefully

**Recommended Plan Structure:**
- Wave 1: Event bus, config, logging, safe write (independent foundations)
- Wave 2: Plugin system, task queue (builds on event bus)
- Wave 3: Voice input, daily writer (builds on event bus + plugin system)
- Wave 4: Installation scripts (can parallelize with others)
