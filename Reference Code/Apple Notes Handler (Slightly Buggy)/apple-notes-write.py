def append_to_apple_note(note_title: str, content: str) -> bool:
    """
    Append timestamped content to an Apple Note by title.
    Creates the note if it doesn't exist.
    Returns True on success, False on failure.
    """
    if not content or not content.strip():
        return False
    safe_content = content.replace('"', '\\"').replace("\n", "<br>")
    safe_note_name = note_title.replace('"', '\\"')
    applescript = f'''
    tell application "Notes"
        tell default account
            if not (exists note "{safe_note_name}") then
                make new note with properties {{name:"{safe_note_name}", body:""}}
            end if

            set targetNote to note "{safe_note_name}"
            set oldBody to body of targetNote

            set newEntry to "<hr><p><b>" & (do shell script "date '+%Y-%m-%d %H:%M'") & "</b><br>" & "{safe_content}" & "</p>"

            if oldBody ends with "</body></html>" then
                set newBody to text 1 thru -15 of oldBody & newEntry & "</body></html>"
            else
                set newBody to oldBody & newEntry
            end if
            set body of targetNote to newBody
        end tell
    end tell
    '''
    try:
        subprocess.run(
            ["osascript", "-e", applescript],
            check=True,
            timeout=15,
            capture_output=True,
        )
        log_debug(f"✅ AppleScript Success: Appended to '{note_title}'")
        return True
    except subprocess.CalledProcessError as e:
        log_debug(f"❌ AppleScript Failed for '{note_title}': {e}")
        return False
    except subprocess.TimeoutExpired:
        log_debug(f"❌ AppleScript timed out for '{note_title}'")
        return False
    except Exception as e:
        log_debug(f"❌ AppleScript exception for '{note_title}': {e}")
        return False


def handle_apple_notes_general(content):
    log_debug("Logging to Apple Notes (General AI)...")

    mapping = resolve_apple_notes_target_from_memories(content)
    note_name = mapping.get("note_name") or "Inbox"
    tag = mapping.get("tag") or "#inbox"

    safe_content = content.replace('"', '\\"').replace("\n", "<br>")
    safe_note_name = note_name.replace('"', '\\"')
    safe_tag = tag.replace('"', '\\"')

    applescript = f'''
    tell application "Notes"
        tell default account
            if not (exists note "{safe_note_name}") then
                make new note with properties {{name:"{safe_note_name}", body:"<h1>{safe_note_name}</h1><p>{safe_tag}</p>"}}
            end if

            set targetNote to note "{safe_note_name}"
            set oldBody to body of targetNote

            -- Append: timestamp + content only (tag is set once when the note is created)
            set newEntry to "<hr><p><b>" & (do shell script "date '+%Y-%m-%d %H:%M'") & "</b><br>" & "{safe_content}" & "</p>"

            -- Inject the new entry before the closing body tags
            if oldBody ends with "</body></html>" then
                set newBody to text 1 thru -15 of oldBody & newEntry & "</body></html>"
            else
                set newBody to oldBody & newEntry
            end if
            set body of targetNote to newBody
        end tell
    end tell
    '''

    try:
        subprocess.run(["osascript", "-e", applescript], check=True)
        log_debug(f"✅ AppleScript Success: Appended to '{note_name}' ({tag})")
        if mapping.get("memory_written_path"):
            log_debug(f"Memory recorded: {mapping.get('memory_written_path')}")
        return f"External | Apple Notes (General): {note_name}"
    except Exception as e:
        log_debug(f"❌ AppleScript Failed (General): {e}")
        return "❌ Err: AppleScript Fail"