---
phase: quick
plan: 1
subsystem: plugins/voice_input
tags: [file-watching, filtering, voice-memos, system-files]
dependency-graph:
  requires: []
  provides: []
  affects: [src/plugins/voice_input/plugin.py]
tech-stack:
  added: []
  patterns: [file-exclusion-filter, early-return-guard]
key-files:
  created: []
  modified:
    - src/plugins/voice_input/plugin.py
    - tests/plugins/test_voice_input.py
decisions: []
metrics:
  duration: 5min
  completed-date: 2026-02-19
---

# Quick Task 1: Exclude Voice Memos from File Watching

**One-liner:** VoiceInputPlugin now excludes hidden files and .DS_Store from processing to avoid unnecessary transcription attempts on system files.

## Summary

Added file exclusion logic to VoiceInputPlugin to prevent the system from attempting to process hidden files (starting with '.') and macOS metadata files (.DS_Store) that appear in the Voice Memos folder. This reduces unnecessary processing and log noise.

## Changes Made

### Source Code

**src/plugins/voice_input/plugin.py:**

- Added `_should_process_file()` method that filters:
  - Hidden files (starting with '.')
  - .DS_Store files (macOS metadata)
  - Non-audio files (delegates to existing `_is_audio_file()`)
- Updated `scan_folder()` to use `_should_process_file()` instead of `_is_audio_file()`
- Updated `process_file()` to use `_should_process_file()` for early return
- Added debug logging when files are skipped

### Tests

**tests/plugins/test_voice_input.py:**

- Added 5 new test cases:
  - `test_should_process_file_hidden`: Verify hidden files are excluded
  - `test_should_process_file_ds_store`: Verify .DS_Store is excluded
  - `test_should_process_file_audio_extensions`: Verify audio files still work
  - `test_scan_folder_excludes_system_files`: Verify scan_folder ignores hidden files
  - `test_process_file_skips_system_files`: Verify process_file returns False for hidden files

## Verification

```bash
# All tests pass (16 total)
bunx pytest tests/plugins/test_voice_input.py -v

# File exclusion tests specifically (5 tests)
bunx pytest tests/plugins/test_voice_input.py -v -k "should_process or excludes or skips"
```

**Results:** All 16 tests pass, including 5 new tests for file exclusion logic.

## Implementation Details

### File Exclusion Logic

The `_should_process_file()` method implements a guard-clause pattern:

1. **Early returns** for excluded file types
2. **Debug logging** for observability
3. **Centralized filter** used by both `scan_folder()` and `process_file()`

### Test Coverage

New tests verify:

- Hidden file detection (multiple patterns)
- .DS_Store exclusion
- Audio file acceptance (positive cases)
- Integration with scan_folder iteration
- Integration with process_file early return

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check

- [x] `_should_process_file` method exists in plugin
- [x] Debug logging present for skipped files
- [x] `scan_folder()` uses the new filter
- [x] `process_file()` uses the new filter
- [x] All 16 tests pass
- [x] New tests verify exclusion logic works correctly

## Commits

| Hash    | Message                                                     |
| ------- | ----------------------------------------------------------- |
| 4a6552f | feat(quick-1): add file exclusion logic to VoiceInputPlugin |
| 9369484 | test(quick-1): add tests for file exclusion logic           |
| 1c51504 | fix(quick-1): correct docstring syntax in tests             |
