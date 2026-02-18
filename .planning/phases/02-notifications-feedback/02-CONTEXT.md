# Phase 2: Notifications & Feedback - Context

**Gathered:** 2026-02-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Provide immediate feedback to users through macOS notifications and audio tones when Butler processes notes. This phase delivers the UX feedback layer — notifications for status updates and audio cues for processing states. The plugin must be fully removable without breaking other features.

</domain>

<decisions>
## Implementation Decisions

### Audio tone design

- Use macOS system sounds (Glass, Hero, Pop, Basso, etc.) — no custom audio files needed for MVP
- Distinct sounds per state: different system sound for success, waiting, and failure
- Follow system volume — no separate Butler volume control
- Global mute toggle in config that the notifications plugin respects (future plugins will also honor this)

### Notification content

- **Success notification:** Show content preview + file location
  - For Obsidian files: Display vault name + file name (not full filesystem path)
  - For Apple Notes: Display just the note name
- **Error notification:** Simplified error message with emoji indicating what failed + "View log" button that opens log file for full details
- **Click action:** Open in Obsidian (for success notifications)
- **Timing:** Immediate — show as soon as note is written, no artificial delay

### Claude's Discretion

- Specific system sound choices (which sound for which state)
- Notification auto-dismiss timing
- Stacking behavior for rapid-fire notifications
- Whether "waiting" state even needs a notification (vs just audio tone)

</decisions>

<specifics>
## Specific Ideas

- User wants Obsidian paths to feel native: "vault/Folder/file.md" not "/Users/name/Library/..."
- Error notifications should be actionable — the "View log" button gives power users depth
- Global mute is a Butler-wide concern, not just this plugin — other plugins should honor it too

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

_Phase: 02-notifications-feedback_
_Context gathered: 2026-02-19_
