# Pitfalls Research

**Domain:** Local-first personal AI assistant with voice input and Obsidian integration
**Researched:** 2026-02-18
**Confidence:** HIGH

## Critical Pitfalls

### Pitfall 1: Performance Invisibility Failure

**What goes wrong:**
App consumes significant CPU/RAM when "idle", making it the reason the user's computer is slow. Users uninstall because "my laptop fan is always on since I installed this."

**Why it happens:**
- Background indexing runs continuously instead of throttled
- Event listeners not properly cleaned up
- AI model loaded in memory even when not processing
- WebView/process not truly idle when UI hidden

**How to avoid:**
1. Implement aggressive resource throttling when idle (CPU < 5%, RAM minimal)
2. Use OS-level power management APIs to detect idle state
3. Lazy-load AI model only when transcription needed, unload after inactivity timeout
4. Profile memory/CPU in CI for regressions
5. Set hard limits: < 100MB RAM when idle, < 1% CPU when idle

**Warning signs:**
- Users reporting fan noise after installation
- Memory usage climbing over time without activity
- Background process visible in Activity Monitor even when "closed"

**Phase to address:**
Phase 1 (Core Infrastructure) - Must be architected in from the start, not retrofitted

---

### Pitfall 2: File Race Condition with Obsidian

**What goes wrong:**
Butler and Obsidian simultaneously modify the same file, causing corruption, data loss, or sync conflicts. User's diary entry gets overwritten or truncated.

**Why it happens:**
- Obsidian uses atomic save (writes to temp file, then renames)
- Butler writes directly to files while Obsidian has them open
- No coordination between Butler and Obsidian's file access
- Mobile sync apps add third concurrent writer

**How to avoid:**
1. Never write to files Obsidian is actively editing (track open files)
2. Use file locking or coordination mechanism
3. Write to a separate "inbox" file, let user/automation move to final location
4. Implement conflict resolution that preserves both versions
5. Consider using Obsidian's plugin API for safer file writes

**Warning signs:**
- User reports "file was corrupted"
- Git merge conflicts in Obsidian vault
- Sync plugins showing conflicts
- File content appears truncated after Butler operation

**Phase to address:**
Phase 2 (Obsidian Integration) - Core integration concern

---

### Pitfall 3: AI Memory Without Persistence

**What goes wrong:**
Every conversation starts from zero. The assistant has no memory of previous interactions, user preferences, or ongoing projects. Users frustrated by repeatedly explaining context.

**Why it happens:**
- LLM context windows reset each session
- Developers assume stateless API calls are sufficient
- Memory architecture not designed upfront
- Storage format for "memory" not defined

**How to avoid:**
1. Design persistent memory architecture from day one
2. Use memory files (MEMORY.md pattern) that are read at session start
3. Implement conversation summarization to condense history
4. Store user preferences, ongoing projects, and key decisions durably
5. Consider vector embeddings for semantic memory retrieval

**Warning signs:**
- Users complain "I told you this yesterday"
- Same onboarding questions repeated each session
- No way to reference previous conversations

**Phase to address:**
Phase 3 (AI Processing Pipeline) - Core to AI functionality

---

### Pitfall 4: Model Size vs Hardware Reality

**What goes wrong:**
App requires 16GB+ RAM for the AI model, but target users (including non-technical users on older laptops) have 8GB total. App either crashes or brings system to crawl.

**Why it happens:**
- Testing only on developer machines (MacBook Pro M-series, 32GB+ RAM)
- Assuming users will accept long model download times
- Not accounting for other apps running simultaneously
- Quantization too aggressive ruins quality

**How to avoid:**
1. Target 4-8GB RAM total app footprint maximum
2. Offer tiered models: fast/small (2GB), balanced (4GB), quality (6GB+)
3. Stream model download with progress, allow background download
4. Graceful degradation: if model won't fit, fall back to cloud API with user consent
5. Hardware detection at startup with clear recommendations

**Warning signs:**
- Users report "app won't start" or crashes on launch
- OOM errors in logs
- Fans spin immediately after model load
- Non-technical users returning/refusing to install

**Phase to address:**
Phase 1 (Core Infrastructure) - Hardware requirements define architecture

---

### Pitfall 5: Speech-to-Text Hallucination in Silent Audio

**What goes wrong:**
Transcription inserts fabricated content during silence or background noise. Cornell research found Whisper can hallucinate violent or inappropriate content in silent portions.

**Why it happens:**
- STT models trained to always produce output
- Silence/noise gets interpreted as closest phonetic match
- No confidence threshold filtering
- Background TV/radio being transcribed as user speech

**How to avoid:**
1. Voice Activity Detection (VAD) before STT - only transcribe actual speech
2. Confidence threshold filtering - discard low-confidence segments
3. Post-processing sanity checks (profanity filter, length validation)
4. User review before content is written to Obsidian
5. Clear UI indication of transcription confidence

**Warning signs:**
- Transcription contains content user never said
- Fabricated sentences during pauses
- Background TV/radio content appearing in transcript
- User embarrassment from inappropriate hallucinated content

**Phase to address:**
Phase 3 (AI Processing Pipeline) - Quality control for transcription

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Skip file locking | Faster writes, simpler code | Data corruption, user trust loss | Never |
| Load full model at startup | Instant transcription | High memory, slow startup | Never |
| No idle throttling | Simpler code | Battery drain, fan noise, uninstall | Never |
| Store memory in single JSON | Quick implementation | Corruption risk, no history, merge conflicts | Prototype only |
| Skip VAD before STT | Simpler pipeline | Hallucinated content, user embarrassment | Never |
| Direct file writes | No coordination needed | Race conditions with Obsidian | Never |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Obsidian | Direct file writes while Obsidian has file open | Use plugin API or write to inbox, coordinate access |
| Telegram Bot | Store messages in plain text locally | Encrypt at rest, minimal retention |
| Voice Input | Assume microphone always available | Handle permission denial, device changes gracefully |
| Local LLM | Single model for all tasks | Match model to task (tiny for simple, larger for complex) |
| File Sync (iCloud/Dropbox) | Ignore sync conflicts | Detect sync status, warn user, implement conflict resolution |
| macOS/Windows | Assume same file system behavior | Test both, handle case sensitivity, path separators |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Memory leak in event loop | RAM grows over hours/days | Profile in CI, use WeakRef for caches, periodic cleanup | After days of uptime |
| Indexing on every keystroke | UI freezes when typing | Debounce, index on idle, background thread | Large vaults (10k+ files) |
| Embedding all history | Startup takes minutes | Lazy embedding, cache embeddings, incremental updates | After months of use |
| WebView bloat | RAM > 500MB for UI | Periodic WebView cleanup, minimize DOM, no memory leaks | After extended use |
| Model swap to disk | System unresponsive | Never exceed available RAM, smaller models | 8GB machines |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Store Telegram API key in code | Key exposed in git/binary | Environment variables, OS keychain |
| Log user messages | Privacy violation, data leak | Never log content, only metadata (timestamp, type) |
| Unencrypted local database | Anyone with file access sees all | Encrypt database with user-derived key |
| Accept all Telegram messages | Spam/injection attacks | Whitelist allowed senders, validate input |
| No input validation on transcriptions | Prompt injection to LLM | Sanitize input, limit length, validate structure |
| Model download without verification | Supply chain attack | Verify checksums, use HTTPS only |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Model download during onboarding | User gives up waiting | Background download, show progress, allow exploration while downloading |
| No transcription preview | Wrong content goes to Obsidian | Always show preview, require confirmation |
| Technical error messages | Non-technical users confused | "Something went wrong with your recording" + actionable steps |
| Assumption of technical knowledge | Mom can't set it up | Zero-config default, hide advanced options |
| No offline fallback | App useless without internet | Full offline mode, cloud as optional enhancement |
| Silent failures | User thinks it worked, but it didn't | Always confirm actions, log failures visibly |

## "Looks Done But Isn't" Checklist

- [ ] **Idle Performance:** App truly invisible when idle — verify RAM < 100MB, CPU < 1% in Activity Monitor
- [ ] **File Safety:** Multiple concurrent writes handled — test with Obsidian open, sync running, Butler writing
- [ ] **Memory Persistence:** Context survives app restart — close and reopen, verify memory intact
- [ ] **Low-Spec Hardware:** Works on 8GB RAM machine — test on actual low-spec hardware, not VM with dedicated RAM
- [ ] **Transcription Quality:** Silent audio doesn't hallucinate — test with quiet room, background TV, coughing
- [ ] **Telegram Security:** API key not in git — grep for keys, verify keychain storage
- [ ] **Non-Technical User:** Mom can install and use — actual user testing, not developer assumption
- [ ] **Error Recovery:** Graceful degradation when things fail — disconnect internet, fill disk, corrupt file

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| File corruption | HIGH | Restore from backup, implement auto-backup, conflict copies |
| Memory leak | MEDIUM | Restart app, identify leak source, patch and update |
| Model too large | MEDIUM | Download smaller model, add model selection UI |
| Race condition data loss | HIGH | Restore from git/time machine, implement file versioning |
| Hallucinated content in notes | LOW | User can edit/delete, add confidence indicator |
| Lost memory context | MEDIUM | Re-explain preferences, add memory export/backup |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Performance Invisibility | Phase 1 | CPU/RAM profiling in CI, idle metrics dashboard |
| File Race Condition | Phase 2 | Concurrent write stress test, conflict scenario tests |
| AI Memory Without Persistence | Phase 3 | Session restart test, memory file validation |
| Model Size vs Hardware | Phase 1 | Hardware detection test, 8GB RAM machine test |
| STT Hallucination | Phase 3 | Silent audio test suite, profanity filter test |
| Non-technical User Onboarding | Phase 4 | Mom test (actual user testing), zero-config verification |
| Security (Telegram keys) | Phase 1 | Grep for secrets, keychain integration test |
| Error Recovery | Phase 4 | Failure injection tests, graceful degradation verification |

## Sources

- Aalto University: "Local-First Software: Promises and Pitfalls" (2025) - Schema evolution, forward/backward compatibility challenges
- Cornell University: "Careless Whisper: Speech-to-Text Hallucination Harms" (2024) - STT hallucination in silent audio
- OpenClaw Personal AI Agent Lessons (2026) - Memory persistence, model selection, context anchoring
- DockYard: "Challenges and Trade-offs of Local AI" (2025) - Computational constraints, model updates
- Tauri GitHub Issues: Memory leak patterns, event loop cleanup
- Electron Performance Docs: Idle optimization, memory management
- Obsidian Plugin Issues: Race conditions, file modification conflicts, plugin isolation
- Obsidian Omnisearch Issues: Indexing performance, memory consumption
- LocalLLM VRAM Calculator: Hardware requirements for local models

---
*Pitfalls research for: Local-first personal AI assistant with voice input and Obsidian integration*
*Researched: 2026-02-18*
