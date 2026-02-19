# Smart Butler 2.0

## What This Is

Smart Butler 2.0 is a local-first personal AI assistant that captures thoughts from voice memos, messages, or text, automatically organizes them, and files them into your second brain or diary without extra effort. It runs quietly on your Mac, handling transcription, classification, writing to the right file, building a searchable memory, and surfacing patterns over time.

## Core Value

Butler is invisible when idle and useful when needed — never the reason your computer is slow. It saves you effort by automatically organizing your thoughts through multiple input methods while being accessible to non-technical users.

## Current State

**Shipped:** v1.0 Core & Notifications MVP (2026-02-19)  
**Phases:** 2 complete (Core Infrastructure, Notifications & Feedback)  
**Plans:** 7 complete  
**Code:** ~10,100 LOC Python

### What v1.0 Delivered

- Event bus with 6 lifecycle signals
- Plugin system with auto-discovery
- Voice input pipeline (folder watching → transcription → Obsidian)
- Daily writer with Obsidian frontmatter
- macOS notifications and audio feedback (success/waiting/error)
- Installation script and butler doctor command
- Huey task queue with SQLite backend
- Safe write protocol for atomic file operations
- Smart throttling based on CPU/RAM/power

## Requirements

### Validated

- ✓ Voice transcription via parakeet-mlx — v1.0
- ✓ Voice input triggers input_received event — v1.0
- ✓ launchd folder watching — v1.0
- ✓ Daily writer subscribes to note.routed — v1.0
- ✓ macOS notifications on note.written — v1.0
- ✓ Audio feedback for success/waiting/error — v1.0
- ✓ Notifications plugin fully removable — v1.0
- ✓ One-command installation — v1.0
- ✓ butler doctor health checks — v1.0

### Active

- [ ] Telegram bot for multi-device capture
- [ ] Alfred workflow for quick notes
- [ ] AI text polish (filler word removal)
- [ ] Daily digest generation
- [ ] AI-powered note routing
- [ ] Vector memory and semantic search
- [ ] Wake word activation
- [ ] Menubar app
- [ ] Action item extraction
- [ ] YouTube transcription
- [ ] Plugin manager TUI

### Out of Scope

- Cloud API fallback — Butler is locked to Apple Silicon + local models
- API key management — all processing happens locally
- Real-time chat features — Butler is an assistant, not a chat app
- Mobile app — Mac-first with iPhone/Watch integration via voice
- Real-time collaboration — personal assistant for individual use

## Context

Smart Butler 2.0 is designed for two distinct user types: a developer/writer who wants technical integration and a non-technical user who journals via Telegram voice messages. The system uses Python 3.10+ with an event bus architecture, plugin system, and local AI processing via Ollama and parakeet-mlx. All data stays on the user's machine with Obsidian-compatible markdown storage.

## Constraints

- **Hardware**: Apple Silicon Mac capable of running parakeet-mlx and llama3.1:8b
- **Models**: Local-only via Ollama, no cloud API fallback
- **Privacy**: All data stays on user's machine, no external services
- **Performance**: Must be invisible when idle, not slow down the computer
- **Storage**: Obsidian-compatible markdown format in user-configured vault

## Key Decisions

| Decision                     | Rationale                                  | Outcome                         |
| ---------------------------- | ------------------------------------------ | ------------------------------- |
| Local-only AI processing     | Privacy and offline capability             | ✓ Working - Ollama runs locally |
| Plugin auto-discovery        | Easy extensibility without CLI commands    | ✓ Working - manifest-based      |
| Event bus architecture       | Loose coupling between components          | ✓ Working - blinker signals     |
| Obsidian format storage      | Familiar format for users                  | ✓ Working - daily notes         |
| Apple Silicon target         | Eliminates conditional logic complexity    | ✓ Working - parakeet-mlx        |
| Huey with SQLite             | Zero external dependencies, crash recovery | ✓ Working                       |
| Subprocess for notifications | Zero hard Python dependencies              | ✓ Working                       |

## Next Milestone Goals

**v1.1 Telegram & Alfred:**

- Phase 3: Telegram bot with text/voice capture
- Phase 4: AI text polish and daily digest

---

_Last updated: 2026-02-19 after v1.0 milestone_
