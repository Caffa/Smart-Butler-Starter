---
phase: quick
plan: 1
type: execute
wave: 1
depends_on: []
files_modified:
  - src/plugins/voice_input/plugin.py
  - tests/plugins/test_voice_input.py
autonomous: true

must_haves:
  truths:
    - Watch path points to actual Voice Memos storage location
    - Voice Memos system files are excluded from processing
    - Hidden files starting with '.' are ignored
    - .DS_Store files are ignored
    - Audio files are still processed normally
  artifacts:
    - path: src/plugins/voice_input/plugin.py
      provides: "Updated watch path and file exclusion logic in VoiceInputPlugin"
    - path: tests/plugins/test_voice_input.py
      provides: "Tests for file exclusion"
  key_links:
    - from: _load_config
      to: default_watch_path
      via: "default path constant"
    - from: scan_folder
      to: _should_process_file
      via: "filter call in iteration"
    - from: process_file
      to: _should_process_file
      via: "early return check"
---

<objective>
Change watch path to actual Voice Memos location and exclude system files from processing.

Purpose: The Voice Memos app stores recordings in `~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings`, not `~/Music/Voice Memos`. The plugin should watch the correct location and filter out system files like .DS_Store.
Output: Updated VoiceInputPlugin with correct watch path, file exclusion logic, and tests.
</objective>

<execution_context>
@/Users/caffae/.config/opencode/get-shit-done/workflows/execute-plan.md
@/Users/caffae/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@/Users/caffae/Local Projects/Smart-Butler-V2/src/plugins/voice_input/plugin.py
@/Users/caffae/Local Projects/Smart-Butler-V2/tests/plugins/test_voice_input.py

The VoiceInputPlugin currently watches `~/Music/Voice Memos` folder for new audio files. This needs to be changed to the actual Voice Memos storage location: `~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings`.

Additionally, the plugin doesn't exclude system files like `.DS_Store` or other hidden files that macOS generates in that folder.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Update default watch path to actual Voice Memos location</name>
  <files>src/plugins/voice_input/plugin.py</files>
  <action>
    Change the default watch path from `~/Music/Voice Memos` to `~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings`.

    Update the `_load_config()` method to use the new default:
    - Change `default_watch_path = "~/Music/Voice Memos"` to `default_watch_path = "~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings"`

    This is the actual location where the Voice Memos app stores recordings on macOS.

  </action>
  <verify>grep -n "Group Containers" src/plugins/voice_input/plugin.py</verify>
  <done>Default watch path points to ~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings</done>
</task>

<task type="auto">
  <name>Task 2: Add file exclusion logic to plugin</name>
  <files>src/plugins/voice_input/plugin.py</files>
  <action>
    Add a `_should_process_file()` method to VoiceInputPlugin that returns False for files that should be excluded:

    1. Files starting with '.' (hidden files)
    2. .DS_Store files (macOS metadata)
    3. Files without supported audio extensions (already exists in _is_audio_file)

    Update the following methods to use this new check:
    - `scan_folder()`: Filter files with `_should_process_file()` before adding to list
    - `process_file()`: Early return False if `_should_process_file()` returns False

    The method should log at debug level when skipping a file, e.g., "Skipping system file: .DS_Store"

    Follow the existing code style in the plugin - use type hints, docstrings, and the logger.

  </action>
  <verify>grep -n "_should_process_file" src/plugins/voice_input/plugin.py</verify>
  <done>_should_process_file method exists, is called from scan_folder and process_file, excludes hidden files and .DS_Store</done>
</task>

<task type="auto">
  <name>Task 3: Add tests for file exclusion</name>
  <files>tests/plugins/test_voice_input.py</files>
  <action>
    Add test cases to the TestVoiceInputPlugin class:
    
    1. `test_should_process_file_hidden` - Verify files starting with '.' are excluded
    2. `test_should_process_file_ds_store` - Verify .DS_Store is excluded
    3. `test_scan_folder_excludes_system_files` - Verify scan_folder ignores hidden files
    4. `test_process_file_skips_system_files` - Verify process_file returns False for hidden files
    
    Test that normal audio files (test.m4a, test.mp3) still return True.
    
    Create temporary files in tests using tempfile, don't use real Voice Memos folder.
  </action>
  <verify>bunx pytest tests/plugins/test_voice_input.py -v -k "should_process"</verify>
  <done>All new tests pass, verify command shows 4 passing tests for file exclusion</done>
</task>

<task type="auto">
  <name>Task 4: Verify all existing tests still pass</name>
  <files>tests/plugins/test_voice_input.py</files>
  <action>
    Run the full test suite for the voice_input plugin to ensure the changes don't break existing functionality.
  </action>
  <verify>bunx pytest tests/plugins/test_voice_input.py -v</verify>
  <done>All tests in test_voice_input.py pass, including existing tests for scan_folder and process_file</done>
</task>

</tasks>

<verification>
- grep -n "_should_process_file" src/plugins/voice_input/plugin.py (method exists)
- grep -n "Skipping.*file" src/plugins/voice_input/plugin.py (debug logging present)
- bunx pytest tests/plugins/test_voice_input.py -v (all tests pass)
</verification>

<success_criteria>

- Default watch path is `~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings`
- VoiceInputPlugin has a `_should_process_file()` method that excludes hidden files and .DS_Store
- `scan_folder()` and `process_file()` use the exclusion check
- Debug logging shows when files are skipped
- All existing tests pass
- New tests verify exclusion logic works correctly
  </success_criteria>

<output>
After completion, create `.planning/quick/1-exclude-voice-memos-from-file-watching/1-SUMMARY.md`
</output>
