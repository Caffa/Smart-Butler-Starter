# ROADMAP: Smart Butler 2.0

**Based on:** v4 Project Plan (Stages 0-13)  
**Requirements:** 53 v1 requirements  
**Depth:** Standard  
**Created:** 2025-02-18

---

## Milestones

- ✅ **v1.0 Core & Notifications MVP** — Phases 1-2 (shipped 2026-02-19)
- 🚧 **v1.1 Telegram & Alfred** — Phases 3-4 (in progress)

---

## Phases

<details>
<summary>✅ v1.0 Core & Notifications MVP (Phases 1-2) — SHIPPED 2026-02-19</summary>

- [x] Phase 1: Core Infrastructure (5/5 plans) — completed 2026-02-18
- [x] Phase 2: Notifications & Feedback (2/2 plans) — completed 2026-02-19

</details>

### 🚧 v1.1 Telegram & Alfred (In Progress)

- [ ] Phase 3: Telegram & Alfred (0/1 plans) — pending
- [ ] Phase 4: AI Text Polish & Day Digest (0/1 plans) — pending

### Future Phases (Planned)

- [ ] Phase 5: Note Router
- [ ] Phase 6: Memory & Search
- [ ] Phase 7: Wake Word & Reflection
- [ ] Phase 8: Menubar App
- [ ] Phase 9: Action Items
- [ ] Phase 10: Deductions & Smarter Digest
- [ ] Phase 11: Link Resolution
- [ ] Phase 12: Plugin Manager & TUI
- [ ] Phase 13: Distribution & Polish

---

## Progress

| Phase                     | Milestone | Plans Complete | Status      | Completed  |
| ------------------------- | --------- | -------------- | ----------- | ---------- |
| 1. Core Infrastructure    | v1.0      | 5/5            | Complete    | 2026-02-18 |
| 2. Notifications          | v1.0      | 2/2            | Complete    | 2026-02-19 |
| 3. Telegram & Alfred      | v1.1      | 0/1            | Not started | -          |
| 4. AI Polish & Digest     | v1.1      | 0/1            | Not started | -          |
| 5. Note Router            | v2.0      | 0/1            | Not started | -          |
| 6. Memory & Search        | v2.0      | 0/1            | Not started | -          |
| 7. Wake Word & Reflection | v2.0      | 0/1            | Not started | -          |
| 8. Menubar                | v2.0      | 0/1            | Not started | -          |
| 9. Action Items           | v2.0      | 0/1            | Not started | -          |
| 10. Deductions            | v2.0      | 0/1            | Not started | -          |
| 11. Link Resolution       | v2.0      | 0/1            | Not started | -          |
| 12. Plugin Manager        | v2.0      | 0/1            | Not started | -          |
| 13. Distribution          | v2.0      | 0/1            | Not started | -          |

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

| Phase     | Requirements | v2 Elevated |
| --------- | ------------ | ----------- |
| 1         | 18           | 0           |
| 2         | 3            | 0           |
| 3         | 7            | 0           |
| 4         | 8            | 0           |
| 5         | 4            | 0           |
| 6         | 4            | 0           |
| 7         | 7            | 0           |
| 8         | 5            | 0           |
| 9         | 3            | 3           |
| 10        | 0            | 3           |
| 11        | 4            | 1           |
| 12        | 0            | 1           |
| 13        | 0            | 0           |
| **Total** | **53**       | **8**       |

---

_Created by GSD Roadmapper_  
_Template: /Users/caffae/.config/opencode/get-shit-done/templates/roadmap.md_
