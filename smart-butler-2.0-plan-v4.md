# 🫖 Smart Butler 2.0 — Project Plan (v4)

---

## What Is This?

**Smart Butler** is a local-first personal AI assistant that captures your thoughts — from voice memos, messages, or text — organises them automatically, and files them into your second brain or diary without any extra effort from you.

It runs quietly on your Mac. You speak, type, or send a message. Butler handles the rest: transcription, classification, writing to the right file, building a searchable memory, and surfacing patterns over time. Everything stays on your machine.

**Built for two kinds of users:**
- **You** — a developer/writer who wants Alfred integration, hotkey voice input from Mac and iPhone/Watch, agentic AI features, and a plugin system you can extend without breaking things.
- **Your mom** — a non-technical user who journals by sending voice messages on Telegram, asks Butler questions about her notes, and never opens a terminal.

Both users run the same system. The difference is the install path and which plugins are enabled.

---

## Hardware Target (Locked)

**Apple Silicon Mac capable of running:**
- `parakeet-mlx` for local transcription
- `llama3.1:8b` via Ollama for LLM tasks

This is not optimised for Intel Macs, cloud API fallback, or API key management. Locking to this target eliminates an entire class of conditional logic from the codebase. Users who don't meet this requirement will see a clear message from `butler doctor` at first run.

---

## The Two-Person Team

### 🔧 Engineer
Cares about: clean architecture, easy reinstall for testing, useful logs, plugin isolation, synthetic input tester, smart library choices, git tags as rollback checkpoints, IPC boundaries that make components independently replaceable, and data integrity under failure conditions.

### 🎨 UX Designer
Cares about: install experience that works for someone who has never opened Terminal, every prompt having plain-English context, setup that feels like a friendly wizard, plugin descriptions a grandmother can understand, Butler being **invisible when idle and useful when needed** — never the reason the computer is slow.

---

## Architecture (Locked)

### Core Patterns
- **Event Bus** (`blinker`): lifecycle events — `input.received`, `note.routed`, `heartbeat.tick`, `day.ended`, etc.
- **Pipeline**: ordered data transforms — transcription → cleaning → routing → saving. Plugins insert named stages.
- **Service Locator** (via `capabilities.json`): plugins declare callable functions; other plugins and Alfred discover and invoke them through the capabilities registry.

### Tech Stack
| Concern | Choice | Reason |
|---|---|---|
| Language | Python 3.11+ | ML libraries, existing codebase, agentic tooling |
| Event bus | `blinker` | Lightweight, battle-tested |
| Task queue | `huey` + SQLite | Zero extra services; SQLite persistence means tasks survive crashes automatically |
| Config | YAML + `PyYAML` + `dataclasses` | Human-readable, no magic |
| Config UI | `textual` TUI | Checkboxes/dropdowns without a web server |
| Menubar app | `rumps` + `py2app` | Mac-native feel, active maintenance. Runs as separate process via IPC — swappable without touching core. |
| Vector memory | `chromadb` behind `MemoryBackend` ABC | Local, no server; swap to pgvector later without changing other code |
| Vault watching | `watchdog` (FSEvents on macOS) + hash cache | Incremental re-indexing only; never re-embeds unchanged files |
| Folder watch (audio) | `launchd` + `WatchPaths` | System-level, reliable, not Automator |
| Notifications | `osascript` + `afplay` | Native macOS, zero dependencies |
| Logging | Single logger, multiple handlers | One place to look, filterable |
| Version control | git tags per stage | Rollback checkpoints |
| Obsidian format | Obsidian-flavoured markdown | `[[wikilinks]]`, frontmatter, tags |
| Wake word | `openwakeword` | Runs locally, lightweight, no cloud |

### Two Storage Domains (Critical Separation)
```
~/.butler/                          ← SYSTEM DATA (never user-edited)
  config/
    config.yaml                     # core + channel settings
  logs/
    butler.log                      # verbose, all levels
    butler-errors.log               # ERROR+ only; Inbox.md fallbacks logged here
  data/
    prompt-history/                 # YYYY-MM-DD.jsonl
    memory/                         # chromadb vector index
    cache/
      dedup.db                      # SHA-256 hash → skip duplicate writes
      file-index.db                 # {filepath: content_hash} for FSEvents watchdog
      recent-events.json            # rolling last 20 events (menubar polls this)
  install-manifest.json             # every file install.sh touched; read by uninstaller

{user-configured vault}/            ← VAULT DATA (Obsidian opens this as a vault)
  default: ~/Butler-Notes/
  journals/
    daily/                          # YYYY-MM-DD.md  ← single source of truth
    Inbox.md                        # safe-write fallback; auto-retried, then heartbeat
    digests/                        # YYYY-MM-DD-digest.md
    reflections/                    # YYYY-MM-DD-reflection.md
    deductions/                     # YYYY-MM-DD-deductions.md
  projects/                         # {project-slug}.md
  reference/
    youtube/                        # {video-slug}.md
  action-items.md                   # append-only, auto-managed
  index.md                          # auto-generated vault index (optional plugin)
```

Install script asks: *"Where would you like Butler to save your notes? (Press Enter for ~/Butler-Notes)"*
Stored in `config.yaml` as `vault.path`. Never hardcoded anywhere.

### Plugin Contract
Every plugin exposes exactly one entry point in `plugin/main.py`:
```python
def register(bus, config):
    ...
```
**Auto-discovery**: startup scans `plugins/*/manifest.json` for `"enabled": true`. Drop a folder in → loads next restart. No CLI registration needed.

**If removing a plugin breaks core, that is a bug in core.**

### Plugin Folder Structure
```
plugins/
  {plugin-id}/
    manifest.json          # identity, version, tags, dependencies, user_settings schema
    hooks.json             # events listened to + emitted
    capabilities.json      # callable functions (compiled from docstrings by dev-script)
    alfred-runner.json     # Alfred script filter entries
    user-data.json         # USER settings overrides — what the TUI edits
    python-runners/        # CLI-callable scripts (Alfred, terminal, Keyboard Maestro)
    plugin/
      main.py              # register(bus, config) — only entry point core calls
      helpers.py
      models.py            # dataclasses only, no Pydantic
    tests/
    README.md              # First line: one sentence. Non-developer readable. Max 120 chars.
```

### manifest.json
```json
{
  "id": "youtube-to-reference",
  "name": "YouTube to Reference",
  "version": "1.0.0",
  "description": "Downloads YouTube videos, transcribes them, and files them in your vault.",
  "author": "you",
  "min_butler_version": "2.0.0",
  "dependencies": [],
  "optional_dependencies": ["memory", "day-digest"],
  "tags": ["media-handler", "link-resolver", "llm-required"],
  "enabled": false,
  "user_settings": {
    "auto_summarise": { "type": "bool", "default": true, "label": "Add summary to daily journal" },
    "output_folder": { "type": "string", "default": "reference/youtube", "label": "Where to save transcripts" }
  }
}
```

### user-data.json (per plugin, TUI-editable)
Holds user overrides for settings declared in `manifest.json` under `user_settings`. The TUI reads the schema from manifest for field type/label/default, reads current values from `user-data.json`, and saves changes back to `user-data.json` only — never touches `manifest.json` or `config.yaml`.

### Prompt History Format
```json
{
  "ts": "2025-02-17T14:32:00",
  "plugin": "note-router",
  "template": "classify_note",
  "variables": { "raw_text": "...", "date": "2025-02-17" },
  "rendered": "full prompt string after all variable injection",
  "model": "llama3.1:8b",
  "response_preview": "first 200 chars of model response"
}
```

### Uninstall Strategy
- `install.sh` writes every touched path to `~/.butler/install-manifest.json` as it runs
- `uninstall.sh --keep-config` removes system files, preserves vault + config
- `uninstall.sh --keep-models` additionally preserves Ollama models
- Told to user at install end: *"To remove Butler any time: ~/.butler/uninstall.sh"*

---

## Core Subsystems (Reference)

### Safe Write Protocol (`core/safe_write.py`)
Prevents race conditions with Obsidian's atomic save (write-temp-rename). Butler must never append to a file Obsidian is currently writing.

**Write sequence:**
1. Check target file `mtime` at queue time — if modified < 2s ago, wait.
2. Re-check `mtime` again immediately before writing (double-check pattern).
3. If still busy: wait 1 minute, retry. Repeat up to 10 times (10 minute window).
4. If still busy after 10 minutes: write to `Inbox.md` as fallback (unconditional).
5. Log every Inbox.md fallback to `butler-errors.log` with reason and timestamp.

**Inbox.md format** — each entry has frontmatter so auto-retry knows its age and origin:
```markdown
---
inbox_ts: 2025-02-17T14:32:00
source: voice-memo
retry_count: 10
original_target: journals/daily/2025-02-17.md
---
Note text here...
```

**Auto-retry from Inbox.md:**
- On each `heartbeat.tick`: scan Inbox.md for entries, attempt to write each to its `original_target` using the same mtime check sequence.
- Successfully written entries are removed from Inbox.md.
- Notifications plugin optionally informed when Inbox.md drains to zero.

**Rule:** Never use `flock` — Obsidian does not respect POSIX file locks and this would give false safety confidence. The mtime double-check pattern is the correct approach for this environment.

---

### Smart Throttling (`core/throttling.py`)
Background tasks (memory indexing, LLM calls, embeddings) check system conditions before running. Designed for a MacBook Air on battery during a Zoom call — Butler must be invisible, not annoying.

**Throttle gate checks (all must pass):**
- CPU usage < 20% (via `psutil`)
- Free RAM > 2GB (via `psutil`)
- No active Ollama process detected (via `psutil` process scan — checks for `ollama` in process list)
- Power: plugged in OR battery > 20%

**Behaviour:**
- If gate fails: task is deferred, re-checked on next `heartbeat.tick`
- Tasks that have been deferred > 30 minutes: logged to `butler.log` with `[THROTTLED]` prefix
- Throttle state visible in menubar icon tooltip and `butler status` output
- `@throttled` decorator wraps any background task function — the decorator handles the check and defer logic so plugins don't implement it themselves

**Tasks that are always throttled (never run unthrottled):**
- Memory reindexing
- Embedding generation
- Reflection generation
- Deduction generation
- YouTube transcription

**Tasks that are never throttled (must run immediately):**
- Writing incoming notes to disk
- Safe-write retry checks
- Telegram message responses
- Notification dispatch

---

### Memory Indexing Strategy (`core/vault_watcher.py`)
Avoids re-embedding the entire vault on every restart.

**Approach: FSEvents watchdog + hash cache**
- `watchdog` library monitors vault path via macOS FSEvents (kernel-level, not polling)
- `~/.butler/data/cache/file-index.db` stores `{filepath: sha256_of_content}`
- On any file change event: compute new hash, compare to stored hash
- **Hash unchanged** → skip entirely (Obsidian sync touch, no real edit)
- **Hash changed, Butler wrote it** → skip re-embedding (Butler tracks its own writes with a write-receipt set in memory)
- **Hash changed, user wrote it** → re-index that file only in memory; emit `vault.file.changed` event; never re-run LLM processing on user edits
- On startup: compare full vault against hash cache, queue changed files for incremental re-indexing (throttled)

**Write receipt pattern:** Before Butler writes to any file, it adds the filepath + expected resulting hash to an in-memory set `butler_write_receipts`. The FSEvents handler checks this set first before deciding whether a change is user-originated.

---

### Crash Recovery
Huey with SQLite backend provides task durability by default. If the worker process dies mid-task, unfinished tasks remain in the SQLite queue and are automatically retried on next startup. No additional recovery logic needed — this is the primary reason SQLite was chosen over an in-memory queue.

**On startup, `butler status` reports:**
- Number of tasks recovered from previous session (if any)
- Visible in menubar tooltip and terminal output

---

### Bootstrapper Install Pattern
The `.pkg` installer and `install.sh` are intentionally lightweight. Heavy assets download separately at first run.

**What the installer does (~50MB download):**
- Installs Python environment and dependencies
- Installs Butler CLI and plugins
- Creates `~/.butler/` directory structure
- Writes `config.yaml` with user-chosen vault path
- Installs launchd plists

**What the installer does NOT do:**
- Download Ollama (checked separately)
- Pull LLM models (`ollama pull llama3.1:8b` ~4.7GB)
- Download parakeet-mlx model (~1.5GB)

**First run sequence** (triggered automatically after install, or via `butler doctor`):
```
🫖 Butler — First Run Setup

✅ Butler installed
⬇️  Ollama not found — installing now...          [progress]
⬇️  Downloading llama3.1:8b (4.7 GB)...           [progress bar]
⬇️  Downloading parakeet-mlx model (1.5 GB)...    [progress bar]
✅  All models ready
✅  Butler is ready to use
```

Each step is resumable — if the internet drops, running `butler doctor` again picks up where it left off.

---

## Plugin Catalogue

| Plugin ID | Tags | Stage | Description |
|---|---|---|---|
| `example-plugin` | `dev` | 0 | Template plugin for development and regression testing. |
| `voice-input` | `input`, `audio` | 1 | Watches a folder for audio files and transcribes them into your daily journal. |
| `daily-writer` | `core`, `output` | 1 | Saves your notes to today's journal file with timestamps and Obsidian formatting. |
| `notifications` | `ux`, `optional` | 2 | Plays a sound and shows a notification when Butler does something. |
| `telegram-input` | `input`, `optional` | 3 | Lets you send notes and voice messages to Butler via Telegram from any device. |
| `alfred-input` | `input`, `optional` | 3 | Lets you send a quick note to Butler from Alfred with a keyboard shortcut. |
| `apple-notes-input` | `input`, `optional` | 3 | Watches an Apple Notes folder and sends new notes to Butler automatically. |
| `text-polish` | `llm-required`, `optional` | 4 | Gently cleans up voice notes — fixing filler words — before saving them. |
| `day-digest` | `llm-required`, `optional` | 4 | Writes a summary of your day's notes each evening. |
| `note-router` | `llm-required`, `optional` | 5 | Automatically files notes to the right project instead of always using the daily journal. |
| `memory` | `core`, `llm-required` | 6 | Gives Butler a searchable memory so you can ask questions and get answers. |
| `wake-word` | `input`, `optional` | 7 | Lets you trigger Butler by saying "Hey Butler" without pressing any keys. |
| `reflection` | `llm-required`, `optional` | 7 | Writes a thoughtful nightly reflection, noticing patterns in what you've been thinking about. |
| `menubar` | `ux`, `optional` | 8 | Shows Butler's status and recent events in your Mac menu bar. |
| `guided-conversation` | `llm-required`, `optional`, `telegram-required` | 9 | Guides you through a short journaling conversation on Telegram and saves the summary. |
| `action-items` | `llm-required`, `optional` | 9 | Extracts open action items from notes and collects them in [[action-items]]. |
| `contradiction-detector` | `llm-required`, `optional` | 9 | Notices when a new note contradicts something you've written before. |
| `morning-briefing` | `llm-required`, `optional`, `telegram-required` | 9 | Sends a friendly morning Telegram message with open loops and a reflection question. |
| `deductions` | `llm-required`, `optional` | 10 | Notices patterns across your notes over time and surfaces hypotheses. |
| `smarter-digest` | `llm-required`, `optional` | 10 | A richer daily digest that connects today's notes to your longer patterns. |
| `readwise` | `media-handler`, `link-resolver`, `optional` | 11 | Automatically sends article URLs and highlights to your Readwise account. |
| `youtube-to-reference` | `media-handler`, `link-resolver`, `llm-required`, `optional` | 11 | Downloads YouTube videos, transcribes them, and files the transcript in your vault. |
| `plugin-manager` | `ux`, `dev` | 12 | Browse, enable, and disable Butler plugins grouped by tag. |
| `transcription-confidence` | `optional`, `audio` | 12 | Highlights low-confidence transcription segments in Obsidian for review. |

---

## Stages

---

### Stage 0 — Skeleton & Dev Tooling
**Exit condition:** `example-plugin` loads and logs cleanly. `butler dev validate example-plugin` passes. Engineer wipes and reinstalls in under 2 minutes.

- [ ] Init git repo, `.gitignore` (`~/.butler/`, `__pycache__`, `.env`, `*.pyc`)
- [ ] Folder structure: `core/`, `plugins/`, `scripts/`, `prompts/`, `tests/`, `docs/`
- [ ] `core/bus.py` — `blinker` wrapper; event names as string constants in `Events` class
- [ ] `core/config.py` — loads `~/.butler/config/config.yaml`, merges `user-data.json` from enabled plugins, returns typed dataclass tree. No Pydantic.
- [ ] `core/plugin_loader.py` — scans `plugins/*/manifest.json`, filters `enabled: true`, calls `plugin.main.register(bus, config)`. Auto-discovery on restart.
- [ ] `core/logger.py` — single logger; file handler (DEBUG+ → `butler.log`), file handler (ERROR+ → `butler-errors.log`), stderr handler (WARNING+). Format: `[HH:MM:SS] [LEVEL] [plugin-id] message`
- [ ] `core/pipeline.py` — named stage registry; `pipeline.insert(after="stage-name", fn=transform)`
- [ ] `core/capabilities_registry.py` — `call(id, **kwargs)` returns `None` + logs warning if plugin disabled. Never raises.
- [ ] `core/prompts.py` — loads `.md` templates with YAML frontmatter, renders with variable dict, appends to prompt-history `.jsonl`
- [ ] `core/safe_write.py` — mtime double-check, retry loop (1 min × 10), Inbox.md fallback, Inbox.md auto-retry on heartbeat. Logs all fallbacks to `butler-errors.log`.
- [ ] `core/throttling.py` — `@throttled` decorator; checks CPU < 20%, RAM > 2GB, no active Ollama process, power status. Defers to next `heartbeat.tick` if gate fails.
- [ ] `core/vault_watcher.py` — `watchdog` FSEvents monitor; SHA-256 hash cache in `file-index.db`; write-receipt set; emits `vault.file.changed` for user edits only.
- [ ] `scripts/dev-validate.py` — manifest key check, hooks.json vs subscriptions, capabilities.json from docstrings, README first line ≤ 120 chars
- [ ] `scripts/dev-test-input.py` — fires synthetic `input.received`. Usage: `python dev-test-input.py --text "hello" --source alfred --dry-run`
- [ ] `scripts/dev-reinstall.sh` — wipes `~/.butler/` (keeps vault), reinstalls fresh
- [ ] `plugins/example-plugin/` — full structure, logs "🫖 loaded" on startup, "👋 hello" on `Events.TEST_PING`. Regression canary + copy-paste template.
- [ ] `CONTRIBUTING.md` — one page: drop plugin folder in, add manifest, restart.
- [ ] **Git tag:** `v2.0-skeleton`

---

### Stage 1 — Base Engine + Friendly Install
**Exit condition:** Drop audio file → transcription in today's `.md`. Install has personality. `butler doctor` runs first-run model downloads with progress bars.

#### Bootstrapper Install Script *(UX first)*
- [ ] Opens with ASCII art butler + greeting: *"Hello! I'm Butler. Let's get you set up. (~3 minutes for the app, models download separately)"*
- [ ] Each prompt preceded by plain-English explanation — never a bare `>` prompt
- [ ] Prompts: vault folder (default `~/Butler-Notes`), Telegram opt-in (y/N — deferred)
- [ ] Progress with emoji step indicators: `✅ Created notes folder`, `✅ Butler CLI installed`
- [ ] Does NOT download Ollama or models — defers to first-run
- [ ] `--verbose` shows full Unix output; default hides behind friendly summaries
- [ ] Ends: *"Almost ready! Run 'butler doctor' to download the AI models (~6GB). This only happens once."*
- [ ] Writes `~/.butler/uninstall.sh`, tells user where it is
- [ ] Writes `install-manifest.json` as it runs

#### `butler doctor` — First Run & Health Check
- [ ] Detects missing dependencies with emoji status: ✅ / ⚠️ / ❌
- [ ] If Ollama missing: *"Butler thinks locally on your Mac using Ollama. Installing now — safe and private."* Runs Ollama installer with explicit confirmation. `--skip-ollama` flag.
- [ ] `ollama pull llama3.1:8b` with progress bar — resumable if interrupted
- [ ] parakeet-mlx model download with progress bar — resumable
- [ ] Hardware check: warns clearly if not Apple Silicon
- [ ] Reports `vault.path`, enabled plugins, last event timestamp
- [ ] Reports recovered tasks from previous crash (if any)
- [ ] Reports throttle state: *"⏸ Background tasks paused (low battery)"* if applicable

#### launchd
- [ ] `WatchPaths` plist watches voice memo drop folder (default `~/Desktop/VoiceMemos/`)
- [ ] On new file: calls `plugins/voice-input/python-runners/transcribe.py {filepath}`
- [ ] Keepalive plist for main butler + huey worker process

#### Plugin: `voice-input`
- [ ] `python-runners/transcribe.py {filepath}` — parakeet-mlx, enqueues huey task
- [ ] `plugin/main.py` — subscribes `input.received`, validates, passes to pipeline
- [ ] `user-data.json`: `watch_folder`, `delete_after_transcription` (default true), `archive_folder`
- [ ] `README.md` first line: *"Watches a folder for new audio files and transcribes them into your daily journal."*

#### Plugin: `daily-writer`
- [ ] Subscribes to `note.routed` (passthrough from `input.received` until Stage 5)
- [ ] Uses `core/safe_write.py` for all file writes — never writes directly
- [ ] Appends timestamped block to `{vault.path}/journals/daily/YYYY-MM-DD.md`
- [ ] Obsidian frontmatter on first write of day: `date`, `tags: [journal, butler-input]`, `source`
- [ ] Emits `note.written` with `{path, ts, word_count, source}`
- [ ] Registers write receipt with `vault_watcher` so FSEvents ignores Butler's own writes
- [ ] `user-data.json`: `date_format`, `tag_prefix`
- [ ] `README.md` first line: *"Saves your notes to today's journal file with timestamps and Obsidian formatting."*

#### Core
- [ ] Huey SQLite worker starts with main process — task durability on crash is automatic
- [ ] `DRY_RUN=true`: pipeline runs, no disk writes, no LLM calls, `[DRY RUN]` prefix on every action log line
- [ ] `butler status`: process running y/n, plugins loaded, last event timestamp, vault path, throttle state, recovered task count

- [ ] **Git tag:** `v2.1-base-voice`

---

### Stage 2 — Notifications & Sounds
**Exit condition:** macOS notification + sound fires on `note.written`. Fully removable.

#### Plugin: `notifications`
- [ ] `optional_dependencies` only — zero hard dependencies on it
- [ ] Subscribes to configurable event list; default: `note.written`, `pipeline.error`
- [ ] `osascript` banner with `{variable}` template per event
- [ ] `afplay` sounds: success / waiting / failure categories. Per-category `.aiff` configurable.
- [ ] Ships 3 default short sounds in `plugin/sounds/`
- [ ] `user-data.json`: `enabled_events`, `sound_enabled`, per-event sound overrides
- [ ] `README.md` first line: *"Plays a sound and shows a notification on your Mac when Butler does something."*

- [ ] **Git tag:** `v2.2-notifications`

---

### Stage 3 — Telegram + Alfred + Apple Notes + PKG Installer
**Exit condition:** Your mom sends a Telegram voice message → it appears in her journal. `.pkg` works on a fresh Mac.

#### Plugin: `telegram-input`
- [ ] Long-poll bot process managed by its own launchd plist (added at plugin enable)
- [ ] Text message → `input.received` with `source: telegram`
- [ ] Voice message → temp file → parakeet transcription → `input.received`
- [ ] `/ask {query}` → stub: *"Memory search coming soon! 🔍"* (until Stage 6)
- [ ] `/help` → friendly list with emoji + plain-English descriptions
- [ ] `/status` → *"🫖 Butler is running. Last note saved at 3:42pm."*
- [ ] Setup wizard uses `tg://resolve?domain=BotFather` deep link — user clicks, Telegram opens with context ready. No manual command typing.
- [ ] `butler plugin setup telegram-input`: shows deep link as clickable URL + QR code in terminal, waits for token paste, sends test message to confirm
- [ ] `user-data.json`: `bot_token`, `allowed_user_ids`, `voice_transcription_enabled`
- [ ] `README.md` first line: *"Lets you send notes and voice messages to Butler via Telegram from any device."*

#### Plugin: `alfred-input`
- [ ] `python-runners/diary-input.py {text}` → `input.received` with `source: alfred`
- [ ] Ships `butler-alfred.alfredworkflow` for one-click import
- [ ] `README.md` first line: *"Lets you send a quick note to Butler from Alfred with a keyboard shortcut."*

#### Plugin: `apple-notes-input` *(optional, off by default)*
- [ ] Polls named Apple Notes folder via AppleScript on `heartbeat.tick`
- [ ] New notes since last poll → `input.received` with `source: apple-notes`
- [ ] Marks processed notes with "butler-processed" tag via AppleScript
- [ ] Reference code: `Reference Code/Apple Notes Handler` — review and stabilise before use
- [ ] `README.md` first line: *"Watches an Apple Notes folder and sends new notes to Butler automatically."*

#### CLI addition
- [ ] `butler plugin list` — all plugins with tags, enabled status, one-line description
- [ ] `butler plugin list --tag media-handler` — filtered by tag
- [ ] `butler plugin enable {id}` / `butler plugin disable {id}`

#### Non-technical install path
- [ ] `scripts/build-pkg.sh` — wraps install.sh into macOS `.pkg` using `pkgbuild` + `productbuild`
- [ ] PKG screens: Welcome (butler personality), Notes Folder (native folder chooser), Done
- [ ] PKG does NOT include models — `butler doctor` handles that on first run
- [ ] Releases: `curl` one-liner (developers) + `butler-installer.pkg` (everyone else)
- [ ] README labels both clearly: *"For developers"* / *"For everyone else"*

- [ ] **Git tag:** `v2.3-telegram-and-pkg`

---

### Stage 4 — LLM Basics (Text Polish + Day Digest)
**Exit condition:** Notes optionally polished. End-of-day digest written. All LLM tasks respect `@throttled`.

#### Core addition: prompt system
- [ ] `core/prompts.py` — `.md` templates with YAML frontmatter, renders with variable dict, appends to prompt-history `.jsonl`
- [ ] `DRY_RUN=true`: no writes, no LLM calls, `[DRY RUN]` prefix on every action log line
- [ ] All LLM calls wrapped with `@throttled` — if system is busy, defer to next heartbeat

#### Plugin: `text-polish` *(optional, off by default)*
- [ ] Inserts into pipeline between `input.received` and `note.routed`
- [ ] `@throttled` — if deferred, text passes through unpolished (graceful degradation, never blocks)
- [ ] If Ollama unavailable: pass through, log warning, fire `pipeline.error` event. Never blocks pipeline.
- [ ] `user-data.json`: `enabled`, `model` (default `llama3.1:8b`), `aggressiveness: [light | standard]`
- [ ] `README.md` first line: *"Gently cleans up voice notes — fixing filler words and run-on sentences — before saving."*

#### Plugin: `day-digest`
- [ ] Subscribes to `day.ended` (core emits at configurable time, default 23:30)
- [ ] `@throttled` — defers if system busy; retries on heartbeat until it runs
- [ ] Reads today's daily `.md`, LLM summarises
- [ ] Writes `{vault.path}/journals/digests/YYYY-MM-DD-digest.md` via `safe_write`
- [ ] Appends `[[YYYY-MM-DD-digest]]` wikilink to daily file via `safe_write`
- [ ] If `telegram-input` capability available: optionally sends digest (safe call, no hard dep)
- [ ] `user-data.json`: `send_time`, `send_to_telegram`, `digest_length: [brief | standard | detailed]`
- [ ] `README.md` first line: *"Writes a summary of your day's notes each evening and optionally sends it to you on Telegram."*

- [ ] **Git tag:** `v2.4-llm-basics`

---

### Stage 5 — Note Router
**Exit condition:** Notes classified and routed to project files. Daily file unchanged as fallback.

#### Plugin: `note-router`
- [ ] Inserts after `text-polish` (or `input.received` if polish disabled)
- [ ] `@throttled` — if deferred, routes to `daily` by default (safe fallback)
- [ ] LLM classifier returns: `{destination: "daily"|"project", project_slug: str|null, note_type: "log"|"idea"|"reference"}`
- [ ] `project` → appends to `{vault.path}/projects/{project_slug}.md` via `safe_write` + wikilink in daily
- [ ] New project files: frontmatter `project`, `created`, `tags: [project, butler-routed]`
- [ ] Deduplication: SHA-256 of raw text in `dedup.db`; exact match within 24h → warn + skip
- [ ] Every classification call written to prompt-history
- [ ] `user-data.json`: `enabled`, `known_projects` (hints classifier), `default_destination`
- [ ] `README.md` first line: *"Automatically files notes to the right project instead of always putting everything in your daily journal."*

- [ ] **Git tag:** `v2.5-note-router`

---

### Stage 6 — Memory & Search
**Exit condition:** `butler ask "query"` returns answer. Alfred search works. Telegram `/ask` works.

#### Plugin: `memory`
- [ ] `plugin/backend.py` — `MemoryBackend` ABC: `add(text, metadata)`, `search(query, n)`, `delete(id)`
- [ ] `plugin/chroma_backend.py` — `ChromaBackend(MemoryBackend)` in `~/.butler/data/memory/`
- [ ] **Migration path:** `PgvectorBackend` implements same ABC. Swap via `user-data.json` `backend: chroma|pgvector`. Nothing else changes.
- [ ] Indexing uses `core/vault_watcher.py` hash cache — only re-embeds changed files
- [ ] All embedding generation wrapped with `@throttled`
- [ ] Search: semantic (ChromaDB) + grep hybrid for better recall
- [ ] Results include `source` metadata shown to user: *"From: voice memo · 14 Feb"*
- [ ] On `note.written`: adds note to memory with `{date, source, project, word_count}` metadata
- [ ] On `vault.file.changed`: re-indexes that file only (user manual edit)
- [ ] Read-only folder indexing: `index_folders` + `exclude_patterns` in `user-data.json`
- [ ] `butler memory reindex` — walks folders, queues changed files only (throttled), progress bar
- [ ] `capabilities.json`: `memory.search(query, n)` and `memory.add_context(prompt)`
- [ ] `python-runners/search.py {query}` → JSON stdout
- [ ] `alfred-runner.json`: "Ask Butler" entry
- [ ] Telegram `/ask {query}` now live
- [ ] `README.md` first line: *"Gives Butler a searchable memory of everything you've written, so you can ask questions and get answers."*

- [ ] **Git tag:** `v2.6-memory`

---

### Stage 7 — Wake Word + Heartbeat + Reflection
**Exit condition:** "Hey Butler" triggers recording. Nightly reflection runs without user input.

#### Core addition: heartbeat
- [ ] `core/heartbeat.py` — configurable tick (default 5 min), emits `heartbeat.tick` with `{ts, idle_seconds, time_of_day}`
- [ ] `@night_only` decorator restricts handler to configurable hours (default 22:00–06:00)
- [ ] Heartbeat also triggers: Inbox.md retry scan, throttle gate re-evaluation, deferred task re-queue

#### Plugin: `wake-word`
- [ ] `openwakeword` — local, no cloud, lightweight background process via launchd plist
- [ ] On "Hey Butler" → start recording → on silence → `input.received` with `source: wake-word`
- [ ] Feedback: menubar icon changes (if menubar enabled), brief tone via `afplay`
- [ ] `user-data.json`: `wake_phrase`, `sensitivity`, `feedback_sound`
- [ ] `README.md` first line: *"Lets you trigger Butler by saying 'Hey Butler' out loud — no keyboard needed."*

#### Plugin: `reflection`
- [ ] Subscribes to `heartbeat.tick` with `@night_only`
- [ ] `@throttled` — defers if system busy, retries on next night tick
- [ ] Reads last 7 days of daily files + last 50 memory entries
- [ ] LLM: open questions, patterns noticed, loose threads
- [ ] Writes `{vault.path}/journals/reflections/YYYY-MM-DD-reflection.md` via `safe_write`, with wikilinks to related daily files
- [ ] Emits `reflection.ready`
- [ ] `user-data.json`: `run_time` (default "23:00"), `lookback_days` (default 7)
- [ ] `README.md` first line: *"Writes a thoughtful reflection each night, noticing patterns in what you've been thinking about."*

- [ ] **Git tag:** `v2.7-wake-and-reflect`

---

### Stage 8 — Menubar App
**Exit condition:** Butler icon in menu bar shows recent events. Quick-send works. Opens today's journal.

#### Plugin: `menubar`
- [ ] `rumps` + `py2app`. Separate process communicates with butler daemon by polling `~/.butler/data/cache/recent-events.json` (rolling last 20 events, butler daemon writes after each event)
- [ ] Menubar icon: 🫖 idle, ⏳ processing, ⏸ throttled, ❌ error
- [ ] Dropdown:
  - Last 5 pipeline events with emoji + relative timestamp: `✅ Note saved · 2 min ago`
  - Separator
  - Text field: *"Quick note..."* → `input.received` on Enter
  - *"Ask Butler..."* → text field → `memory.search` capability → result in rumps alert
  - Separator
  - *"Open Today's Journal"* → `open obsidian://open?vault=...&file=journals/daily/YYYY-MM-DD`
  - *"Open Butler Config"* → launches `butler config` TUI in Terminal
  - Separator
  - *"Butler v2.x.x"* (non-clickable version string)
- [ ] Throttle state shown in icon tooltip: *"⏸ Paused — low battery"*
- [ ] `user-data.json`: `max_events_shown` (default 5), `poll_interval_seconds` (default 30)
- [ ] `README.md` first line: *"Shows Butler's recent activity in your Mac menu bar and lets you send quick notes without opening anything."*

- [ ] **Git tag:** `v2.8-menubar`

---

### Stage 9 — Enrichment Plugins
**Exit condition:** All four plugins work independently. Each can be toggled without affecting others.

#### Plugin: `guided-conversation`
- [ ] Initiates prompted Telegram conversation on schedule or `/journal` command
- [ ] Configurable prompt sequences stored as `.md` templates in `plugin/conversations/`
- [ ] Times out gracefully if no response within `timeout_minutes`
- [ ] Summarises → appends to daily journal via `safe_write` with `source: guided-conversation` tag
- [ ] `user-data.json`: `schedule` (default null), `conversation_template`, `timeout_minutes`
- [ ] `README.md` first line: *"Guides you through a short journaling conversation on Telegram and saves the summary to your daily notes."*

#### Plugin: `action-items`
- [ ] Subscribes to `note.written`
- [ ] `@throttled` LLM extraction
- [ ] LLM instructed to distinguish `[x] completed` tasks from `[ ] open` tasks — only open tasks extracted
- [ ] Appends to `{vault.path}/action-items.md` with date + source wikilink via `safe_write`
- [ ] Does not mutate original note — extraction only
- [ ] `user-data.json`: `extraction_threshold`, `phrases_to_watch`
- [ ] `README.md` first line: *"Extracts open action items from your notes and collects them in a single [[action-items]] file."*

#### Plugin: `contradiction-detector`
- [ ] Subscribes to `note.written`
- [ ] `@throttled` — skips silently if system busy, runs on next heartbeat
- [ ] Calls `memory.search`, LLM evaluates genuine contradiction vs. evolution of thinking
- [ ] If found: appends gentle flag to bottom of new note via `safe_write`: `> 🔄 This might contradict: [[older-note-date]]`
- [ ] `user-data.json`: `sensitivity: [low | medium | high]`, `enabled`
- [ ] `README.md` first line: *"Notices when a new note contradicts something you've written before and flags it gently in your journal."*

#### Plugin: `morning-briefing`
- [ ] Fires at configured time via `heartbeat.tick` check
- [ ] Pulls: open action items (unchecked only — relies on `action-items` plugin state), last 3 days' themes from memory, one reflection question
- [ ] Sends via Telegram as friendly formatted message
- [ ] `user-data.json`: `send_time` (default "08:00"), `lookback_days` (default 3)
- [ ] `README.md` first line: *"Sends you a friendly morning message on Telegram with your open loops and a question to start your day."*

- [ ] **Git tag:** `v2.9-enrichment`

---

### Stage 10 — Deductions + Smarter Digest
**Exit condition:** Temporal patterns surfaced. Smarter digest uses memory context.

#### Plugin: `deductions`
- [ ] Subscribes to `day.ended` and `reflection.ready`
- [ ] `@throttled` — defers until system is idle
- [ ] `memory.search` for cross-date thematic clusters
- [ ] LLM: patterns / hypotheses / contradictions across time
- [ ] Writes `{vault.path}/journals/deductions/YYYY-MM-DD-deductions.md` via `safe_write`
- [ ] Deductions added to memory tagged `type: deduction`
- [ ] Full `DRY_RUN` support
- [ ] `README.md` first line: *"Notices patterns across your notes over time and surfaces hypotheses you might not have seen yourself."*

#### Plugin: `smarter-digest` *(supersedes `day-digest`)*
- [ ] `manifest.json`: `"supersedes": ["day-digest"]` — plugin loader disables `day-digest` if both enabled
- [ ] Pulls memory + deductions for temporal-context digest
- [ ] Surfaces: changed since last week, recurring themes, open loops
- [ ] `README.md` first line: *"A richer daily digest that connects today's notes to your longer patterns."*

- [ ] **Git tag:** `v2.10-deductions`

---

### Stage 11 — Link Resolvers (Readwise + YouTube)
**Exit condition:** Pasting a URL routes correctly. YouTube transcript filed in vault.

#### URL Detection (core pipeline stage)
- [ ] New pipeline stage `url-detector`: scans incoming text for URLs, emits `link.detected` with `{url, source_text, detected_type: "youtube"|"article"|"unknown"}`
- [ ] Non-URL text passes through unchanged

#### Plugin: `readwise` *(optional, off by default)*
- [ ] Tags: `media-handler`, `link-resolver`, `optional`
- [ ] Subscribes to `link.detected` where `detected_type != "youtube"`
- [ ] Sends URL to Readwise API
- [ ] `user-data.json`: `api_token`, `send_highlights`, `tag_prefix`
- [ ] `README.md` first line: *"Automatically sends article URLs and links to your Readwise account."*

#### Plugin: `youtube-to-reference` *(optional, off by default)*
- [ ] Tags: `media-handler`, `link-resolver`, `llm-required`, `optional`
- [ ] Subscribes to `link.detected` where `detected_type == "youtube"`
- [ ] Reference code: `Reference Code/Youtube Handler` — review and integrate
- [ ] `@throttled` — transcription and summarisation deferred when system busy
- [ ] Downloads audio via `yt-dlp`, transcribes via parakeet-mlx in chunks
- [ ] Writes `{vault.path}/reference/youtube/{video-slug}.md` via `safe_write` with frontmatter: `title`, `url`, `date`, `duration`, `tags: [youtube, reference, transcript]`
- [ ] If `auto_summarise` enabled: LLM summary → appends brief note to daily journal via `safe_write` with wikilink to transcript
- [ ] `user-data.json`: `auto_summarise` (default true), `output_folder`, `keep_audio` (default false)
- [ ] `README.md` first line: *"Downloads YouTube videos, transcribes them, and saves the transcript to your vault."*

- [ ] **Git tag:** `v2.11-link-resolvers`

---

### Stage 12 — Plugin Manager + Config TUI + Transcription Confidence
**Exit condition:** `butler config` is pleasant to use. Plugin manager shows tags. Confidence highlights work.

#### Textual TUI
- [ ] `butler config` — plugins grouped by tag in collapsible sections, enable/disable toggles, per-plugin `user-data.json` fields as typed form
- [ ] Each plugin shows: name, README first line as description, tag badges, enabled toggle
- [ ] `butler prompts` tab — today's `.jsonl` table; select row → full rendered prompt + variables
- [ ] `butler logs` tab — tail with level filter
- [ ] Fallback: if `textual` not installed → `$EDITOR` on `config.yaml`

#### Plugin: `plugin-manager`
- [ ] `butler plugins` command — tag-grouped browsable list
- [ ] Future community registry integration point
- [ ] `README.md` first line: *"Browse, enable, and disable Butler plugins grouped by what they do."*

#### Plugin: `transcription-confidence`
- [ ] parakeet-mlx per-segment confidence scores
- [ ] Below threshold → wrapped in `==highlight==` in saved note
- [ ] Frontmatter flag: `has_low_confidence: true` for Obsidian filtering
- [ ] `user-data.json`: `confidence_threshold` (default 0.75), `highlight_style`
- [ ] `README.md` first line: *"Highlights parts of transcribed notes that Butler wasn't sure about, so you can review them."*

#### Dev tooling final pass
- [ ] `butler dev validate {plugin-id}` — full mismatch report
- [ ] `butler dev test --dry-run` — synthetic input, full pipeline trace with `[DRY RUN]`
- [ ] `butler doctor` — full dependency + hardware check, throttle state, vault health

- [ ] **Git tag:** `v2.12-plugin-manager`

---

### Stage 13 — Distribution & Polish
**Exit condition:** Non-technical user installs in under 10 minutes. Your mom uses it successfully.

- [ ] Final `install.sh` pass — test on clean macOS account
- [ ] `.pkg` tested with non-technical user (your mom)
- [ ] `butler doctor` first-run flow tested end-to-end on clean account
- [ ] README: *"For developers"* (curl) + *"For everyone else"* (.pkg) sections
- [ ] Plugin catalogue in README from manifest descriptions
- [ ] GitHub Actions: tag push → builds `.pkg` → attaches to release
- [ ] Uninstall tested: `--keep-config` leaves vault untouched, `--keep-models` leaves Ollama
- [ ] `butler doctor` passes green on a fresh install

- [ ] **Git tag:** `v2.13-distribution`

---

## Event Taxonomy (Reference)

| Event | Emitter | Payload |
|---|---|---|
| `input.received` | any input plugin | `{text, source, ts, raw_file?}` |
| `link.detected` | url-detector pipeline stage | `{url, source_text, detected_type}` |
| `note.routed` | pipeline / note-router | `{text, destination, project_slug?, note_type?}` |
| `note.written` | daily-writer | `{path, ts, word_count, source}` |
| `vault.file.changed` | vault_watcher | `{path, old_hash, new_hash, ts}` |
| `pipeline.error` | core | `{stage, error, input_preview}` |
| `heartbeat.tick` | core | `{ts, idle_seconds, time_of_day}` |
| `day.ended` | core | `{date, daily_file_path}` |
| `reflection.ready` | reflection plugin | `{path, ts}` |
| `Events.TEST_PING` | dev tooling | `{}` |

---

## Plugin Tags (Reference)

| Tag | Meaning |
|---|---|
| `input` | Receives data from outside (voice, Telegram, Alfred, etc.) |
| `output` | Writes data somewhere (vault, Telegram, Readwise) |
| `core` | Required or near-required for basic function |
| `llm-required` | Will not work without Ollama running |
| `media-handler` | Processes media files or URLs |
| `link-resolver` | Handles incoming URLs |
| `telegram-required` | Depends on the telegram-input plugin being enabled |
| `audio` | Deals with audio recording or transcription |
| `ux` | User-facing interface or experience feature |
| `optional` | Safe to disable; degrades gracefully |
| `dev` | Developer tooling; not needed for end-user function |

---

## Capabilities Registry (Reference)

```python
# Safe cross-plugin call — returns None + logs warning if plugin disabled. Never raises.
result = bus.capabilities.call("memory.search", query="what did I decide about X", n=5)
context = bus.capabilities.call("memory.add_context", prompt=my_prompt)
```

---

## Notes for Agentic Coding Workflow (GSD)

- Each Stage = one GSD task block with a named exit condition
- Begin every stage: read existing plugin READMEs + core module docstrings
- Run `butler dev validate` on all plugins before tagging
- Test `DRY_RUN=true` at every stage from Stage 4 onwards
- `plugins/example-plugin/` must pass `dev validate` at every stage (regression canary)
- Never modify core between stages unless a stage explicitly lists a core addition
- If a plugin requires an unlisted core change: stop, reconsider the event/capability design
- All LLM calls and background tasks must use `@throttled` from Stage 4 onwards — no exceptions
- All vault file writes must use `core/safe_write.py` from Stage 1 onwards — no exceptions
- Every new feature must satisfy both: *"is this good architecture?"* AND *"could a non-technical user understand what this does?"*
- Reference code in `Reference Code/` — review before implementing Apple Notes, YouTube, and Menubar plugins
