---
phase: 01-core-infrastructure
plan: 02
subsystem: core
tags: [plugin-system, task-queue, throttling, huey, capabilities]

requires:
  - phase: 01-01
    provides: Event bus, configuration, logging, safe_write

provides:
  - Capability registry for loose plugin coupling
  - Plugin base class with lifecycle management
  - Plugin manifest schema and validation
  - Plugin manager with auto-discovery
  - Huey task queue with SQLite backend
  - Smart throttling decorators

affects:
  - All plugins (use base class, register capabilities)
  - Voice input pipeline (background transcription tasks)
  - Daily writer (throttled note writing)
  - AI layer (capability provider/consumer)

tech-stack:
  added: [huey, psutil]
  patterns:
    - "Thread-safe capability registry with RLock"
    - "Plugin auto-discovery with dependency ordering"
    - "Resource-aware task throttling"
    - "SQLite-backed task queue for crash recovery"

key-files:
  created:
    - src/core/capabilities.py
    - src/core/plugin_manager.py
    - src/core/task_queue.py
    - src/core/throttling.py
    - src/plugins/base.py
    - src/plugins/manifest.py
    - tests/core/test_capabilities.py
    - tests/core/test_plugin_manager.py
    - tests/core/test_task_queue.py
    - tests/core/test_throttling.py
    - tests/plugins/test_base.py

key-decisions:
  - "Huey with SQLite backend for zero-config task persistence"
  - "ThrottledException integrates with Huey retry mechanism"
  - "Plugin manifests use YAML for human-editable configuration"
  - "Capability registry uses blinker Signal for registration events"

requirements-completed: [CORE-02, CORE-04, CORE-07]

duration: 23min
completed: 2026-02-18
---
# Phase 1 Plan 2: Infrastructure Layer Summary

**Plugin system with auto-discovery, Huey task queue with smart throttling, and capability registry for loose coupling - 195 passing tests.**

## Performance

- **Duration:** 23 min
- **Started:** 2026-02-18T09:40:09Z
- **Completed:** 2026-02-18T10:03:16Z
- **Tasks:** 5
- **Files modified:** 11

## Accomplishments

- Thread-safe capability registry enabling plugins to expose/consume features without hard dependencies
- Plugin base class with manifest-driven lifecycle and capability registration
- Plugin manager with auto-discovery, dependency ordering, and graceful error handling
- Huey task queue with SQLite backend for crash recovery and background processing
- Smart throttling decorators checking CPU/RAM/power with Huey retry integration

## Task Commits

1. **Task 1: Capability Registry** - `af2e7ce` (feat)
2. **Task 2: Plugin Base Class and Manifest** - `9a04eeb` (feat)
3. **Task 3: Plugin Manager with Auto-Discovery** - `f878c05` (feat)
4. **Task 4: Task Queue with Huey** - `8840320` (feat)
5. **Task 5: Smart Throttling** - `8e77c4b` (feat)

**Plan metadata:** [pending] (docs: complete plan)

## Files Created/Modified

- `src/core/capabilities.py` - Thread-safe capability registry with Signal emission
- `src/core/plugin_manager.py` - Plugin discovery, dependency resolution, lifecycle management
- `src/core/task_queue.py` - Huey SQLite backend with task/periodic decorators
- `src/core/throttling.py` - Resource-aware throttling decorators
- `src/plugins/base.py` - Abstract base plugin class with capability/event integration
- `src/plugins/manifest.py` - YAML manifest schema and validation
- `tests/core/test_capabilities.py` - 26 tests for capability registry
- `tests/core/test_plugin_manager.py` - 23 tests for plugin manager
- `tests/core/test_task_queue.py` - 22 tests for task queue
- `tests/core/test_throttling.py` - 25 tests for throttling
- `tests/plugins/test_base.py` - 26 tests for plugin base and manifest

## Decisions Made

1. **Huey with SQLite backend**: Chosen over Redis for zero external dependencies. SQLite provides crash recovery via persisted task queue.

2. **ThrottledException pattern**: Throttling raises an exception that Huey's retry mechanism can catch, automatically rescheduling tasks when resources become available.

3. **YAML manifests over JSON**: More human-editable for plugin developers, supports comments for documentation.

4. **Thread-safe capability registry**: Uses RLock for concurrent access during parallel plugin loading.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

1. **Huey API differences**: The `schedule()` method requires `eta` or `delay` parameters - for immediate queueing, call the task directly. Fixed tests to use correct API.

2. **Periodic task pickling**: Local functions cannot be pickled for periodic tasks - adjusted tests to use Huey directly instead of the decorator wrapper.

3. **Result object attributes**: Huey's Result uses `id` not `task_id` - fixed test assertions.

All issues were minor test adjustments to match Huey's actual API.

## User Setup Required

None - no external service configuration required. The task queue creates its SQLite database at `~/.butler/data/tasks.db` automatically.

## Next Phase Readiness

- Plugin system ready for voice_input and daily_writer plugins
- Task queue ready for background transcription
- Capability registry ready for AI layer integration
- All infrastructure tests passing (195 total)

**Ready for Phase 2: Voice Input Pipeline**

---
*Phase: 01-core-infrastructure*
*Completed: 2026-02-18*
