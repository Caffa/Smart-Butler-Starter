# 🫖 Smart Butler 2.0 — Project Plan

---

## What Is This?

**Smart Butler** is a local-first personal AI assistant that captures your thoughts — from voice memos, messages, or text — organises them automatically, and files them into your second brain or diary without any extra effort from you.

It runs quietly on your Mac. You speak, type, or send a message. Butler handles the rest: transcription, classification, writing to the right file, building a searchable memory, and surfacing patterns over time. Everything stays on your machine by default.

It is built for two kinds of users:

- **You** — a developer/writer who wants deep control, Alfred integration, voice input from Mac and iPhone/Watch, agentic AI features, and a plugin system you can extend without breaking things.
- **Your mom** — a non-technical user who wants to journal by sending voice messages on Telegram, ask questions about her notes, and never open a terminal.

Both users run the same system. The difference is the install path and which plugins are enabled.

---

## The Two-Person Team

### 🔧 Engineer (Dev perspective)
Cares about: clean architecture, easy reinstall for testing, logs that are actually useful, plugin isolation so removing one never breaks another, a tester function for synthetic input, smart library choices, and git tags as rollback checkpoints.

### 🎨 UX Designer (User perspective)
Cares about: install experience that works for a non-technical user, every prompt having plain-English context, a setup flow that feels like a friendly wizard not a bash script, plugin descriptions a grandmother can read, and the Telegram experience being so smooth it feels like texting a person.

---

## Architecture Decisions (Locked)

### Core Patterns
- **Event Bus** (`blinker`): lifecycle events — `input.received`, `note.routed`, `heartbeat.tick`, `day.ended`, etc.
- **Pipeline**: ordered data transforms — transcription → cleaning → routing → saving. Plugins insert named stages.
- **Service Locator** (via `capabilities.json`): plugins declare callable functions; other plugins and Alfred discover and invoke them through the capabilities registry. Inspired by OpenClaw's skill system.

### Tech Stack
| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | ML libraries, existing v1 codebase, agentic tooling |
| Event bus | `blinker` | Lightweight, battle-tested, Flask-proven |
| Task queue | `huey` + SQLite | Zero extra services, fully packageable |
| Config | YAML + `PyYAML` + `dataclasses` | Human-readable, no Pydantic magic |
| Config UI | `textual` TUI | Checkbox/dropdown without a web server |
| Vector memory | `chromadb` behind `MemoryBackend` ABC | Local, no server; swap to pgvector later without touching other code |
| Folder watch | `launchd` + `WatchPaths` | System-level, reliable, not Automator |
| Notifications | `osascript` + `afplay` | Native macOS, zero dependencies |
| Logging | Single logger, multiple handlers | One place to look, filter by level |
| Version control | git tags per stage | Rollback checkpoints |
| Obsidian format | Obsidian-flavoured markdown | `[[wikilinks]]`, frontmatter, tags — tight coupling for better experience |

### Two Storage Domains (Important Separation)
```
~/.butler/                          ← SYSTEM DATA (never user-edited)
  config/
    config.yaml                     # core settings
    plugins/                        # per-plugin config overrides
  logs/
    butler.log                      # verbose, all levels
    butler-errors.log               # ERROR+ only
  data/
    prompt-history/                 # YYYY-MM-DD.jsonl — rendered prompts + variables
    memory/                         # chromadb vector index
    cache/                          # plugin caches, dedup hashes
  install-manifest.json             # every file install.sh touched, for uninstaller

{user-configured notes folder}/     ← VAULT DATA (Obsidian opens this)
  default: ~/Butler-Notes/
  journals/
    daily/                          # YYYY-MM-DD.md  ← single source of truth for input
    digests/                        # YYYY-MM-DD-digest.md
    reflections/                    # YYYY-MM-DD-reflection.md
    deductions/                     # YYYY-MM-DD-deductions.md
  projects/                         # {project-slug}.md
  index.md                          # auto-generated vault index (optional plugin)
```

The install script asks: *"Where would you like Butler to save your notes? (Press Enter for ~/Butler-Notes)"*
This path is stored in `config.yaml` as `vault.path` and never hardcoded anywhere.

### Plugin Contract
Every plugin exposes exactly one entry point in `plugin/main.py`:
```python
def register(bus, config):
    ...
```
Core calls nothing else. **If removing a plugin breaks core, that is a bug in core.**

Plugin auto-discovery: on startup, `plugin_loader.py` scans all subdirectories of `plugins/` for a `manifest.json` with `"enabled": true`. Drop a folder in → it loads next restart. No CLI registration needed.

### Plugin Folder Structure
```
plugins/
  {plugin-id}/
    manifest.json          # identity, version, dependencies, enabled flag (Obsidian-style)
    hooks.json             # events this plugin listens to + emits (declared; validated by dev-script)
    capabilities.json      # callable functions for other plugins/Alfred (compiled from docstrings)
    alfred-runner.json     # Alfred script filter entries
    user-data.json         # USER settings overrides — this is what the TUI edits
    python-runners/        # CLI-callable scripts (Alfred, terminal, Keyboard Maestro)
      script-name.py       # python script-name.py {input} → output (JSON or plain text)
    plugin/                # plugin source code
      main.py              # register(bus, config) — the only entry point core calls
      helpers.py
      models.py            # dataclasses only, no Pydantic
    tests/
      test_main.py
    README.md              # Plain English. First line: one sentence a non-developer can read.
```

### manifest.json
```json
{
  "id": "voice-input",
  "name": "Voice Input",
  "version": "1.0.0",
  "description": "Listens for new audio files and transcribes them into your daily journal automatically.",
  "author": "you",
  "min_butler_version": "2.0.0",
  "dependencies": [],
  "optional_dependencies": ["notifications"],
  "tags": ["input", "audio"],
  "enabled": true
}
```

### user-data.json (NEW — per plugin, TUI-editable)
```json
{
  "watch_folder": "~/Desktop/VoiceMemos",
  "delete_after_transcription": true,
  "archive_folder": null
}
```
The Textual TUI (`butler config`) scans all plugin folders for `user-data.json`, merges with the schema declared in `manifest.json` under `"user_settings"`, and presents everything in one unified interface. User changes write back to `user-data.json` in the plugin folder — never to `config.yaml`, which remains the system/developer layer.

### hooks.json
```json
{
  "listens": [
    { "event": "heartbeat.tick", "description": "Checks watch folder for new audio files on each tick" }
  ],
  "emits": [
    { "event": "input.received", "description": "Fired after transcription completes, carries raw text and source metadata" }
  ]
}
```

### capabilities.json (compiled from docstrings by `butler dev validate`)
```json
{
  "capabilities": [
    {
      "id": "memory.search",
      "description": "Semantic search across all indexed notes. Returns ranked results with metadata.",
      "callable": "plugin.main.search",
      "params": { "query": "str", "n": "int" },
      "returns": "list[dict]"
    },
    {
      "id": "memory.add_context",
      "description": "Takes a prompt string, injects relevant memory as context, returns enhanced prompt.",
      "callable": "plugin.main.add_context",
      "params": { "prompt": "str" },
      "returns": "str"
    }
  ]
}
```

### Prompt History Format
One JSON line per LLM call, written to `~/.butler/data/prompt-history/YYYY-MM-DD.jsonl`:
```json
{
  "ts": "2025-02-17T14:32:00",
  "plugin": "note-router",
  "template": "classify_note",
  "variables": { "raw_text": "...", "date": "2025-02-17" },
  "rendered": "full prompt string after all variable injection",
  "model": "llama3.2",
  "response_preview": "first 200 chars of model response"
}
```
`butler prompts` in the TUI shows today's table; select a row to see full rendered prompt and all injected variables. This is how you debug when something goes wrong.

### Uninstall Strategy
- `install.sh` writes every touched path to `~/.butler/install-manifest.json` as it runs
- `uninstall.sh` reads manifest and removes in reverse order
- `--keep-config` preserves `~/.butler/config/` and the vault folder
- `--keep-models` preserves downloaded Ollama models
- Presented during install: *"If you ever want to remove Butler, run: ~/.butler/uninstall.sh"*

---

## Stages

---

### Stage 0 — Skeleton & Dev Tooling
**Exit condition:** `example-plugin` loads, logs "hello" cleanly, and `butler dev validate example-plugin` passes. Engineer can wipe and reinstall in under 2 minutes.

#### Tasks

**Repo & structure**
- [ ] Init git repo, `.gitignore` (exclude `~/.butler/`, `__pycache__`, `.env`)
- [ ] Top-level: `core/`, `plugins/`, `scripts/`, `prompts/`, `tests/`, `docs/`
- [ ] `CONTRIBUTING.md` — how to add a plugin (drop folder, add manifest, restart)

**Core modules**
- [ ] `core/bus.py` — `blinker` wrapper; event names as string constants in `Events` class (e.g. `Events.INPUT_RECEIVED = "input.received"`)
- [ ] `core/config.py` — loads `~/.butler/config/config.yaml`, merges `user-data.json` from each enabled plugin, returns typed dataclass tree. No Pydantic.
- [ ] `core/plugin_loader.py` — scans `plugins/*/manifest.json`, filters `enabled: true`, calls `plugin.main.register(bus, config)`. Auto-discovery: no CLI registration.
- [ ] `core/logger.py` — single `logging.Logger`, two handlers: file (DEBUG+, `~/.butler/logs/butler.log`), stderr (WARNING+). Format: `[HH:MM:SS] [LEVEL] [plugin-id] message`
- [ ] `core/pipeline.py` — named stage registry; plugins call `pipeline.insert(after="stage-name", fn=my_transform)`. Default passthrough: `input.received → note.routed`.
- [ ] `core/capabilities_registry.py` — dict keyed by capability id; `call(id, **kwargs)` returns `None` and logs warning if plugin disabled. Never raises.
- [ ] `core/prompts.py` — loads `.md` templates from `prompts/` with YAML frontmatter; renders with variable dict; appends to prompt-history `.jsonl`

**Dev tooling**
- [ ] `scripts/dev-validate.py` — validates a plugin folder: manifest required keys, hooks.json vs actual subscriptions, compiles capabilities.json from docstrings, checks README.md first line length (warn if >120 chars — TUI truncates)
- [ ] `scripts/dev-test-input.py` — fires a synthetic `input.received` event with configurable payload. The engineer's smoke test. Usage: `python dev-test-input.py --text "hello world" --source alfred`
- [ ] `scripts/dev-reinstall.sh` — wipes `~/.butler/` (keeps vault), reinstalls fresh. For testing install script.

**Example plugin**
- [ ] `plugins/example-plugin/` — full folder structure, logs "🫖 example-plugin loaded" on startup and "👋 hello from example-plugin" on `Events.TEST_PING`. Serves as regression canary for all future stages and as copy-paste template for new plugins.

**Git tag:** `v2.0-skeleton`

---

### Stage 1 — Base Engine + Friendly Install
**Exit condition:** Drop audio file → transcription in today's `.md`. Install script has personality. Engineer can test with `dev-test-input.py`. UX designer's grandmother could read the install prompts.

#### Tasks

**Friendly install script** *(UX priority — do this before the engine)*
- [ ] `scripts/install.sh` opens with ASCII art butler logo and greeting: *"Hello! I'm Butler. Let's get you set up. This will take about 3 minutes."*
- [ ] Each prompt has a plain-English explanation before it appears, e.g.: *"Butler saves your journal entries as plain text files. Where should they go? You can open this folder with Obsidian later."*
- [ ] Prompts: notes folder path (default `~/Butler-Notes`), Ollama model choice (default `llama3.2`), whether to enable Telegram (y/N — deferred to Stage 3 if no)
- [ ] Shows progress with emoji step indicators: `✅ Created notes folder`, `⬇️ Downloading Ollama...`, `✅ Butler is ready!`
- [ ] Detects if Ollama is already installed; if not, prints: *"Butler uses Ollama to think locally on your Mac. I'll install it now — this is safe and private."* then runs Ollama's own installer with explicit user confirmation (`--skip-ollama` flag to bypass)
- [ ] `--verbose` flag shows full Unix output for developers; default hides it
- [ ] Writes `~/.butler/install-manifest.json` as it goes
- [ ] Ends with: *"All done! 🎉 Butler is now running in the background. Your notes will appear in ~/Butler-Notes/journals/daily/"* (or whatever path was chosen)
- [ ] Writes `~/.butler/uninstall.sh` and tells user where it is

**launchd**
- [ ] `WatchPaths` plist watches configured voice memo drop folder (default `~/Desktop/VoiceMemos/`)
- [ ] On new file: calls `plugins/voice-input/python-runners/transcribe.py {filepath}`
- [ ] Keepalive plist for main butler process (huey worker)

**Plugin: `voice-input`**
- [ ] `python-runners/transcribe.py {filepath}` — runs parakeet-mlx, enqueues huey task with transcription text and source metadata
- [ ] `plugin/main.py register()` — subscribes to `input.received`, validates payload shape, passes to pipeline
- [ ] `user-data.json`: `watch_folder`, `delete_after_transcription` (default true), `archive_folder` (default null)
- [ ] `README.md` first line: *"Watches a folder for new audio files and transcribes them into your daily journal."*

**Plugin: `daily-writer`**
- [ ] Subscribes to `note.routed` (passthrough from `input.received` until note-router added in Stage 5)
- [ ] Appends timestamped block to `{vault.path}/journals/daily/YYYY-MM-DD.md` with Obsidian frontmatter header on first write of the day
- [ ] Obsidian frontmatter: `date`, `tags: [journal, butler-input]`, `source` field
- [ ] Emits `note.written` with `{path, ts, word_count, source}`
- [ ] `user-data.json`: `date_format`, `tag_prefix` (default "butler")

**Core**
- [ ] Huey SQLite worker starts as part of main butler process
- [ ] `DRY_RUN=true` env var: all pipeline stages run, nothing writes to disk, no LLM calls, every action logs `[DRY RUN]`
- [ ] `butler status` CLI shows: process running y/n, plugins loaded, last event timestamp, vault path

**Git tag:** `v2.1-base-voice`

---

### Stage 2 — Notifications & Sounds
**Exit condition:** macOS notification + sound fires on `note.written`. Fully removable.

**Plugin: `notifications`**
- [ ] Listed as `optional_dependencies` in other manifests — zero hard dependencies on it
- [ ] Subscribes to configurable event list; default: `note.written`, `pipeline.error`
- [ ] `osascript` notification banner; configurable title/body template per event using `{variables}` from event payload
- [ ] `afplay` sounds: three categories — success (note written), waiting (processing), failure (error). Configurable `.aiff` path per category.
- [ ] Ships 3 default short sounds in `plugin/sounds/`
- [ ] `user-data.json`: `enabled_events` list, `sound_enabled` bool, per-event sound overrides
- [ ] `README.md` first line: *"Plays a sound and shows a notification on your Mac when Butler does something."*

**Git tag:** `v2.2-notifications`

---

### Stage 3 — Telegram Input + Non-Technical Install Path
**Exit condition:** Your mom can send a voice message on Telegram and it appears in her daily journal. The `.pkg` installer exists.

*Note from UX designer: This stage is the real v1 for non-technical users. It must be solid before anything else is added.*

**Plugin: `telegram-input`**
- [ ] `python-runners/telegram-bot.py` — long-poll bot, managed by its own launchd plist
- [ ] Commands:
  - `/note {text}` or just sending any text → `input.received` with `source: telegram`
  - Voice message sent to bot → saved to temp file → transcribed → `input.received`
  - `/ask {query}` → stubbed response: *"Memory search coming soon! 🔍"* until Stage 6
  - `/help` → friendly command list with emoji, plain-English descriptions
  - `/status` → *"🫖 Butler is running. Your last note was saved at 3:42pm."*
- [ ] Bot setup wizard: `butler plugin setup telegram-input` walks through: create bot with BotFather link, paste token, test message. Friendly prompts, not cold Unix.
- [ ] `user-data.json`: `bot_token`, `allowed_user_ids` (security — only listed Telegram user IDs can send notes), `voice_transcription_enabled`
- [ ] `README.md` first line: *"Lets you send notes and voice messages to Butler via Telegram from any device."*

**Plugin: `alfred-input`**
- [ ] `python-runners/diary-input.py {text}` — enqueues `input.received` with `source: alfred`
- [ ] `alfred-runner.json`: one entry, name "Send to Butler", description "Save a quick note to today's journal"
- [ ] Ships `butler-alfred.alfredworkflow` in plugin root for easy import
- [ ] `README.md` first line: *"Lets you send a quick note to Butler from Alfred with a keyboard shortcut."*

**Non-technical install path**
- [ ] `scripts/build-pkg.sh` — wraps install.sh into a macOS `.pkg` installer with a GUI wizard (using `pkgbuild` + `productbuild`)
- [ ] PKG installer screens: Welcome (with butler personality), Notes Folder picker (native macOS folder chooser), Ollama install confirmation, Telegram setup (optional), Done
- [ ] Releases: `butler-installer.pkg` alongside the `curl` one-liner. README shows both options with clear labels: *"For developers"* and *"For everyone else"*

**Git tag:** `v2.3-telegram-and-pkg`

---

### Stage 4 — LLM Text Polish + Day Digest
**Exit condition:** Notes optionally cleaned by LLM. End-of-day digest written. `DRY_RUN` fully tested.

**Plugin: `text-polish`** *(optional, off by default)*
- [ ] Inserts into pipeline after `input.received`, before `note.routed`
- [ ] LLM call via Ollama (configured model, default `llama3.2`)
- [ ] If Ollama unavailable → pass through unchanged, log warning, fire `pipeline.error` event (notifications plugin catches this)
- [ ] Never blocks the pipeline. Degraded mode is always just "pass through."
- [ ] `user-data.json`: `enabled`, `model`, `aggressiveness: [light | standard]`
- [ ] `README.md` first line: *"Gently cleans up your voice notes — fixing filler words and run-on sentences — before saving them."*

**Plugin: `day-digest`**
- [ ] Subscribes to `day.ended` (core emits at configurable time, default 23:30)
- [ ] Reads today's daily `.md`, LLM summarises into digest
- [ ] Writes `{vault.path}/journals/digests/YYYY-MM-DD-digest.md` with Obsidian frontmatter
- [ ] Daily file gets a `[[YYYY-MM-DD-digest]]` wikilink appended
- [ ] If `telegram-input` capability available: sends digest as Telegram message (safe capability call — checks registry first, no hard dep)
- [ ] `user-data.json`: `send_time` (default "23:30"), `send_to_telegram` (default false), `digest_length: [brief | standard | detailed]`
- [ ] `README.md` first line: *"Writes a summary of your day's notes each evening and optionally sends it to you on Telegram."*

**Git tag:** `v2.4-llm-basics`

---

### Stage 5 — Note Router
**Exit condition:** Notes classified and filed to project files. Daily journal unchanged as fallback.

**Plugin: `note-router`**
- [ ] Inserts into pipeline after `text-polish` (or after `input.received` if polish disabled)
- [ ] LLM classifier returns: `{destination: "daily"|"project", project_slug: str|null, note_type: "log"|"idea"|"reference"}`
- [ ] `daily` → standard flow, nothing changes
- [ ] `project` → appends to `{vault.path}/projects/{project_slug}.md` + appends `→ [[{project_slug}]]` wikilink to daily entry
- [ ] New project file gets Obsidian frontmatter: `project`, `created`, `tags: [project, butler-routed]`
- [ ] Deduplication: SHA-256 hash of raw text stored in `~/.butler/data/cache/dedup.db`; exact match within 24h → warn + skip
- [ ] Every classification call written to prompt-history
- [ ] `user-data.json`: `enabled`, `known_projects` list (helps classifier), `default_destination`
- [ ] `README.md` first line: *"Automatically files notes to the right project instead of always putting everything in your daily journal."*

**Git tag:** `v2.5-note-router`

---

### Stage 6 — Memory & Search
**Exit condition:** `butler ask "query"` returns answer. Alfred search works. Telegram `/ask` works.

**Plugin: `memory`**
- [ ] `plugin/backend.py` — `MemoryBackend` ABC: `add(text, metadata) → str`, `search(query, n) → list[dict]`, `delete(id) → None`
- [ ] `plugin/chroma_backend.py` — `ChromaBackend(MemoryBackend)`, stores in `~/.butler/data/memory/`
- [ ] **Migration note:** Future `PgvectorBackend` implements same ABC. Swap in `user-data.json` as `backend: chroma|pgvector`. Nothing else in codebase changes.
- [ ] On `note.written`: adds note to memory with `{date, source, project, word_count}` metadata
- [ ] Search combines semantic (ChromaDB) + grep (Python `re`) for hybrid recall
- [ ] Read-only folder indexing: `user-data.json` lists `index_folders` with `exclude_patterns` (e.g. `**/Templates/**`)
- [ ] `butler memory reindex` CLI command — walks folders, bulk-adds, shows progress bar
- [ ] `capabilities.json`: exposes `memory.search` and `memory.add_context`
- [ ] `python-runners/search.py {query}` → JSON to stdout (Alfred + terminal)
- [ ] `alfred-runner.json`: entry "Ask Butler", description "Search your notes with a question"
- [ ] Telegram `/ask {query}` now works — `telegram-input` plugin calls `memory.search` capability
- [ ] `README.md` first line: *"Gives Butler a searchable memory of everything you've written, so you can ask questions and get answers."*

**Git tag:** `v2.6-memory`

---

### Stage 7 — Heartbeat & Reflection
**Exit condition:** Nightly reflection runs without user input. Idle detection works.

**Core addition**
- [ ] `core/heartbeat.py` — configurable tick (default 5 min), emits `heartbeat.tick` with `{ts, idle_seconds, time_of_day}`
- [ ] Night gate: `@night_only` decorator restricts handler to configurable hours (default 22:00–06:00)
- [ ] Keepalive launchd plist (already started in Stage 1, this formalises the pattern)

**Plugin: `reflection`**
- [ ] Subscribes to `heartbeat.tick` with `@night_only`
- [ ] Reads last 7 days of daily files + last 50 memory entries
- [ ] LLM generates: open questions, patterns noticed, loose threads
- [ ] Writes `{vault.path}/journals/reflections/YYYY-MM-DD-reflection.md` with wikilinks to relevant daily files
- [ ] Emits `reflection.ready` (notifications plugin shows banner: *"🌙 Butler has written your nightly reflection"*)
- [ ] `user-data.json`: `enabled`, `run_time` (default "23:00"), `lookback_days` (default 7)
- [ ] `README.md` first line: *"Writes a thoughtful reflection each night, noticing patterns in what you've been thinking about."*

**Git tag:** `v2.7-heartbeat`

---

### Stage 8 — Deductions
**Exit condition:** Butler surfaces temporal patterns and hypotheses from accumulated memory.

**Plugin: `deductions`**
- [ ] Subscribes to `day.ended` and `reflection.ready`
- [ ] Calls `memory.search` capability for thematically related notes across time
- [ ] LLM: given N cross-date notes, identify patterns / hypotheses / contradictions
- [ ] Writes `{vault.path}/journals/deductions/YYYY-MM-DD-deductions.md`
- [ ] Deductions added back to memory with `type: deduction` tag
- [ ] Full `DRY_RUN` support — shows what would be written, no LLM calls
- [ ] `README.md` first line: *"Notices patterns across your notes over time and surfaces hypotheses you might not have seen yourself."*

**Plugin: `smarter-digest`** *(optional upgrade to `day-digest`)*
- [ ] Replaces `day-digest` if both enabled (manifest `supersedes: ["day-digest"]`)
- [ ] Pulls from memory + deductions for temporal-context digest
- [ ] Surfaces: what changed since last week, recurring themes, open loops
- [ ] `README.md` first line: *"A richer version of the daily digest that notices trends and connects today's notes to your longer patterns."*

**Git tag:** `v2.8-deductions`

---

### Stage 9 — Config TUI & Prompt Manager
**Exit condition:** `butler config` is pleasant to use. Non-technical user could change their settings.

**Textual TUI** (`butler config`)
- [ ] Opens with butler header, list of enabled plugins with toggle checkboxes
- [ ] Each plugin shows: name, README first line as description, enabled/disabled toggle
- [ ] Selecting a plugin shows its `user-data.json` fields as editable form (text inputs, dropdowns, checkboxes based on field type declared in manifest `user_settings` schema)
- [ ] Save writes back to `user-data.json` in the plugin folder
- [ ] Tab: `butler prompts` — table from today's `.jsonl`; select row → full rendered prompt + variable values
- [ ] Tab: `butler logs` — tail with level filter
- [ ] Fallback: if `textual` not installed → opens `$EDITOR` on `config.yaml` with a comment at the top explaining each key

**Dev tooling additions**
- [ ] `butler dev validate {plugin-id}` — hook/capability mismatch report, README first-line check
- [ ] `butler dev test --dry-run` — loads all plugins, fires synthetic `input.received`, traces full pipeline with `[DRY RUN]`, prints event trace

**Git tag:** `v2.9-tui`

---

### Stage 10 — Polish & Distribution
**Exit condition:** Someone else installs this in under 10 minutes. Your mom successfully uses it.

- [ ] Final `install.sh` pass: test on a clean macOS account, fix any rough edges
- [ ] `.pkg` installer tested on a non-technical user (your mom)
- [ ] `README.md`: two install sections — *"For developers"* (curl command) and *"For everyone else"* (download .pkg link)
- [ ] Plugin catalogue in README: each plugin listed with its one-sentence description
- [ ] `butler doctor` command — checks all dependencies, prints status of each with emoji (✅ / ⚠️ / ❌)
- [ ] GitHub Actions: on tag push, builds `.pkg` and attaches to release
- [ ] Uninstall tested: `~/.butler/uninstall.sh --keep-config` leaves vault untouched

**Git tag:** `v2.10-distribution`

---

## Event Taxonomy (Reference)

| Event | Emitter | Payload |
|---|---|---|
| `input.received` | any input plugin | `{text, source, ts, raw_file?}` |
| `note.routed` | pipeline / note-router | `{text, destination, project_slug?, note_type?}` |
| `note.written` | daily-writer | `{path, ts, word_count, source}` |
| `pipeline.error` | core | `{stage, error, input_preview}` |
| `heartbeat.tick` | core | `{ts, idle_seconds, time_of_day}` |
| `day.ended` | core | `{date, daily_file_path}` |
| `reflection.ready` | reflection plugin | `{path, ts}` |

---

## Capabilities Registry Pattern (Reference)

```python
# Safe cross-plugin call. Returns None + logs warning if plugin disabled. Never raises.
result = bus.capabilities.call("memory.search", query="what did I decide about X", n=5)
context = bus.capabilities.call("memory.add_context", prompt=my_prompt)
```

---

## Notes for Agentic Coding Workflow (GSD)

- Each Stage = one GSD task block with a named exit condition
- Begin every stage by reading existing plugin READMEs and core module docstrings
- Run `butler dev validate` on all plugins at end of every stage before tagging
- Test `DRY_RUN=true` at every stage from Stage 4 onwards
- `plugins/example-plugin/` must pass `butler dev validate` at every stage (regression canary)
- Never modify core between stages unless a stage explicitly lists a core addition
- If a plugin requires a core change not listed in the stage plan: stop and reconsider the event/capability design
- The two-person team rule: every new feature must satisfy both *"is this good architecture?"* AND *"could a non-technical user understand what this does?"*
