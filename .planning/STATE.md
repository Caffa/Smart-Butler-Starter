# STATE: Smart Butler 2.0

**Last updated:** 2025-02-18  
**Session:** Initial roadmap creation

---

## Project Reference

**Core Value:** Butler is invisible when idle and useful when needed — never the reason your computer is slow

**Current Focus:** Phase 1 - Core Infrastructure

**MVP Definition:** Voice memos from iPhone → transcribed → filed to Obsidian automatically

---

## Current Position

| Attribute | Value                                                                             |
| --------- | --------------------------------------------------------------------------------- |
| Phase     | 1                                                                                 |
| Plan      | 05 (complete)                                                                     |
| Status    | CLI voice pipeline complete: router, process-voice command, event chain validated |

### Phase Progress

```
[░░░░░░░░░░░░░░░░░░] 0/13 phases

Phase 1:  ██████████ 100% (01-05 complete, 5/5 plans done)
Phase 2:  ░░░░░░░░░░ 0%
Phase 3:  ░░░░░░░░░░ 0%
Phase 4:  ░░░░░░░░░░ 0%
Phase 5:  ░░░░░░░░░░ 0%
Phase 6:  ░░░░░░░░░░ 0%
Phase 7:  ░░░░░░░░░░ 0%
Phase 8:  ░░░░░░░░░░ 0%
Phase 9:  ░░░░░░░░░░ 0%
Phase 10: ░░░░░░░░░░ 0%
Phase 11: ░░░░░░░░░░ 0%
Phase 12: ░░░░░░░░░░ 0%
Phase 13: ░░░░░░░░░░ 0%
```

---

## Performance Metrics

| Metric                | Target  | Current | Status |
| --------------------- | ------- | ------- | ------ |
| Idle RAM              | < 100MB | —       | —      |
| Idle CPU              | < 1%    | —       | —      |
| Transcription latency | < 5s    | —       | —      |
| Note routing latency  | < 2s    | —       | —      |

---

| Phase 01-core-infrastructure P05 | 6min | 3 tasks | 8 files |
| Phase 01-core-infrastructure P03 | 19min | 5 tasks | 13 files |
| Phase 01-core-infrastructure P02 | 23min | 5 tasks | 11 files |
| Phase 01-core-infrastructure P01 | 10min | 4 tasks | 9 files |

## Accumulated Context

### Decisions Made

| Date       | Decision                          | Context                            |
| ---------- | --------------------------------- | ---------------------------------- |
| 2025-02-18 | Local-only AI (no cloud fallback) | Privacy requirement                |
| 2025-02-18 | Apple Silicon only                | Eliminate conditional complexity   |
| 2025-02-18 | 13 phases based on v4 plan        | Natural delivery boundaries        |
| 2025-02-18 | Phase 9 covers v2 requirements    | Action items deferred but included |

- [Phase 01-core-infrastructure]: Use Click for CLI framework - better than argparse for subcommands
- [Phase 01-core-infrastructure]: Python 3.10+ requirement instead of 3.11+ for environment compatibility
- [Phase 01-core-infrastructure]: Git annotated tags for checkpoints - includes metadata and rollback commands
- [Phase 01-core-infrastructure]: Huey with SQLite backend for zero-config task persistence
- [Phase 01-core-infrastructure]: ThrottledException pattern integrates with Huey retry mechanism
- [Phase 01-core-infrastructure]: SimpleRouter for MVP - passthrough routing to daily notes (AI routing in Phase 5)

### Technical Patterns

**Event Bus:** Blinker-based lifecycle events (input.received, note.routed, heartbeat.tick, day.ended)

**Safe Write Protocol:** mtime double-check + atomic temp+replace to prevent Obsidian race conditions

**Plugin Architecture:** Auto-discovery, capability registry, zero hard dependencies

**Memory Tiers:** Session → Working → Learning → Vector (ChromaDB)

### Open Questions

1. Should Phase 10 (Deductions) use v2 requirements or be deferred entirely?
2. Is parakeet-mlx streaming API mature enough for Phase 1?
3. What's the minimum macOS version for openwakeword in Phase 7?

### Blockers

None currently.

---

## Session Continuity

### Last Action

Completed 01-05-PLAN.md - CLI process-voice command with SimpleRouter, complete event chain validated

### Next Action

Phase 1 complete - ready for Phase 2: AI Layer

### Context to Preserve

**Phase 1 Critical Path:**

- Event bus enables all coordination
- Safe-write protocol prevents data loss from day one
- Plugin auto-discovery removes CLI friction
- Voice → Obsidian loop is MVP validation

**Research Flags (from SUMMARY.md):**

- Phase 2 needs parakeet-mlx streaming API research
- Phase 3 needs Ollama prompt templates research
- Phase 4 needs Telegram bot security patterns research

**Risk Mitigations:**

- Performance invisibility: lazy-load AI, profile in CI
- Race conditions: safe-write protocol, never edit open files
- STT hallucination: VAD before STT, confidence thresholds

---

## Notes

**From PROJECT.md:**

- Dual user types: developer/writer + non-technical (mom via Telegram)
- Obsidian-native, not siloed storage
- Invisible when idle, useful when needed

**From REQUIREMENTS.md:**

- 53 v1 requirements mapped across 13 phases
- Phase 9 bridges v1/v2 with ACTION-\* requirements
- All file writes use safe_write protocol

**From Research:**

- Stack: Ollama, parakeet-mlx, SQLite, ChromaDB, Textual, rumps, blinker, huey
- Architecture: Gateway-centric control plane, pipeline pattern
- Critical pitfalls: performance invisibility, file race conditions, STT hallucination

---

_State file managed by GSD workflow_  
_Template: /Users/caffae/.config/opencode/get-shit-done/templates/state.md_
