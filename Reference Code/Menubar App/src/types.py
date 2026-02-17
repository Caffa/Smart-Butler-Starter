"""Shared constants, paths, and configuration for the note router."""

import os

# ==============================================================================
# CONFIGURATION
# ==============================================================================

# PATHS
VAULT_ROOT = os.path.abspath("/Users/caffae/Notes")
LOG_FILE_PATH = os.path.join(os.path.expanduser("~"), "Desktop", "llm_router_audit.log")
VERBOSE_LOG_PATH = "/Users/caffae/Local Projects/AI Memories/Debug/System Logs/main.log"
NOTE_SORTER_MEMORY_ROOT = os.path.abspath(
    "/Users/caffae/Local Projects/AI Memories/Note Sorter Memories"
)
NOTE_SORTER_MEMORY_INBOX_FOLDER = "00 Inbox"
PREFERENCES_MEMORY_ROOT = os.path.abspath(
    "/Users/caffae/Local Projects/AI Memories/Information on Moi"
)
TEMPORAL_MEMORIES_ROOT = os.path.abspath(
    "/Users/caffae/Local Projects/AI Memories/Temporal Memories"
)
TEMPORAL_DAILY_FOLDER = "daily"
TEMPORAL_STAGING_FOLDER = "staging"  # Buffered events under daily/staging/
TEMPORAL_WEEKLY_FOLDER = "weekly"
TEMPORAL_MONTHLY_FOLDER = "monthly"
TEMPORAL_DEDUCTIONS_FOLDER = "Deductions"
TEMPORAL_PATTERNS_FOLDER = "Patterns"
AI_PERSONALITY_FOLDER = "AI-Personality"
AI_PERSONALITY_DIR = os.path.join(TEMPORAL_MEMORIES_ROOT, AI_PERSONALITY_FOLDER)
IDENTITY_PATH = os.path.join(AI_PERSONALITY_DIR, "IDENTITY.md")
SOUL_PATH = os.path.join(AI_PERSONALITY_DIR, "SOUL.md")
MESSAGES_TO_AI_FILE = os.path.join(TEMPORAL_MEMORIES_ROOT, "Messages-to-AI.md")
PRIORITY_READING_LIST_PATH = os.path.join(
    TEMPORAL_MEMORIES_ROOT, "priority-reading-list.md"
)
DAILY_DIGEST_DIR = os.path.abspath(
    "/Users/caffae/Local Projects/AI Memories/Presenting to User/Daily Digest"
)

# Tracking indexes for diary/zettel review (plan: batch processing at heartbeat)
INDEXES_ROOT = "/Users/caffae/Local Projects/AI Memories/Temporal Memories/indexes"
DIARY_REVIEW_INDEX_PATH = os.path.join(INDEXES_ROOT, "diary-review-index.json")

# New workflow: diary entries processed at heartbeat, not immediately
ENABLE_IMMEDIATE_DIARY_PROCESSING = False

# SUB-DIRECTORIES
DAILY_NOTE_DIR = os.path.join(VAULT_ROOT, "Journal/Journals")
WEEKLY_NOTE_DIR = os.path.join(VAULT_ROOT, "Journal/Journals/Weekly")
IDEAS_DIR = os.path.join(
    VAULT_ROOT, "ZettelPublish (Content Creator V2 April 2025)/08 Ideas"
)
NOVEL_WRITING_DIR = os.path.join(VAULT_ROOT, "Novel-Writing")
NOVEL_DIR = os.path.join(VAULT_ROOT, "Novel-Writing/Novel")
FICTION_PATH = os.path.join(
    VAULT_ROOT, "Novel-Writing/Novel/Ideas/Misc Random Ideas.md"
)
EXPERIMENT_DIR = os.path.join(
    VAULT_ROOT, "ZettelPublish (Content Creator V2 April 2025)/08 Ideas/80 Experiment"
)
EXPERIMENT_INDEX = os.path.join(
    VAULT_ROOT,
    "ZettelPublish (Content Creator V2 April 2025)/07 Projects/Tiny Experiments 2026.md",
)
DEVLOG_DIR = os.path.join(
    VAULT_ROOT, "ZettelPublish (Content Creator V2 April 2025)/07 Projects/Devlog"
)
# Time-of-day division for devlog: entries after this get a time prefix (e.g. **17:45**)
DEVLOG_EVENING_HOUR = 17
DEVLOG_EVENING_MINUTE = 30

# Zettel vault root (ZettelPublish) for butler summary scope
ZETTEL_VAULT_ROOT = os.path.join(
    VAULT_ROOT, "ZettelPublish (Content Creator V2 April 2025)"
)
# ZETTELKASTEN BD/KORE: Only these folders are scanned for #bd/#kore tags at heartbeat
ZETTELKASTEN_BD_KORE_SCAN_FOLDERS = [
    os.path.join(VAULT_ROOT, "ZettelPublish (Content Creator V2 April 2025)/01 Inbox"),
    os.path.join(
        VAULT_ROOT, "ZettelPublish (Content Creator V2 April 2025)/03 Sleeping Notes"
    ),
]

# ZETTELKASTEN: Folders to scan for modified notes during heartbeat
ZETTELKASTEN_FOLDERS = [
    os.path.join(VAULT_ROOT, "ZettelPublish (Content Creator V2 April 2025)/01 Inbox"),
    os.path.join(
        VAULT_ROOT, "ZettelPublish (Content Creator V2 April 2025)/02 Reference Notes"
    ),
    os.path.join(
        VAULT_ROOT, "ZettelPublish (Content Creator V2 April 2025)/03 Sleeping Notes"
    ),
    os.path.join(
        VAULT_ROOT,
        "ZettelPublish (Content Creator V2 April 2025)/04 Main (Point) Notes",
    ),
    os.path.join(
        VAULT_ROOT, "ZettelPublish (Content Creator V2 April 2025)/05 Source Material"
    ),
    os.path.join(
        VAULT_ROOT, "ZettelPublish (Content Creator V2 April 2025)/06 Hub Notes"
    ),
    os.path.join(
        VAULT_ROOT, "ZettelPublish (Content Creator V2 April 2025)/07 Projects"
    ),
    os.path.join(VAULT_ROOT, "ZettelPublish (Content Creator V2 April 2025)/08 Ideas"),
    os.path.join(VAULT_ROOT, "ZettelPublish (Content Creator V2 April 2025)/10 Log"),
]

# RULES
RULES_FILE = os.path.join(
    VAULT_ROOT,
    "ZettelPublish (Content Creator V2 April 2025)/00 Command/Where things should go.md",
)
RULES_CACHE = RULES_FILE + ".cached"

# EXECUTABLES - _SCRIPT_DIR is parent of src/ (Note Sorting Scripts folder)
_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFERENCE_SAVE_BACKGROUND_SCRIPT = os.path.join(
    _SCRIPT_DIR, "preference-attribute-save-background.py"
)
TEMPORAL_SAVE_BACKGROUND_SCRIPT = os.path.join(
    _SCRIPT_DIR, "temporal-memories-save-background.py"
)
MEMORY_EVIDENCE_READER_SCRIPT = os.path.join(_SCRIPT_DIR, "memory-evidence-reader.py")
DEDUCTION_HEARTBEAT_SCRIPT = os.path.join(_SCRIPT_DIR, "deduction-heartbeat.py")
PYTHON_EXEC = "/opt/homebrew/opt/python@3.10/bin/python3.10"
ZETTEL_SCRIPT = os.path.join(_SCRIPT_DIR, "create-zettel.py")
ZETTELKASTEN_SCRIPT_PATH = "/Users/caffae/Documents/Useful Archive/Useful Scripts/KeyboardMaestro SaveToZettel/create_zettel_note.py"
DIARY_MEMORY_SAVE_BACKGROUND_SCRIPT = os.path.join(
    _SCRIPT_DIR, "diary-memory-save-background.py"
)
INFORMATION_MOI_SYNTHESIS_SCRIPT = os.path.join(
    _SCRIPT_DIR, "information-moi-synthesis.py"
)
MEMORY_PROCESSING_LOCK_FILE = os.path.join(
    os.path.expanduser("~"), ".diary_memory_processing.lock"
)
QUEUE_DB_PATH = os.path.join(_SCRIPT_DIR, "queue.db")
CACHE_DB_PATH = os.path.join(_SCRIPT_DIR, "cache.db")
HUEY_REDIS_URL = os.environ.get("HUEY_REDIS_URL", "redis://localhost:6379/0")
OLLAMA_LOCK_FILE = os.path.abspath(
    "/Users/caffae/Local Projects/AI Memories/.locks/ollama.lock"
)

# LLM CONFIG
OLLAMA_URL = "http://localhost:11434/api/chat"
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
OLLAMA_READ_TIMEOUT = 900  # seconds (15 min); increase if large models often time out
OLLAMA_LOCK_TIMEOUT = int(
    os.environ.get("OLLAMA_LOCK_TIMEOUT", "7200")
)  # lock acquire wait (2h); must exceed longest call (~2300s observed)
OLLAMA_LOCK_RETRY_INTERVAL = float(
    os.environ.get("OLLAMA_LOCK_RETRY_INTERVAL", "1.0")
)  # seconds between lock retries; default 1.0
OLLAMA_LOCK_MIN_FREE_MEMORY_MB = int(
    os.environ.get("OLLAMA_LOCK_MIN_FREE_MEMORY_MB", "2048")
)  # min free MB before refusing to proceed without lock; 0 = disable check

# Diary correction priority: skip lock if this much RAM free; abort after wait if below threshold
DIARY_CORRECTION_SKIP_LOCK_MIN_FREE_MB = int(
    os.environ.get("DIARY_CORRECTION_SKIP_LOCK_MIN_FREE_MB", "4096")
)  # if >= this much free, skip lock (highest priority)
DIARY_CORRECTION_ABORT_WAIT_SECONDS = int(
    os.environ.get("DIARY_CORRECTION_ABORT_WAIT_SECONDS", "600")
)  # 10 min max wait for lock
DIARY_CORRECTION_ABORT_LOW_MEM_MB = int(
    os.environ.get("DIARY_CORRECTION_ABORT_LOW_MEM_MB", "2048")
)  # if waited 10min and free < this, return uncorrected
ATTEMPTED_PROMPTS_DIR = os.path.abspath(
    "/Users/caffae/Local Projects/AI Memories/Debug/Attempted Prompts"
)

MODEL_FAST = "gemma3:4b"  # Only for file names
MODEL_STAGING = "llama3.1:8b"  # Batch staging: summarize long content (fast)
# Batch staging: max chars per staging line third field; above this threshold use LLM to summarize
STAGING_MAX_CHARS = 600
STAGING_SUMMARIZE_ABOVE_CHARS = 1000
MODEL_SMART_MakeInstructions = (
    "deepseek-r1:32b"  # for making rules (logic / instruction generation)
)
MODEL_SMART_MakeRouterDecisions = "gemma3:27b"  # chatty, but good at making decisions
MODEL_MED = "gemma3:12b"  # Also very good at making decisions (actually more succinct)

# Apple Notes for todo routing (handle_daily)
APPLE_NOTE_SOMEDAY_TASKS = "Someday Tasks"
APPLE_NOTE_PRINCIPLES = "Principles & Habits"
TODO_ROUTING_HOUR_THRESHOLD = 2  # 2AM threshold for today vs tomorrow classification

MODEL_ALT = "qwen/qwen3-4b-2507"
MODEL_LIFE_COACH_CHAT = "gemma3:27b"
MODEL_LIFE_COACH_DEDUCTION = "deepseek-r1:32b"
MODEL_CODE_INSPECTOR = (
    "qwen3-coder:30b"  # code inspection for supervisor-dev evolution log
)


# VAULT PATH PROTECTION (butler and indexing must not modify template or excalidraw files)
def is_template_path(path):
    """True if the basename stem ends with 'template' (case-insensitive), e.g. 'Inbox Template.md', or if any path component is 'Template' or 'Templates'."""
    if not path or not isinstance(path, str):
        return False
    norm = os.path.normpath(path)
    base = os.path.basename(norm)
    if base and "template" in base.lower():
        return True
    for part in norm.split(os.sep):
        if part and part.lower() in ("template", "templates"):
            return True
    stem, _ = os.path.splitext(base)
    return stem.lower().endswith("template")


def is_excalidraw_path(path):
    """True if the path is an Excalidraw or canvas file (by basename or extension)."""
    if not path or not isinstance(path, str):
        return False
    basename = os.path.basename(path)
    lower = basename.lower()
    if "excalidraw" in lower:
        return True
    return (
        lower.endswith(".excalidraw")
        or lower.endswith(".excalidraw.md")
        or lower.endswith(".canvas")
    )


def is_vault_path_protected(path):
    """True if the path should not be modified by butler/indexing (template or excalidraw)."""
    return is_template_path(path) or is_excalidraw_path(path)


# SAFETY CONFIGURATION
SAFETY_ENABLED = True
SAFETY_GIT_ROOT = os.path.abspath("/Users/caffae/Local Projects/AI Memories")
SAFETY_AUTO_ROLLBACK = True
SAFETY_CHECKPOINT_ON_HEARTBEAT = True
SAFETY_SEMANTIC_DRIFT_THRESHOLD = 0.7
SAFETY_MIN_CONTENT_LENGTH = 10
SAFETY_MAX_CONTENT_LENGTH = 50000
MODEL_FALLBACK_SAFETY = "llama3.1:8b"
MODELS_ELIGIBLE_FOR_FALLBACK = ("gemma3:27b", "gemma3:12b", "llama3.1:8b")

# Context expansion (recursive file reading for deduction / patterns / temporal memory)
CONTEXT_EXPANSION_MAX_DEPTH = 5
CONTEXT_EXPANSION_MAX_FILES_PER_SESSION = 50
CONTEXT_EXPANSION_MAX_BYTES_PER_SESSION = 500 * 1024  # 500KB
CONTEXT_EXPANSION_CONFIDENCE_THRESHOLD = 0.6  # Expand if below this
CONTEXT_EXPANSION_MIN_EVIDENCE_THRESHOLD = 3  # Expand if fewer sources

ROUTER_TOOLS_DESCRIPTION = """
1. use_daily_journal
   - Functionality: Appends text to today's date-stamped file.
   - Best For: THE DEFAULT. Use for "What I did today", "Dear Diary", casual logs, todo lists, fleeting thoughts, music logs.
   - RULE: If it describes your day or is a random thought, IT GOES HERE.

2. use_zettel_script
   - Functionality: Runs a Python script to structure deep research.
   - Best For: Atomic notes, intellectual insights, definitions, research summaries, permanent knowledge.

3. use_idea_generator
   - Functionality: Creates a new timestamped Markdown file in the Ideas folder.
   - Best For: Business concepts, Content Creation ideas, YouTube topics, entrepreneurial brainstorms, Code ideas, App ideas, Product ideas.
   - RULE: If it is my idea about a business, content, video, app, coding, product, or any other income generating idea, IT GOES HERE.

4. use_fiction_append
   - Functionality: Appends to the general Fiction Ideas file.
   - Best For: Novel ideas, character snippets, dialogue, story scenes.

5. use_experiment_create
   - Functionality: Creates a NEW Markdown file for a "Tiny Experiment" and links it to the Index.
   - Best For: STARTING a brand new scientific/lifestyle experiment.

6. use_experiment_log
   - Functionality: Appends an observation to an EXISTING experiment file.
   - Best For: Updates on ongoing experiments (e.g., "Day 3 of Socializing More"). *Requires file path from Context.*
   - When the note applies to MULTIPLE existing experiments: pick one as primary (use "path") and list the other file paths in "extra_paths"; the system will append content to the primary and add a block reference to the others.

7. use_apple_notes_general
   - Functionality: Appends text to Apple Notes, but the AI chooses the Apple Note name + tag, using the \"Note Sorter Memories\" directory as an evolving memory.
   - Best For: Recurring logs/categories that you want to be quickly searchable in Apple Notes (e.g. coffee logs, cafe tastings, gym logs).
   - RULE: Only use this if the information is useful for a recurring category that the user may want to search for later. These entries should still also be sent to 'use_daily_journal' as well.

8. use_dev_log
   - Functionality: Appends to an existing project devlog file in the Devlog folder. *Requires file path from Context (Recent Devlog project notes).*
   - Best For: Coding progress, feature/bugfix logs, project-specific updates. Often used together with use_daily_journal.
   - If the content is about coding but no Devlog project in context clearly matches, return only use_daily_journal (or use the most recently modified Devlog path as best guess).

9. use_dev_log_create
   - Functionality: Creates a new project note in the Devlog folder when the user mentions a project that does *not* appear in CONTEXT (Recent Devlog project notes). Do not use if a matching devlog PATH already exists in context.
   - Best For: First mention of a project (coding or not, e.g. "mannequin project", "habit app"), or starting a new project log. Prefer a single use_dev_log_create with the initial content in "content" (create and first log in one op).

10. use_zettel_append
   - Functionality: Appends content to an *existing* zettel file. Path must be a full file path under the Zettel vault. Used when the user says they are "adding onto" a previous thought and the system resolved a single recent zettel.
   - Best For: Only use when reference resolution has already chosen to append to one zettel (pre-step). Do not use for new ideas; use use_zettel_script for new zettels.
"""


def get_router_tools_description(forbid_new_devlog_creation=False):
    """Return ROUTER_TOOLS_DESCRIPTION, optionally with use_dev_log_create block removed."""
    if not forbid_new_devlog_creation:
        return ROUTER_TOOLS_DESCRIPTION
    import re
    # Remove "9. use_dev_log_create" and its two bullet lines, then renumber 10 -> 9
    block = re.compile(
        r"\n9\. use_dev_log_create\n"
        r"(   - Functionality:.*?\n)"
        r"(   - Best For:.*?\n)"
        r"\n",
        re.DOTALL,
    )
    out = block.sub("\n", ROUTER_TOOLS_DESCRIPTION)
    out = out.replace("10. use_zettel_append", "9. use_zettel_append")
    return out


# CONVERSATIONS_FOLDER - used by conversation-runner
CONVERSATIONS_FOLDER = os.path.join(TEMPORAL_MEMORIES_ROOT, "Conversations")

# Vault display names: long vault name -> short name for user-facing text (e.g. daily Project Log).
# When parsing, the short name is resolved back to the long vault name for project key/path.
VAULT_DISPLAY_NAMES = {
    "ZettelPublish (Content Creator V2 April 2025)": "Zettelkasten",
}
VAULT_DISPLAY_NAMES_REVERSE = {v: k for k, v in VAULT_DISPLAY_NAMES.items()}

# Settings: Settings.yaml only (comments allowed)
SETTINGS_DIR = _SCRIPT_DIR
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "Settings.yaml")
_SETTINGS_CACHE = None


def _load_settings_raw():
    """Load settings from Settings.yaml. Returns dict of key -> value or {}."""
    try:
        if os.path.isfile(SETTINGS_PATH):
            import yaml

            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def get_setting(key, default=None):
    """Load settings from Settings.yaml and return value for key. Returns default if missing or on error."""
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE is None:
        _SETTINGS_CACHE = {}
        data = _load_settings_raw()
        for k, v in data.items():
            if k.endswith("_description"):
                continue
            if isinstance(v, (bool, str, int, float)):
                _SETTINGS_CACHE[k] = v
    return _SETTINGS_CACHE.get(key, default)


def get_zettelkasten_tag_lists():
    """Load zettelkasten breakdown/analysis tag lists from Settings.yaml. Returns (breakdown_tags, analysis_tags) as lists of strings. Defaults to (['#bd'], ['#kore']) if unset."""
    data = _load_settings_raw()
    breakdown = data.get("zettelkasten-breakdown-tags")
    analysis = data.get("zettelkasten-analysis-tags")
    if isinstance(breakdown, list):
        breakdown = [str(t).strip() for t in breakdown if t and str(t).strip()]
    else:
        breakdown = []
    if isinstance(analysis, list):
        analysis = [str(t).strip() for t in analysis if t and str(t).strip()]
    else:
        analysis = []
    if not breakdown:
        breakdown = ["#bd"]
    if not analysis:
        analysis = ["#kore"]
    return (breakdown, analysis)
