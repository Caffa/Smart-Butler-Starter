# Requirements: Smart Butler 2.0

**Defined:** 2025-02-18
**Core Value:** Butler is invisible when idle and useful when needed — never the reason your computer is slow

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Core Infrastructure (Phase 1)

- [ ] **CORE-01**: Event bus system handles lifecycle events (input.received, note.routed, heartbeat.tick, day.ended)
- [ ] **CORE-02**: Plugin system with auto-discovery loads enabled plugins on startup
- [ ] **CORE-03**: Safe write protocol prevents race conditions with Obsidian using mtime double-check pattern
- [ ] **CORE-04**: Smart throttling gates background tasks based on CPU, RAM, and power status
- [ ] **CORE-05**: Configuration system loads settings from YAML and per-plugin user-data.json
- [ ] **CORE-06**: Logging system writes to separate verbose and error log files with plugin attribution
- [ ] **CORE-07**: Task queue with SQLite backend provides crash recovery and persistence

### Input - Voice (Phase 1)

- [ ] **VOICE-01**: Voice input plugin watches folder for audio files and transcribes them
- [ ] **VOICE-02**: parakeet-mlx performs local transcription on Apple Silicon
- [ ] **VOICE-03**: Transcribed text emits input.received event to pipeline
- [ ] **VOICE-04**: launchd plist watches voice memo folder via WatchPaths

### Output - Daily Writer (Phase 1)

- [ ] **OUTPUT-01**: Daily writer plugin subscribes to note.routed events
- [ ] **OUTPUT-02**: Notes append to YYYY-MM-DD.md with timestamps and Obsidian frontmatter
- [ ] **OUTPUT-03**: Emits note.written event with path, timestamp, word count, and source
- [ ] **OUTPUT-04**: All file writes use safe_write protocol

### UX - Notifications (Phase 2)

- [ ] **NOTIFY-01**: macOS notification displays on configurable events (note.written, pipeline.error)
- [ ] **NOTIFY-02**: Audio feedback plays via afplay for success/waiting/failure states
- [ ] **NOTIFY-03**: Plugin is fully removable with zero hard dependencies

### Input - Telegram (Phase 3)

- [ ] **TELEGRAM-01**: Telegram bot receives text messages and emits input.received
- [ ] **TELEGRAM-02**: Voice messages download, transcribe via parakeet-mlx, emit input.received
- [ ] **TELEGRAM-03**: /help command shows friendly emoji-based command list
- [ ] **TELEGRAM-04**: /status command shows Butler status and last note timestamp
- [ ] **TELEGRAM-05**: Bot setup wizard uses tg:// deep link to BotFather

### Input - Alfred (Phase 3)

- [ ] **ALFRED-01**: Alfred workflow sends quick notes via python runner
- [ ] **ALFRED-02**: Ships as importable .alfredworkflow file

### AI - Text Polish (Phase 4)

- [ ] **POLISH-01**: Plugin inserts into pipeline between input.received and note.routed
- [ ] **POLISH-02**: LLM cleans filler words and run-on sentences from voice notes
- [ ] **POLISH-03**: Graceful degradation: if Ollama unavailable, text passes through
- [ ] **POLISH-04**: @throttled decorator defers processing when system busy

### AI - Day Digest (Phase 4)

- [ ] **DIGEST-01**: Subscribes to day.ended event (emitted at configurable time, default 23:30)
- [ ] **DIGEST-02**: LLM summarizes today's daily notes
- [ ] **DIGEST-03**: Writes YYYY-MM-DD-digest.md via safe_write
- [ ] **DIGEST-04**: Appends wikilink to daily file

### AI - Note Router (Phase 5)

- [ ] **ROUTER-01**: LLM classifier returns destination (daily|project) and note type
- [ ] **ROUTER-02**: Project notes append to projects/{slug}.md with wikilink in daily
- [ ] **ROUTER-03**: Deduplication using SHA-256 hash skips exact duplicates within 24h
- [ ] **ROUTER-04**: Classification calls logged to prompt-history

### AI - Memory (Phase 6)

- [ ] **MEMORY-01**: Vector memory backend (ChromaDB) stores embeddings in ~/.butler/data/memory/
- [ ] **MEMORY-02**: On note.written, adds note to memory with metadata (date, source, project)
- [ ] **MEMORY-03**: Search capability available via capabilities registry
- [ ] **MEMORY-04**: butler ask "query" CLI command returns answers from memory

### Input - Wake Word (Phase 7)

- [ ] **WAKE-01**: openwakeword runs locally detecting "Hey Butler" phrase
- [ ] **WAKE-02**: On detection, starts recording → silence → emits input.received
- [ ] **WAKE-03**: Feedback tone plays via afplay

### AI - Reflection (Phase 7)

- [ ] **REFLECT-01**: Subscribes to heartbeat.tick with @night_only decorator
- [ ] **REFLECT-02**: Reads last 7 days of daily files + memory entries
- [ ] **REFLECT-03**: LLM writes reflection noticing patterns and loose threads
- [ ] **REFLECT-04**: Writes YYYY-MM-DD-reflection.md via safe_write with wikilinks

### UX - Menubar (Phase 8)

- [ ] **MENUBAR-01**: rumps app shows in macOS menu bar
- [ ] **MENUBAR-02**: Displays recent 5 events with emoji and relative timestamp
- [ ] **MENUBAR-03**: Quick note text field emits input.received on Enter
- [ ] **MENUBAR-04**: "Open Today's Journal" opens Obsidian vault
- [ ] **MENUBAR-05**: Icon indicates state: idle, processing, throttled, error

### Enrichment - Action Items (Phase 9)

- [ ] **ACTION-01**: Extracts open [ ] tasks from notes via LLM
- [ ] **ACTION-02**: Appends to action-items.md with date and source wikilink
- [ ] **ACTION-03**: Only extracts unchecked items, ignores completed [x] tasks

### Link Resolution - YouTube (Phase 11)

- [ ] **YOUTUBE-01**: Detects YouTube URLs in incoming text
- [ ] **YOUTUBE-02**: Downloads audio via yt-dlp, transcribes via parakeet-mlx
- [ ] **YOUTUBE-03**: Writes transcript to reference/youtube/{slug}.md
- [ ] **YOUTUBE-04**: Optionally appends summary to daily journal

### Dev - Install & Doctor (Phase 1-13)

- [ ] **INSTALL-01**: install.sh script creates ~/.butler/ structure with friendly personality
- [ ] **INSTALL-02**: butler doctor checks dependencies and downloads models on first run
- [ ] **INSTALL-03**: Git tags mark rollback checkpoints at each stage

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Input

- **INPUT-01**: Apple Notes integration watches folder via AppleScript

### AI

- **AI-01**: Contradiction detector notices when new notes contradict old ones
- **AI-02**: Deductions plugin surfaces patterns across notes over time
- **AI-03**: Smarter digest supersedes day-digest with memory context
- **AI-04**: Morning briefing sends Telegram message with open loops

### Integration

- **INTEG-01**: Readwise plugin sends article URLs to Readwise account
- **INTEG-02**: Guided conversation initiates Telegram journaling prompts

### UX

- **UX-01**: Plugin manager TUI browses and toggles plugins by tag
- **UX-02**: Transcription confidence highlights low-confidence segments
- **UX-03**: Alfred search integration for memory queries

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Cloud API fallback | Breaks local-first promise and privacy guarantee |
| Intel Mac support | Locked to Apple Silicon to eliminate conditional logic |
| Real-time chat interface | Butler is capture/filing assistant, not chatbot |
| Mobile app | Mac-first; mobile via Telegram integration |
| Social/collaboration features | Personal assistant for individual use only |
| Cloud sync | User manages own sync (iCloud, Syncthing, Git) |
| Built-in web server | TUI and menubar sufficient, no HTTP layer |
| Fine-tuned custom models | Prompt engineering sufficient for personal use |
| Complex tagging taxonomy | AI auto-classification replaces manual tagging |
| Multi-vault support | Adds complexity, single vault sufficient for v1 |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| CORE-01 | Phase 1 | Pending |
| CORE-02 | Phase 1 | Pending |
| CORE-03 | Phase 1 | Pending |
| CORE-04 | Phase 1 | Pending |
| CORE-05 | Phase 1 | Pending |
| CORE-06 | Phase 1 | Pending |
| CORE-07 | Phase 1 | Pending |
| VOICE-01 | Phase 1 | Pending |
| VOICE-02 | Phase 1 | Pending |
| VOICE-03 | Phase 1 | Pending |
| VOICE-04 | Phase 1 | Pending |
| OUTPUT-01 | Phase 1 | Pending |
| OUTPUT-02 | Phase 1 | Pending |
| OUTPUT-03 | Phase 1 | Pending |
| OUTPUT-04 | Phase 1 | Pending |
| NOTIFY-01 | Phase 2 | Pending |
| NOTIFY-02 | Phase 2 | Pending |
| NOTIFY-03 | Phase 2 | Pending |
| TELEGRAM-01 | Phase 3 | Pending |
| TELEGRAM-02 | Phase 3 | Pending |
| TELEGRAM-03 | Phase 3 | Pending |
| TELEGRAM-04 | Phase 3 | Pending |
| TELEGRAM-05 | Phase 3 | Pending |
| ALFRED-01 | Phase 3 | Pending |
| ALFRED-02 | Phase 3 | Pending |
| POLISH-01 | Phase 4 | Pending |
| POLISH-02 | Phase 4 | Pending |
| POLISH-03 | Phase 4 | Pending |
| POLISH-04 | Phase 4 | Pending |
| DIGEST-01 | Phase 4 | Pending |
| DIGEST-02 | Phase 4 | Pending |
| DIGEST-03 | Phase 4 | Pending |
| DIGEST-04 | Phase 4 | Pending |
| ROUTER-01 | Phase 5 | Pending |
| ROUTER-02 | Phase 5 | Pending |
| ROUTER-03 | Phase 5 | Pending |
| ROUTER-04 | Phase 5 | Pending |
| MEMORY-01 | Phase 6 | Pending |
| MEMORY-02 | Phase 6 | Pending |
| MEMORY-03 | Phase 6 | Pending |
| MEMORY-04 | Phase 6 | Pending |
| WAKE-01 | Phase 7 | Pending |
| WAKE-02 | Phase 7 | Pending |
| WAKE-03 | Phase 7 | Pending |
| REFLECT-01 | Phase 7 | Pending |
| REFLECT-02 | Phase 7 | Pending |
| REFLECT-03 | Phase 7 | Pending |
| REFLECT-04 | Phase 7 | Pending |
| MENUBAR-01 | Phase 8 | Pending |
| MENUBAR-02 | Phase 8 | Pending |
| MENUBAR-03 | Phase 8 | Pending |
| MENUBAR-04 | Phase 8 | Pending |
| MENUBAR-05 | Phase 8 | Pending |
| ACTION-01 | Phase 9 | Pending |
| ACTION-02 | Phase 9 | Pending |
| ACTION-03 | Phase 9 | Pending |
| YOUTUBE-01 | Phase 11 | Pending |
| YOUTUBE-02 | Phase 11 | Pending |
| YOUTUBE-03 | Phase 11 | Pending |
| YOUTUBE-04 | Phase 11 | Pending |
| INSTALL-01 | Phase 1 | Pending |
| INSTALL-02 | Phase 1 | Pending |
| INSTALL-03 | Phase 1 | Pending |

**Coverage:**
- v1 requirements: 53 total
- Mapped to phases: 53
- Unmapped: 0 ✓

---
*Requirements defined: 2025-02-18*
*Last updated: 2025-02-18 after initial definition*