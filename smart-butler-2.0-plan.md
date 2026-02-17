# Smart Butler 2.0 — Project Plan

## Architecture Decisions (Locked)

### Core Pattern
- **Event Bus** (`blinker`): lifecycle events — `input.received`, `note.routed`, `heartbeat.tick`, `day.ended`, etc.
- **Pipeline**: data transforms — transcription → cleaning → routing → saving. Plugins hook into pipeline stages.
- **Service Locator** (via `capabilities.json`): plugins declare callable functions; other plugins and Alfred can discover and invoke them.

### Tech Stack
- **Language**: Python 3.11+
- **Event bus**: `blinker`
- **Task queue**: `huey` with SQLite backend (zero extra services, packageable)
- **Config**: plain YAML + `PyYAML` + `dataclasses`. No Pydantic.
- **Config UI**: `textual` TUI, falls back to direct YAML editing
- **Vector memory**: `chromadb` (local), behind a `MemoryBackend` ABC for future pgvector swap
- **Folder watch**: `launchd` with `WatchPaths` (reliable, system-level, not Automator)
- **Notifications**: macOS `osascript` for banners + `afplay` for sounds (both wrapped in notification plugin)
- **Logging**: single logger, multiple handlers (file = verbose, desktop = filtered notify plugin)
- **Version control**: git tags per stage (`v2.0-skeleton`, `v2.1-base-voice`, etc.)

### Plugin Contract
Every plugin exposes exactly one entry point:
```python
def register(bus, config):
    ...
```
Core calls nothing else. If removing a plugin breaks core, that is a bug in core.

### Plugin Folder Structure
```
plugins/
  {plugin-id}/
    manifest.json        # identity, version, dependencies, enabled flag
    hooks.json           # events listened to + emitted (declared manually, validated by dev-script)
    capabilities.json    # callable functions (compiled from docstrings by dev-script)
    alfred-runner.json   # alfred script filter entries
    python-runners/      # CLI-callable scripts (alfred, terminal, keyboard maestro)
    plugin/              # plugin source
      main.py            # register(bus, config) lives here
      helpers.py
      models.py          # dataclasses only
    tests/
    README.md
```

### manifest.json (Obsidian-style extended)
```json
{
  "id": "voice-input",
  "name": "Voice Input",
  "version": "1.0.0",
  "description": "Watches a folder for audio files, transcribes with parakeet-mlx",
  "author": "you",
  "min_butler_version": "2.0.0",
  "dependencies": [],
  "optional_dependencies": ["notifications"],
  "tags": ["input", "audio"],
  "enabled": true
}
```

### hooks.json
```json
{
  "listens": [
    { "event": "heartbeat.tick", "description": "Checks watch folder for new audio files" }
  ],
  "emits": [
    { "event": "input.received", "description": "Fired when transcription is complete, carries raw text" }
  ]
}
```

### capabilities.json (compiled from docstrings by dev-script)
```json
{
  "capabilities": [
    {
      "id": "memory.search",
      "description": "Semantic + grep search across all indexed notes",
      "callable": "plugin.main.search",
      "params": { "query": "str", "n": "int" },
      "returns": "list[dict]"
    }
  ]
}
```

### Directory Layout (Runtime)
```
~/.butler/
  config/
    config.yaml          # main config
    plugins/             # per-plugin config overrides
  data/
    daily/               # daily note .md files (single source of truth)
    prompt-history/      # YYYY-MM-DD.jsonl — full rendered prompts with variables
    memory/              # chromadb files
    cache/               # plugin caches
  logs/
    butler.log           # verbose, all levels
    butler-errors.log    # ERROR and above only
  install-manifest.json  # written at install time, read by uninstaller
```

### Prompt History Format
One JSON line per LLM call:
```json
{
  "ts": "2025-02-17T14:32:00",
  "plugin": "note-router",
  "template": "classify_note",
  "variables": {"raw_text": "...", "date": "2025-02-17"},
  "rendered": "full prompt string after injection",
  "model": "gpt-4o-mini",
  "response_preview": "first 200 chars"
}
```

### Uninstall Strategy
- `install.sh` writes every file/plist/symlink it touches to `~/.butler/install-manifest.json`
- `uninstall.sh` reads this manifest and removes each entry in reverse order
- `--keep-config` flag preserves `~/.butler/config/` and `~/.butler/data/`
- Model downloads tracked in manifest (can be optionally removed)

---

## Stages

### Stage 0 — Skeleton & Dev Tooling
**Exit condition**: empty plugin loads and logs cleanly; dev-script validates a plugin folder.

- [ ] Initialise git repo, add `.gitignore`, tag `v2.0-dev-start`
- [ ] Create top-level folder structure: `core/`, `plugins/`, `scripts/`, `tests/`
- [ ] `core/bus.py` — thin `blinker` wrapper with typed event names as string constants
- [ ] `core/config.py` — YAML loader, merges core config + per-plugin configs, returns plain dataclass tree
- [ ] `core/plugin_loader.py` — scans `plugins/` folder, reads `manifest.json`, calls `register(bus, config)` for enabled plugins
- [ ] `core/logger.py` — single logger, file handler (verbose), stderr handler (warnings+). Format: `[TIME] [LEVEL] [plugin-id] message`
- [ ] `core/pipeline.py` — ordered list of transform functions; plugins can insert named stages
- [ ] `core/capabilities_registry.py` — dict of discovered capabilities; safe `call(id, **kwargs)` returns None if plugin disabled, never raises
- [ ] `scripts/dev-validate.py` — validates a plugin folder: checks manifest keys, compares hooks.json to blinker subscriptions found in code, compiles capabilities.json from docstrings
- [ ] `plugins/example-plugin/` — logs "hello" on a test event; regression canary for all future stages
- [ ] Git tag: `v2.0-skeleton`

---

### Stage 1 — Base Engine (Voice Input → Daily File)
**Exit condition**: drop an audio file in watch folder → transcription appears in today's `.md` file. No LLM.

**launchd setup**:
- [ ] `scripts/install.sh` — creates `~/.butler/`, copies config template, installs launchd `WatchPaths` plist, writes `install-manifest.json`
- [ ] `scripts/uninstall.sh` — reads manifest, removes everything, respects `--keep-config`
- [ ] launchd plist watches `~/Desktop/VoiceMemos/` (configurable), calls `scripts/on-new-audio.sh {filepath}`
- [ ] `on-new-audio.sh` calls `plugins/voice-input/python-runners/transcribe.py {filepath}`

**Plugin: `voice-input`**:
- [ ] `python-runners/transcribe.py` — runs parakeet-mlx on file, enqueues huey task with transcription text
- [ ] `plugin/main.py register()` — subscribes to `input.received`, validates payload, passes to pipeline

**Plugin: `daily-writer`**:
- [ ] Subscribes to `note.routed` (acts as direct passthrough from `input.received` until note-router is added in Stage 5)
- [ ] Appends timestamped text block to `~/.butler/data/daily/YYYY-MM-DD.md`
- [ ] Emits `note.written` with `{path, ts, word_count}`
- [ ] Configurable: delete source audio / move to archive folder on `note.written`

**Core**:
- [ ] Huey SQLite worker starts with core process
- [ ] Default pipeline: `input.received → note.routed` passthrough with empty transform list

- [ ] Git tag: `v2.1-base-voice`

---

### Stage 2 — Notifications & Sounds
**Exit condition**: macOS notification with sound fires on `note.written`. Fully removable without breaking anything.

**Plugin: `notifications`**:
- [ ] Listed as `optional_dependencies` in other plugin manifests — nothing hard-depends on it
- [ ] Subscribes to configurable event list (default: `note.written`, `pipeline.error`)
- [ ] Fires `osascript` notification banner with configurable title/body template per event
- [ ] Sounds via `afplay`: configurable `.aiff` file per event category (success / waiting / failure)
- [ ] Ships 3 default short royalty-free sounds in `plugin/sounds/`
- [ ] Disable by removing from `plugins.enabled` — zero effect on other plugins

- [ ] Git tag: `v2.2-notifications`

---

### Stage 3 — Input Channels (Alfred + Telegram + Apple Notes)
**Exit condition**: text reaches daily file from Alfred, Telegram, and Apple Notes. Voice still works.

**Plugin: `alfred-input`**:
- [ ] `python-runners/diary-input.py {text}` — enqueues `input.received` with `source: alfred`
- [ ] `alfred-runner.json` entry for Alfred script filter
- [ ] Ships `.alfredworkflow` import file in plugin root

**Plugin: `telegram-input`** *(optional, disabled by default)*:
- [ ] `python-runners/telegram-bot.py` — long-poll bot, managed by its own launchd plist (added at plugin enable time)
- [ ] `/note {text}` → `input.received`; `/ask {query}` → stubbed until Stage 6
- [ ] `butler plugin enable telegram-input` writes plist + adds to config

**Plugin: `apple-notes-input`** *(optional, disabled by default)*:
- [ ] Polls a named Apple Notes folder via AppleScript on `heartbeat.tick`
- [ ] New notes since last poll → `input.received` with `source: apple-notes`
- [ ] Appends a "processed" tag to handled notes via AppleScript to avoid reprocessing

**Core addition**:
- [ ] `butler` CLI (`scripts/butler.py`): `status`, `plugin list`, `plugin enable {id}`, `plugin disable {id}`, `logs`, `config edit`

- [ ] Git tag: `v2.3-channels`

---

### Stage 4 — LLM Basics (Text Polish + Day Digest)
**Exit condition**: notes optionally polished by LLM. End-of-day digest written. DRY_RUN works.

**Core addition — prompt system**:
- [ ] `core/prompts.py` — loads `.md` templates from `prompts/` with YAML frontmatter (`plugin`, `version`, `description`)
- [ ] Renders with variable dict; writes full record to `~/.butler/prompt-history/YYYY-MM-DD.jsonl`
- [ ] `DRY_RUN=true`: pipeline runs, no disk writes, no LLM calls, `[DRY RUN]` prefix on all log lines

**Plugin: `text-polish`** *(optional)*:
- [ ] Inserts into pipeline between `input.received` and `note.routed`
- [ ] LLM call (configurable: ollama / OpenAI-compatible endpoint)
- [ ] If LLM unavailable → pass through unchanged, log warning. Never blocks pipeline.
- [ ] Config: `enabled`, `model`, `endpoint`, `aggressiveness: [light | standard]`

**Plugin: `day-digest`**:
- [ ] Subscribes to `day.ended` (core emits at configurable time, default 23:30)
- [ ] Reads today's daily `.md`, calls LLM for summary
- [ ] Writes to `~/.butler/data/digests/YYYY-MM-DD-digest.md`
- [ ] If `telegram-input` capability available: optionally sends digest (safe capability call, not hard dep)

- [ ] Git tag: `v2.4-llm-basics`

---

### Stage 5 — Note Router
**Exit condition**: notes classified and routed to project files. Daily file unchanged as base fallback.

**Plugin: `note-router`**:
- [ ] Inserts into pipeline after `text-polish` (or after `input.received` if polish disabled)
- [ ] LLM classifier returns: `{destination: "daily"|"project", project_slug: str|null, note_type: "log"|"idea"|"reference"}`
- [ ] `daily` → standard flow unchanged
- [ ] `project` → appends to `~/.butler/data/projects/{project_slug}.md` + link line in daily file
- [ ] Deduplication: SHA-256 hash of raw text in daily cache; exact match within 24h → warn + skip
- [ ] Every classification call written to prompt-history

- [ ] Git tag: `v2.5-note-router`

---

### Stage 6 — Memory & Search
**Exit condition**: `butler ask "query"` returns answer. Alfred search works. Telegram `/ask` works.

**Plugin: `memory`**:
- [ ] `plugin/backend.py` — `MemoryBackend` ABC: `add(text, metadata)`, `search(query, n)`, `delete(id)`
- [ ] `plugin/chroma_backend.py` — `ChromaBackend` implements ABC, stores in `~/.butler/data/memory/`
- [ ] Future migration path: write `PgvectorBackend` implementing same ABC, swap in config — nothing else changes
- [ ] On `note.written`: adds note to memory with `{date, source, project}` metadata
- [ ] Read-only folder indexing: config lists folders + exclude patterns (e.g. `**/Templates/**`)
- [ ] `butler memory reindex` — walks folders, bulk-adds to ChromaDB
- [ ] `capabilities.json` exposes: `memory.search(query, n)` and `memory.add_context(prompt)`
- [ ] `python-runners/search.py {query}` — JSON output, callable from Alfred
- [ ] `alfred-runner.json`: "Ask Butler" entry

- [ ] Git tag: `v2.6-memory`

---

### Stage 7 — Heartbeat & Reflection
**Exit condition**: nightly reflection runs without user input. Idle detection works.

**Core addition**:
- [ ] `core/heartbeat.py` — configurable tick (default 5 min), emits `heartbeat.tick` with `{ts, idle_seconds, time_of_day}`
- [ ] Night gate decorator: `@night_only` restricts handler to configurable hours (default 22:00–06:00)
- [ ] launchd keepalive plist ensures main process stays running

**Plugin: `reflection`**:
- [ ] Subscribes to `heartbeat.tick` with `@night_only`
- [ ] Reads recent daily files + recent memory entries
- [ ] LLM generates reflection: open questions, patterns, loose threads
- [ ] Writes to `~/.butler/data/reflections/YYYY-MM-DD.md`
- [ ] Emits `reflection.ready` for notifications plugin

- [ ] Git tag: `v2.7-heartbeat`

---

### Stage 8 — Deductions
**Exit condition**: temporal patterns and hypotheses surfaced from accumulated memory.

**Plugin: `deductions`**:
- [ ] Subscribes to `day.ended` and `reflection.ready`
- [ ] Calls `memory.search` capability for thematically related notes across time
- [ ] LLM: given N cross-date notes, identify patterns / hypotheses / contradictions
- [ ] Writes to `~/.butler/data/deductions/YYYY-MM-DD.md`
- [ ] Deductions added to memory tagged `type: deduction`
- [ ] Full `DRY_RUN` support

**Plugin: `smarter-digest`** *(replaces `day-digest`)*:
- [ ] Pulls memory + deductions for temporal-context digest
- [ ] Surfaces what changed since last week, recurring themes

- [ ] Git tag: `v2.8-deductions`

---

### Stage 9 — Config TUI & Prompt Manager
**Exit condition**: `butler config` and `butler prompts` are interactive and useful.

**Textual TUI**:
- [ ] `butler config` — plugin checkboxes, per-plugin key settings, saves to `config.yaml`
- [ ] `butler prompts` — table from today's `.jsonl`; select row → full rendered prompt + variable values shown
- [ ] `butler logs` — tail with level filter dropdown
- [ ] Fallback: if `textual` not installed, open `$EDITOR` on config file

**Dev tooling**:
- [ ] `butler dev validate {plugin-id}` — hook/capability mismatch report
- [ ] `butler dev test {plugin-id} --dry-run` — loads single plugin, fires synthetic event, traces pipeline

- [ ] Git tag: `v2.9-tui`

---

### Stage 10 — Distribution
**Exit condition**: fresh install under 10 minutes from one curl command.

- [ ] `curl -fsSL https://raw.githubusercontent.com/.../install.sh | bash`
- [ ] Detects Apple Silicon vs Intel → downloads correct parakeet-mlx variant
- [ ] Dependency checks: Python 3.11+, ffmpeg, ollama (optional with prompt)
- [ ] Writes `~/.butler/uninstall.sh` during install
- [ ] README: prerequisites, quickstart, plugin catalogue, screenshots

- [ ] Git tag: `v2.10-distribution`

---

## Event Taxonomy (Reference)

| Event | Emitter | Payload |
|---|---|---|
| `input.received` | any input plugin | `{text, source, ts, raw_file?}` |
| `note.routed` | pipeline / note-router | `{text, destination, project_slug?, note_type?}` |
| `note.written` | daily-writer | `{path, ts, word_count}` |
| `pipeline.error` | core | `{stage, error, input_preview}` |
| `heartbeat.tick` | core | `{ts, idle_seconds, time_of_day}` |
| `day.ended` | core | `{date, daily_file_path}` |
| `reflection.ready` | reflection plugin | `{path, ts}` |

---

## Capabilities Registry Pattern (Reference)

```python
# Safe cross-plugin call — returns None if plugin disabled, never raises
result = bus.capabilities.call("memory.search", query="what did I decide about X", n=5)
```

Capabilities discovered at startup by scanning `capabilities.json` of all enabled plugins.

---

## Notes for Agentic Coding Workflow (GSD)

- Each Stage = one GSD task block with a named exit condition
- Begin every stage by reading existing plugin READMEs and `core/` module docstrings
- Run `butler dev validate` at end of every stage before tagging
- Test `DRY_RUN=true` at every stage from Stage 4 onwards  
- The `example-plugin` from Stage 0 must remain functional at every stage (regression canary)
- Never modify core between stages unless a stage explicitly lists a core addition
- If a plugin change requires an unlisted core change: stop, reconsider the event/capability design
