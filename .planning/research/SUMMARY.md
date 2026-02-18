# Project Research Summary

**Project:** Smart Butler V2
**Domain:** Local-first personal AI assistant with voice input and Obsidian integration
**Researched:** 2026-02-18
**Confidence:** HIGH

## Executive Summary

Smart Butler V2 is a voice-first, local-only AI assistant that captures spoken thoughts and routes them to an Obsidian vault. Unlike cloud-dependent assistants, it runs entirely on Apple Silicon Macs, respecting the "invisible when idle" principle—users should never notice it's running until they need it.

Research across stack, features, architecture, and pitfalls converges on a clear approach: build a gateway-centric control plane with a pipeline architecture, using Ollama + parakeet-mlx for local AI/voice, SQLite for persistence, and a safe-write protocol to coordinate with Obsidian. The critical risks are resource consumption (idle performance), file race conditions, and STT hallucination—all preventable with architectural decisions made in Phase 1.

The product's competitive edge comes from being truly local-first (no cloud dependency), voice-first (not chat-optimized), and Obsidian-native (files live in the user's vault, not a silo). The MVP should validate this core loop: voice → transcription → auto-filing to Obsidian.

## Key Findings

### Recommended Stack

Python 3.11+ with a carefully selected set of local-first technologies. Ollama provides the LLM runtime (llama3.1:8b for reasoning, nomic-embed-text for embeddings). parakeet-mlx delivers Apple Silicon-optimized voice transcription—faster than Whisper on M-series chips. SQLite handles all persistence (tasks via Huey, memory, config). ChromaDB provides embedded vector search without a server.

**Core technologies:**
- **Ollama (0.6.1):** Local LLM runtime — handles model management, embeddings, chat completion via official Python SDK
- **parakeet-mlx:** Voice transcription — optimized for Apple Silicon via MLX framework, faster than whisper-mlx for real-time
- **SQLite (3.45+):** Primary database — local-first by design, single-file, zero-config, ACID compliant
- **ChromaDB (1.5.0):** Vector memory — embedded vector DB with Ollama integration, no server required
- **Textual (8.0.0):** TUI framework — async-native, CSS-based styling, supports browser export
- **rumps (0.4.0):** macOS menubar — only mature Python option for status bar apps
- **blinker (1.9.0):** Event bus — Pallets ecosystem standard, thread-safe, zero dependencies
- **huey (2.6.0):** Task queue — lightweight alternative to Celery with SQLite backend built-in

**Explicitly avoided:** Celery (overkill), Redis (external dependency), OpenAI API (violates local-first), LangChain (heavy abstraction), Electron (memory bloat), FastAPI (no HTTP layer needed).

### Expected Features

Research identified table stakes users expect, differentiators that set the product apart, and anti-features that create problems despite seeming appealing.

**Must have (table stakes):**
- Voice transcription — primary input for target users, parakeet-mlx handles this well
- Local processing — "local-first" promise requires actual local execution
- Markdown/Obsidian storage — explicitly promised, standard file operations
- Basic search — users expect to find their notes
- Multiple input channels — Telegram, Alfred, direct voice capture
- AI assistance — "AI assistant" in the name requires AI capabilities
- Menubar presence — quick access, "invisible when idle, useful when needed"

**Should have (competitive advantage):**
- Automatic note classification — removes friction between capture and organized notes
- Daily summaries + nightly reflections — proactive value, scheduled jobs
- Semantic memory search — find concepts, not just keywords (ChromaDB)
- Plugin system — extensibility without core bloat
- True invisibility — zero resource usage when idle, respects user's computer

**Defer (v2+):**
- Plugin system — design API early, ship later
- Daily summaries — requires scheduler and memory maturity
- Apple Notes integration — system-level capture, add after core validated
- Multi-vault support — complexity for power users

### Architecture Approach

A gateway-centric control plane orchestrates all subsystems through an event-driven architecture. The pipeline pattern handles ordered data transforms (transcription → cleaning → routing → saving), while a multi-tier memory system separates session, working, and learning contexts.

**Major components:**
1. **Gateway** — central control plane, owns session state, coordinates all subsystems
2. **Event Bus** — Blinker-based lifecycle events, decoupled hooks, async coordination
3. **Pipeline Orchestrator** — chain of responsibility for ordered transforms
4. **Memory Manager** — multi-tier memory (session, working, learning, vector index)
5. **LLM Router** — model selection, local-only for v1
6. **Safe Write Protocol** — race condition prevention with Obsidian, atomic writes
7. **Task Queue** — Huey + SQLite for background processing with smart throttling

### Critical Pitfalls

1. **Performance Invisibility Failure** — App must be invisible when idle. Hard limits: < 100MB RAM, < 1% CPU when idle. Lazy-load AI models, profile in CI, use OS-level power management APIs.

2. **File Race Condition with Obsidian** — Concurrent writes cause corruption. Implement safe-write protocol (mtime double-check, atomic temp+replace), never write to files Obsidian is editing.

3. **AI Memory Without Persistence** — Every session starts from zero. Design persistent memory architecture from day one, use MEMORY.md pattern, conversation summarization.

4. **Model Size vs Hardware Reality** — Target users may have 8GB RAM total. Limit app footprint to 4-8GB max, offer tiered models, hardware detection at startup.

5. **STT Hallucination in Silent Audio** — Whisper can hallucinate content during silence. Voice Activity Detection before STT, confidence threshold filtering, user review before writing to Obsidian.

## Implications for Roadmap

Based on combined research, suggested phase structure:

### Phase 1: Core Infrastructure
**Rationale:** Foundation layer that all other phases depend on. Event bus has zero dependencies and enables all coordination. Gateway skeleton provides central coordination point. Storage abstractions and safe-write protocol prevent data loss from day one.
**Delivers:** Event-driven skeleton, safe file operations, hardware-aware resource management
**Addresses:** Voice → Obsidian note (core loop), menubar quick record
**Avoids:** Performance invisibility failure, file race conditions, model size issues

### Phase 2: Voice Pipeline
**Rationale:** Core differentiator—voice-first input. Depends on Phase 1 infrastructure (event bus, safe writes). STT pipeline with VAD prevents hallucination pitfall.
**Delivers:** Voice capture → transcription → cleaning → Obsidian filing
**Uses:** parakeet-mlx (STT), blinker (events), safe-write protocol
**Implements:** Pipeline orchestrator with transcription, cleaning, saving stages

### Phase 3: Intelligence Layer
**Rationale:** AI capabilities require stable infrastructure and working voice pipeline. Memory system enables persistent context across sessions.
**Delivers:** LLM-powered classification, memory persistence, basic AI assistance
**Uses:** Ollama (llama3.1:8b, nomic-embed-text), ChromaDB
**Implements:** LLM router, memory manager, session manager

### Phase 4: Input Channels
**Rationale:** Extensibility via plugins. Telegram and Alfred integrations share common plugin architecture. Depends on core pipeline working.
**Delivers:** Telegram bot input, Alfred workflow, plugin system foundation
**Uses:** python-telegram-bot, plugin registry pattern
**Implements:** Plugin registry, capabilities registry

### Phase 5: Advanced Features
**Rationale:** Semantic search, daily summaries, and multi-tier memory require mature AI pipeline and sufficient usage data.
**Delivers:** Semantic search, daily summaries, memory tiering
**Uses:** ChromaDB (full utilization), Huey scheduling
**Implements:** Vector index, background task queue with throttling

### Phase Ordering Rationale

- **Phase 1 first:** Infrastructure has no dependencies; event bus enables all coordination; safe-write protocol prevents data loss from the start
- **Phases 2-3 grouped for MVP:** Voice + AI = core value proposition validated
- **Phase 4 extends capture:** Plugin architecture enables Telegram, Alfred without core changes
- **Phase 5 is enhancement:** Advanced features require mature foundation and usage patterns

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2:** parakeet-mlx streaming API details, VAD library selection (webrtcvad vs silero)
- **Phase 3:** Ollama prompt templates for classification, memory capture strategies
- **Phase 4:** Telegram bot security patterns, Alfred workflow integration specifics

Phases with standard patterns (skip research-phase):
- **Phase 1:** Well-documented patterns (blinker, SQLite, file operations)
- **Phase 5:** Standard vector search and scheduling patterns

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All packages verified on PyPI with current versions. Official Ollama SDK, mature TUI framework. |
| Features | HIGH | Derived from competitor analysis (OpenClaw, Obsidian Copilot, Voicenotes) and explicit project requirements. |
| Architecture | HIGH | Based on Clawdbot architecture, AI Agents 2026 patterns, and local-first best practices. Multiple sources converge. |
| Pitfalls | HIGH | Cornell research on STT hallucination, Obsidian forum on race conditions, proven patterns from similar projects. |

**Overall confidence:** HIGH

### Gaps to Address

- **parakeet-mlx streaming mode:** Documentation may be sparse—test early in Phase 2, have whisper-mlx as fallback
- **Obsidian plugin API:** If safe-write proves insufficient, research Obsidian's plugin API for coordinated writes
- **Memory capture heuristics:** What qualifies as "high-value" for learning memory tier—iterate based on usage
- **8GB RAM testing:** Need actual hardware testing, not just VM simulation—find low-spec test machine

## Sources

### Primary (HIGH confidence)
- PyPI — Package versions verified (textual 8.0.0, chromadb 1.5.0, ollama 0.6.1, etc.)
- ollama.com/library — Model specifications (llama3.1:8b, nomic-embed-text)
- github.com/senstella/parakeet-mlx — Apple Silicon voice transcription
- Clawdbot Architecture (mmntm.net) — Gateway-centric design, memory architecture
- AI Agents 2026 Architecture (andriifurmanets.com) — Tool contracts, state machines
- Cornell University — STT hallucination research

### Secondary (MEDIUM confidence)
- OpenClaw/GitHub — Competitor architecture analysis
- Obsidian Forum — File I/O patterns, race conditions
- DockYard — Local AI challenges and trade-offs
- Local-First Software Research (Aalto University) — Schema evolution patterns

### Tertiary (needs validation)
- Medium/blog articles — Specific integration patterns (validate during implementation)
- Competitor feature claims — Verify actual capabilities before assuming parity

---
*Research completed: 2026-02-18*
*Ready for roadmap: yes*
