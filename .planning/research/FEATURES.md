# Feature Research

**Domain:** Local-first personal AI assistant with voice input and Obsidian integration
**Researched:** 2026-02-18
**Confidence:** HIGH

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Voice transcription | Voice memos are the primary input for target users | MEDIUM | parakeet-mlx handles this well on Apple Silicon |
| Local processing | "Local-first" promise requires actual local execution | MEDIUM | Ollama provides this foundation |
| Markdown storage | Obsidian-compatible output is explicitly promised | LOW | Standard file operations |
| Basic search | Users expect to find their notes | MEDIUM | Can start with grep, upgrade to semantic later |
| Multiple input channels | Users want to capture from wherever they are | MEDIUM | Telegram, Alfred, direct voice — each needs integration |
| AI assistance | "AI assistant" in the name requires AI capabilities | MEDIUM | Ollama + local models |
| Menubar presence | "Invisible when idle, useful when needed" implies quick access | LOW | Standard macOS menubar app pattern |

### Differentiators (Competitive Advantage)

Features that set the product apart. Not required, but valuable.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Automatic note classification | Removes friction between capture and organized notes | HIGH | AI-powered categorization + routing |
| Daily summaries + nightly reflections | Proactive value — assistant works for you while you sleep | MEDIUM | Scheduled jobs, LLM summarization |
| Semantic memory search | Find concepts, not just keywords | HIGH | ChromaDB + embeddings — but depends on note volume |
| Plugin system | Extensibility without core bloat | HIGH | See OpenClaw's tool architecture |
| True invisibility | Zero resource usage when idle — respects "never the reason your computer is slow" | MEDIUM | Lazy loading, efficient event handling |
| Apple Notes integration | Captures from system-level without custom app | MEDIUM | AppleScript / Shortcuts integration |
| Obsidian-native storage | Files live in user's vault, not a silo | LOW | Already table stakes for this project specifically |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem good but create problems.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Cloud sync | Access from anywhere | Breaks local-first promise, adds latency, privacy concerns | User manages their own sync (iCloud, Syncthing, Git) |
| Real-time always-on processing | "Instant" responses | Battery drain, resource contention, violates "invisible when idle" | On-demand processing with efficient triggers |
| Complex onboarding wizard | Reduce setup friction | Over-engineering for v1, hides power-user flexibility | Sensible defaults + optional config file |
| Built-in cloud AI fallback | "Just works" even without local model | Defeats privacy promise, creates dependency, confusing UX | Clear error when local model unavailable |
| Social/collaboration features | Share notes with others | Scope creep, adds auth/sync complexity, not target use case | Export to user's preferred sharing tool |
| Fine-tuned custom model | "Better" AI responses | Maintenance burden, hardware requirements, over-engineering for personal use | Prompt engineering + context management |
| Mobile companion app | Access on phone | Massive scope expansion, different platform constraints | Telegram bot provides mobile input already |
| Complex tagging taxonomy | Granular organization | Cognitive overhead, manual effort, breaks "invisible" promise | AI auto-classification with simple categories |

## Feature Dependencies

```
Voice Transcription
    └──requires──> Local AI (Ollama)
                        └──requires──> Apple Silicon Mac

Automatic Classification
    └──requires──> Local AI (Ollama)
    └──requires──> Note Storage (Markdown)

Semantic Search
    └──requires──> Vector Embeddings
    └──requires──> ChromaDB
    └──enhances──> Basic Search

Daily Summaries
    └──requires──> Note Storage
    └──requires──> Local AI (Ollama)
    └──requires──> Scheduler (background job)

Plugin System
    └──requires──> Core API abstraction
    └──enables──> Telegram Integration
    └──enables──> Alfred Integration
    └──enables──> Apple Notes Integration

Obsidian Integration
    └──requires──> Markdown Storage
    └──conflicts──> Proprietary database formats
```

### Dependency Notes

- **Voice Transcription requires Local AI:** parakeet-mlx runs locally, no cloud fallback
- **Semantic Search requires ChromaDB:** Can defer to v2 — grep-based search works for MVP
- **Plugin System enables all input integrations:** Design plugin API early even if v1 only ships voice input
- **Daily Summaries requires Scheduler:** macOS LaunchAgent or in-app timer — background processing must respect "invisible when idle"

## MVP Definition

### Launch With (v1)

Minimum viable product — what's needed to validate the concept.

- [ ] Voice input → transcription → Obsidian note — Core loop: speak, auto-transcribe, file to vault
- [ ] Menubar UI with quick record — Single-click capture, no app-switching
- [ ] Local-only processing — Ollama + parakeet-mlx, no cloud calls
- [ ] Basic auto-filing — Route to predefined folder (e.g., `/Inbox/` or `/Daily/`)
- [ ] Simple search — Grep-based, search within notes

### Add After Validation (v1.x)

Features to add once core is working.

- [ ] Automatic classification — AI categorizes note type (journal, todo, idea, reference)
- [ ] Telegram bot input — Remote capture via Telegram voice/text
- [ ] Alfred workflow — Quick capture from keyboard
- [ ] Semantic search — ChromaDB for concept-based retrieval

### Future Consideration (v2+)

Features to defer until product-market fit is established.

- [ ] Plugin system — External developers can add input/output channels
- [ ] Daily summaries / nightly reflections — Proactive AI-generated insights
- [ ] Apple Notes integration — System-level capture
- [ ] Multi-vault support — Manage multiple Obsidian vaults

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Voice → Obsidian note | HIGH | MEDIUM | P1 |
| Menubar quick record | HIGH | LOW | P1 |
| Local processing | HIGH | MEDIUM | P1 |
| Basic auto-filing | MEDIUM | LOW | P1 |
| Simple search | MEDIUM | LOW | P1 |
| Automatic classification | HIGH | HIGH | P2 |
| Telegram input | MEDIUM | MEDIUM | P2 |
| Alfred workflow | MEDIUM | LOW | P2 |
| Semantic search | HIGH | HIGH | P2 |
| Plugin system | MEDIUM | HIGH | P3 |
| Daily summaries | MEDIUM | MEDIUM | P3 |
| Apple Notes integration | LOW | MEDIUM | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor Feature Analysis

| Feature | OpenClaw | Obsidian Copilot | Voicenotes | Our Approach |
|---------|----------|------------------|------------|--------------|
| Local processing | ✅ Core value | ✅ Via plugins | ❌ Cloud | ✅ Core value |
| Voice input | ✅ Telegram | ❌ | ✅ Native | ✅ Native + Telegram |
| Obsidian integration | ✅ File ops | ✅ Native | ❌ | ✅ Native storage |
| Auto-classification | ❌ Manual rules | ✅ AI-assisted | ❌ | ✅ AI-powered routing |
| Daily summaries | ✅ Scheduled tasks | ❌ | ✅ AI summaries | ✅ Nightly reflections |
| Plugin system | ✅ Tool architecture | ✅ Obsidian plugins | ❌ | ✅ Input/output plugins |
| Menubar UI | ❌ Terminal/chat | ❌ In-app | ✅ Mobile | ✅ Native macOS |
| Semantic search | ❌ Basic | ✅ Smart Connections | ✅ | ✅ ChromaDB |

## Key Differentiation Strategy

Smart Butler 2.0's unique position:

1. **Invisible when idle** — Unlike OpenClaw (always-on) or cloud assistants (network overhead)
2. **Voice-first, not chat-first** — Unlike most AI assistants optimized for typing
3. **Obsidian-native** — Notes live in your vault, not a silo (unlike Voicenotes, Otter.ai)
4. **Apple Silicon optimized** — parakeet-mlx is faster than generic Whisper, lower resource usage

## Sources

- OpenClaw/Moltbot analysis: GitHub (100k+ stars), architecture docs — HIGH confidence
- Obsidian AI ecosystem: Smart Connections, Copilot, Text Generator plugins — HIGH confidence
- Voice memo apps: Voicenotes, Otter.ai, Day One AI features — MEDIUM confidence
- Menubar AI apps: BoltAI, Apple AI, Raycast AI — MEDIUM confidence
- Local AI challenges: DockYard, Microsoft Learn, Greenspector (battery impact) — HIGH confidence
- Feature creep research: Built In, Stack Overflow, Medium — MEDIUM confidence

---
*Feature research for: Local-first personal AI assistant*
*Researched: 2026-02-18*
