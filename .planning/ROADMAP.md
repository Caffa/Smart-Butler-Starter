# ROADMAP: Smart Butler 2.0

**Based on:** v4 Project Plan (Stages 0-13)  
**Requirements:** 53 v1 requirements  
**Depth:** Standard  
**Created:** 2025-02-18

---

## Phases

- [ ] **Phase 1: Core Infrastructure** - Event bus, plugin system, voice input, daily writer, installation
- [ ] **Phase 2: Notifications & Feedback** - macOS notifications and audio feedback
- [ ] **Phase 3: Telegram & Alfred** - Multi-device input via Telegram bot and Alfred workflow
- [ ] **Phase 4: AI Text Polish & Day Digest** - LLM text cleaning and nightly summaries
- [ ] **Phase 5: Note Router** - AI-powered note classification and routing
- [ ] **Phase 6: Memory & Search** - Vector memory with ChromaDB and semantic search
- [ ] **Phase 7: Wake Word & Reflection** - Hands-free activation and nightly insights
- [ ] **Phase 8: Menubar App** - macOS menu bar interface with quick access
- [ ] **Phase 9: Action Items** - Extract and track tasks from notes
- [ ] **Phase 10: Deductions & Smarter Digest** - Pattern detection and enhanced summaries
- [ ] **Phase 11: Link Resolution** - YouTube transcription and Readwise integration
- [ ] **Phase 12: Plugin Manager & TUI** - Visual plugin management and configuration
- [ ] **Phase 13: Distribution & Polish** - PKG installer and final refinements

---

## Phase Details

### Phase 1: Core Infrastructure
**Goal:** Users can install Butler and capture voice memos that appear in Obsidian  
**Depends on:** Nothing (first phase)  
**Requirements:** CORE-01, CORE-02, CORE-03, CORE-04, CORE-05, CORE-06, CORE-07, VOICE-01, VOICE-02, VOICE-03, VOICE-04, OUTPUT-01, OUTPUT-02, OUTPUT-03, OUTPUT-04, INSTALL-01, INSTALL-02, INSTALL-03

**Success Criteria** (what must be TRUE):
1. User runs one install command and Butler is ready to use
2. Voice memos dropped into watched folder auto-transcribe and appear in Obsidian daily file
3. Daily notes include timestamps and Obsidian frontmatter
4. Plugin system loads enabled plugins without manual intervention
5. Safe write protocol prevents data corruption when Obsidian is editing files
6. Task queue survives crashes and resumes processing on restart

---

### Phase 2: Notifications & Feedback
**Goal:** Users receive immediate feedback on Butler's activity  
**Depends on:** Phase 1  
**Requirements:** NOTIFY-01, NOTIFY-02, NOTIFY-03

**Success Criteria** (what must be TRUE):
1. User sees macOS notification when note is successfully written
2. Audio tone plays when Butler starts processing voice input
3. Different tones indicate success, waiting, and failure states
4. Notification plugin can be disabled without breaking other features

---

### Phase 3: Telegram & Alfred
**Goal:** Users can capture thoughts from any device via Telegram or Mac via Alfred  
**Depends on:** Phase 1  
**Requirements:** TELEGRAM-01, TELEGRAM-02, TELEGRAM-03, TELEGRAM-04, TELEGRAM-05, ALFRED-01, ALFRED-02

**Success Criteria** (what must be TRUE):
1. User sends Telegram message and it appears in Obsidian within 30 seconds
2. User sends Telegram voice message and transcribed text appears in Obsidian
3. /help command displays friendly emoji-based command list
4. /status command shows Butler health and last note time
5. Bot setup wizard guides through BotFather configuration
6. Alfred workflow sends quick notes via keyboard shortcut
7. Alfred workflow imports with double-click on .alfredworkflow file

---

### Phase 4: AI Text Polish & Day Digest
**Goal:** Voice notes are cleaned by AI and daily summaries are generated  
**Depends on:** Phase 1, Phase 3  
**Requirements:** POLISH-01, POLISH-02, POLISH-03, POLISH-04, DIGEST-01, DIGEST-02, DIGEST-03, DIGEST-04

**Success Criteria** (what must be TRUE):
1. Filler words and run-on sentences are removed from transcribed voice notes
2. If Ollama is unavailable, raw text passes through without blocking
3. Heavy processing is deferred when system is busy
4. At 23:30 daily, Butler generates summary of day's notes
5. Digest file includes wikilink back to daily note

---

### Phase 5: Note Router
**Goal:** Notes are intelligently classified and routed to appropriate files  
**Depends on:** Phase 1, Phase 4  
**Requirements:** ROUTER-01, ROUTER-02, ROUTER-03, ROUTER-04

**Success Criteria** (what must be TRUE):
1. Project-related notes automatically append to projects/{slug}.md
2. Daily notes contain wikilink to project file for routed notes
3. Exact duplicate notes within 24h are skipped (SHA-256 deduplication)
4. All classification decisions are logged to prompt-history file

---

### Phase 6: Memory & Search
**Goal:** Users can search their notes conversationally  
**Depends on:** Phase 1, Phase 5  
**Requirements:** MEMORY-01, MEMORY-02, MEMORY-03, MEMORY-04

**Success Criteria** (what must be TRUE):
1. Every written note is automatically embedded and stored in vector memory
2. User runs `butler ask "what did I say about gardening?"` and gets relevant results
3. Search results include metadata (date, source, project) for context
4. Memory persists across Butler restarts

---

### Phase 7: Wake Word & Reflection
**Goal:** Hands-free activation and nightly insights  
**Depends on:** Phase 1, Phase 2, Phase 6  
**Requirements:** WAKE-01, WAKE-02, WAKE-03, REFLECT-01, REFLECT-02, REFLECT-03, REFLECT-04

**Success Criteria** (what must be TRUE):
1. User says "Hey Butler" and hears confirmation tone
2. Voice recording starts automatically and stops on silence
3. Nightly reflection reads last 7 days and writes insights to YYYY-MM-DD-reflection.md
4. Reflections include wikilinks to referenced notes
5. Reflection only runs at night (configurable time)

---

### Phase 8: Menubar App
**Goal:** Quick visual access to Butler status and functions  
**Depends on:** Phase 1, Phase 2  
**Requirements:** MENUBAR-01, MENUBAR-02, MENUBAR-03, MENUBAR-04, MENUBAR-05

**Success Criteria** (what must be TRUE):
1. Butler icon appears in macOS menu bar at all times
2. Menu shows last 5 events with emoji icons and relative timestamps
3. Quick note field allows typing and pressing Enter to capture
4. "Open Today's Journal" launches Obsidian to current daily file
5. Icon changes to indicate: idle, processing, throttled, or error state

---

### Phase 9: Action Items
**Goal:** Open tasks are extracted and tracked; guided conversations and morning briefings  
**Depends on:** Phase 1, Phase 4  
**Requirements:** ACTION-01, ACTION-02, ACTION-03, CONV-01 (v2), CONTR-01 (v2), BRIEF-01 (v2)

**Success Criteria** (what must be TRUE):
1. Unchecked [ ] tasks in notes are extracted and added to action-items.md
2. Each task includes date and wikilink to source note
3. Completed [x] tasks are ignored
4. Butler detects contradictions between new notes and existing memory
5. Morning briefing Telegram message sent with open loops and priorities
6. Guided conversation initiates journaling prompts via Telegram

---

### Phase 10: Deductions & Smarter Digest
**Goal:** Butler surfaces patterns and insights across notes  
**Depends on:** Phase 4, Phase 6  
**Requirements:** DEDUCT-01 (v2), DEDUCT-02 (v2), SMART-01 (v2)

**Success Criteria** (what must be TRUE):
1. Deductions plugin surfaces recurring themes across multiple notes
2. Smarter digest incorporates memory context for richer summaries
3. Insights are written to dedicated deductions.md file
4. Digest quality noticeably improved vs basic day-digest

---

### Phase 11: Link Resolution
**Goal:** YouTube videos and articles are processed and referenced  
**Depends on:** Phase 1, Phase 4  
**Requirements:** YOUTUBE-01, YOUTUBE-02, YOUTUBE-03, YOUTUBE-04, READWISE-01 (v2)

**Success Criteria** (what must be TRUE):
1. YouTube URLs in notes trigger audio download and transcription
2. Transcripts saved to reference/youtube/{slug}.md with metadata
3. Optional summary appended to daily journal with source link
4. Readwise integration sends article URLs to user's Readwise account
5. Link processing runs asynchronously without blocking note capture

---

### Phase 12: Plugin Manager & TUI
**Goal:** Users can manage plugins via visual interface  
**Depends on:** Phase 1, Phase 8  
**Requirements:** PLUGMAN-01 (v2), TCONF-01 (v2)

**Success Criteria** (what must be TRUE):
1. `butler config` launches TUI for browsing and toggling plugins
2. Plugins are grouped by tags (input, ai, output, ux)
3. Plugin dependencies shown before enabling
4. Low-confidence transcription segments are visually highlighted in output
5. TUI works in both terminal and browser modes

---

### Phase 13: Distribution & Polish
**Goal:** Butler is installable via standard macOS distribution  
**Depends on:** All previous phases  
**Requirements:** PKG installer, distribution polish

**Success Criteria** (what must be TRUE):
1. User downloads .pkg file and installs via double-click
2. PKG includes all dependencies and models
3. Post-install wizard configures Obsidian vault path
4. Uninstaller properly removes all Butler files
5. Rollback checkpoints available at each phase via Git tags

---

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Core Infrastructure | 0/4 | Planned | - |
| 2. Notifications | 0/1 | Not started | - |
| 3. Telegram & Alfred | 0/1 | Not started | - |
| 4. AI Polish & Digest | 0/1 | Not started | - |
| 5. Note Router | 0/1 | Not started | - |
| 6. Memory & Search | 0/1 | Not started | - |
| 7. Wake Word & Reflection | 0/1 | Not started | - |
| 8. Menubar | 0/1 | Not started | - |
| 9. Action Items | 0/1 | Not started | - |
| 10. Deductions | 0/1 | Not started | - |
| 11. Link Resolution | 0/1 | Not started | - |
| 12. Plugin Manager | 0/1 | Not started | - |
| 13. Distribution | 0/1 | Not started | - |

---

## Dependencies

```
Phase 1 (Foundation)
    ↓
    ├──→ Phase 2 (Notifications)
    │        ↓
    │     Phase 8 (Menubar)
    │
    ├──→ Phase 3 (Telegram/Alfred)
    │        ↓
    │     Phase 4 (AI Polish)
    │        ↓
    │     Phase 5 (Router)
    │        ↓
    │     Phase 6 (Memory)
    │        ↓
    │     Phase 9 (Action Items)
    │        ↓
    │     Phase 10 (Deductions)
    │        ↓
    │     Phase 11 (Links)
    │
    ├──→ Phase 7 (Wake Word)
    │     (depends on 1, 2, 6)
    │
    └──→ Phase 12 (TUI)
          (depends on 1, 8)
    
    All phases → Phase 13 (Distribution)
```

---

## Coverage

**Total v1 requirements:** 53  
**Elevated from v2:** 8 (phases 9-12)  
**Total mapped:** 61  
**Unmapped:** 0 ✓

### Requirement Distribution by Phase

| Phase | Requirements | v2 Elevated |
|-------|--------------|-------------|
| 1 | 18 | 0 |
| 2 | 3 | 0 |
| 3 | 7 | 0 |
| 4 | 8 | 0 |
| 5 | 4 | 0 |
| 6 | 4 | 0 |
| 7 | 7 | 0 |
| 8 | 5 | 0 |
| 9 | 3 | 3 |
| 10 | 0 | 3 |
| 11 | 4 | 1 |
| 12 | 0 | 1 |
| 13 | 0 | 0 |
| **Total** | **53** | **8** |

---

*Created by GSD Roadmapper*  
*Template: /Users/caffae/.config/opencode/get-shit-done/templates/roadmap.md*
