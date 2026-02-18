---
phase: 01-core-infrastructure
plan: "04"
subsystem: cli

tags:
  - click
  - pytest
  - setuptools
  - pip
  - git-tags
  - ollama

requires:
  - phase: 01-core-infrastructure
    provides: None (first plan in phase)

provides:
  - One-command installation via install.sh
  - pip installable Python package with pyproject.toml
  - CLI entry point butler with doctor command
  - Dependency checking and auto-fix capability
  - Git checkpoint tagging workflow and tooling
  - Package structure with src/butler/
  - Comprehensive test suite for CLI

affects:
  - all future plans requiring CLI
  - deployment and distribution
  - user onboarding

tech-stack:
  added:
    - click (CLI framework)
    - setuptools (packaging)
    - pytest (testing)
  patterns:
    - Click group pattern for subcommands
    - Doctor pattern for health checks
    - Git annotated tags for rollback
    - Pip editable install for development

key-files:
  created:
    - pyproject.toml (package metadata and deps)
    - requirements.txt (pip dependencies)
    - src/butler/__init__.py (package root)
    - src/butler/cli/__init__.py (CLI module)
    - src/butler/cli/main.py (CLI entry point)
    - src/butler/cli/doctor.py (health checker)
    - scripts/install.sh (installation script)
    - scripts/tag-checkpoint.sh (tagging helper)
    - tests/cli/test_doctor.py (doctor tests)
    - tests/cli/test_main.py (CLI tests)
    - .github/workflows/tag-checkpoints.yml (CI workflow)
    - CONTRIBUTING.md (contribution guidelines)
    - README.md (quick start documentation)
  modified:
    - .planning/ROADMAP.md (plan progress tracking)

key-decisions:
  - "Use Click for CLI framework - better than argparse for subcommands"
  - "Python 3.10+ requirement - balances features with availability"
  - "pip install -e . for development - editable install workflow"
  - "Git annotated tags for checkpoints - includes metadata and messages"
  - "Doctor command with emoji indicators - intuitive status display"
  - "install.sh with personality - matches Butler character"

patterns-established:
  - "CLI command pattern: @click.group() for main CLI, @cli.command() for subcommands"
  - "Health check pattern: Status enum with emoji values, CheckResult dataclass"
  - "Test pattern: Use Click's CliRunner for CLI testing, patch for mocking"
  - "Commit pattern: feat(01-04): Task N - description"

requirements-completed:
  - INSTALL-01
  - INSTALL-02
  - INSTALL-03

duration: "90min"
completed: "2026-02-18"
---

# Phase 01 Plan 04: Installation and CLI Infrastructure Summary

**One-command installation with curl-to-bash, pip-installable package, butler doctor health checks, and Git checkpoint tagging for rollback safety**

## Performance

- **Duration:** 90 min
- **Started:** 2026-02-18T08:54:58Z
- **Completed:** 2026-02-18T10:25:00Z
- **Tasks:** 5
- **Files created:** 12

## Accomplishments

- Complete Python package structure with pyproject.toml and src/butler/ layout
- One-command installation script (curl-to-bash) with friendly Butler personality
- Comprehensive health checker (`butler doctor`) with 11 dependency checks
- Auto-fix capability to download missing Ollama models
- Git checkpoint tagging system with manual and automated workflows
- Full CLI test suite with 31 passing tests
- CONTRIBUTING.md documenting development workflow

## Task Commits

Each task was committed atomically:

1. **Task 1: Project Structure and Dependencies** - `ca42bea` (feat)
2. **Task 2: install.sh Script** - `1898e36` (feat)
3. **Task 3: butler doctor Command** - `2055062` (feat)
4. **Task 4: Git Rollback Checkpoints** - `73da79a` (feat)
5. **Task 5: CLI Main Entry Point** - `b797ca4` (feat)
6. **ROADMAP update** - `e8861dd` (chore)
7. **Plan completion metadata** - [pending]

## Files Created/Modified

- `pyproject.toml` - Package metadata, dependencies (blinker, huey, pyyaml, psutil, ollama, chromadb, click), entry point
- `requirements.txt` - Pip-installable dependencies
- `src/butler/__init__.py` - Package root with version
- `src/butler/cli/__init__.py` - CLI module
- `src/butler/cli/main.py` - CLI entry point with Click (doctor, process-voice, version, config)
- `src/butler/cli/doctor.py` - Health checker with 11 checks and emoji indicators
- `scripts/install.sh` - Friendly installation script with dry-run mode
- `scripts/tag-checkpoint.sh` - Manual tagging helper script
- `tests/cli/test_doctor.py` - 16 comprehensive doctor tests
- `tests/cli/test_main.py` - 15 CLI integration tests
- `.github/workflows/tag-checkpoints.yml` - Automated tagging on plan completion
- `CONTRIBUTING.md` - Contribution guidelines with tagging strategy
- `README.md` - Quick start documentation

## Decisions Made

- **Click over argparse** - Better subcommand support, built-in help, type checking
- **Python 3.10+ instead of 3.11+** - Environment compatibility while keeping modern features
- **src/ layout** - Cleaner separation of source and tests, avoids import issues
- **Git annotated tags** - Include metadata like date, committer, rollback commands
- **Doctor with emoji indicators** - ✓ OK, ⚠ Warning, ✗ Error for intuitive status
- **install.sh personality** - Friendly, conversational tone matching Butler character

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Adjusted Python version requirement**
- **Found during:** Task 1 (Project Structure)
- **Issue:** Environment has Python 3.10 but plan specified 3.11+
- **Fix:** Changed requires-python to ">=3.10" and updated classifiers
- **Files modified:** pyproject.toml
- **Committed in:** ca42bea (Task 1 commit)

**2. [Rule 1 - Bug] Fixed doctor module import in tests**
- **Found during:** Task 5 (CLI tests)
- **Issue:** Mock path pointed to wrong module location
- **Fix:** Changed `@patch("butler.cli.main.check_dependencies")` to `@patch("butler.cli.doctor.check_dependencies")`
- **Files modified:** tests/cli/test_main.py
- **Committed in:** b797ca4 (Task 5 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both necessary for correctness. No scope creep.

## Issues Encountered

1. **Click CliRunner returns exit code 2 for no-args** - Expected behavior, test adjusted to check output instead
2. **Tag created before final commit** - Recreated tag phase-01-plan-04 pointing to correct commit

## User Setup Required

**Dependencies to install manually:**

1. **Ollama** - Required for local LLM inference
   - Download from: https://ollama.com/download
   - Or run: `brew install ollama`

2. **AI Models** - Download via doctor:
   ```bash
   butler doctor --fix
   ```
   This downloads: llama3.1:8b, nomic-embed-text

**Optional dependencies:**
- parakeet-mlx - For transcription (macOS only)
  ```bash
  pip install parakeet-mlx
  ```

## Next Phase Readiness

- ✅ Package installs via pip
- ✅ CLI entry point functional
- ✅ Health checking operational
- ✅ Git tagging workflow ready
- ✅ 31 passing tests
- ⚠️ Ollama installation required (documented in README)

**Ready for:** Phase 2 (Voice Input Pipeline) development

---
*Phase: 01-core-infrastructure*  
*Completed: 2026-02-18*
