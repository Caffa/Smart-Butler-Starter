# Smart Butler 2.0

## What This Is

Smart Butler 2.0 is a local-first personal AI assistant that captures thoughts from voice memos, messages, or text, automatically organizes them, and files them into your second brain or diary without extra effort. It runs quietly on your Mac, handling transcription, classification, writing to the right file, building a searchable memory, and surfacing patterns over time.

## Core Value

Butler is invisible when idle and useful when needed — never the reason your computer is slow. It saves you effort by automatically organizing your thoughts through multiple input methods while being accessible to non-technical users.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] User can capture thoughts via voice input from Mac and iPhone/Watch
- [ ] User can send notes and voice messages via Telegram from any device
- [ ] User can send quick notes from Alfred with keyboard shortcut
- [ ] Butler automatically classifies and routes notes to appropriate files
- [ ] Butler provides a plugin system that can be extended without breaking things
- [ ] Butler maintains a searchable memory for asking questions about notes
- [ ] Butler writes thoughtful nightly reflections and daily summaries
- [ ] Butler shows recent activity in Mac menu bar with quick-send functionality
- [ ] Butler automatically detects and processes YouTube URLs and article links
- [ ] Butler provides a pleasant configuration TUI grouped by plugin tags

### Out of Scope

- Cloud API fallback — Butler is locked to Apple Silicon + local models
- API key management — all processing happens locally
- Real-time chat features — Butler is an assistant, not a chat app
- Mobile app — Mac-first with iPhone/Watch integration via voice
- Real-time collaboration — personal assistant for individual use

## Context

Smart Butler 2.0 is designed for two distinct user types: a developer/writer who wants technical integration and a non-technical user (your mom) who journals via Telegram voice messages. The system uses Python 3.11+ with an event bus architecture, plugin system, and local AI processing via Ollama and parakeet-mlx. All data stays on the user's machine with Obsidian-compatible markdown storage.

## Constraints

- **Hardware**: Apple Silicon Mac capable of running parakeet-mlx and llama3.1:8b
- **Models**: Local-only via Ollama, no cloud API fallback
- **Privacy**: All data stays on user's machine, no external services
- **Performance**: Must be invisible when idle, not slow down the computer
- **Storage**: Obsidian-compatible markdown format in user-configured vault

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Local-only AI processing | Privacy and offline capability | — Pending |
| Plugin auto-discovery | Easy extensibility without CLI commands | — Pending |
| Event bus architecture | Loose coupling between components | — Pending |
| Obsidian format storage | Familiar format for users | — Pending |
| Apple Silicon target | Eliminates conditional logic complexity | — Pending |

---
*Last updated: 2025-02-18 after initialization*