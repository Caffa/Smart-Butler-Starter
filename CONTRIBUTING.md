# Contributing to Smart Butler

Thank you for your interest in contributing to Smart Butler!

## Development Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/smart-butler.git
cd smart-butler

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest

# Run type checking
mypy src/

# Format code
black src/ tests/
```

## Checkpoint Tagging Strategy

We use Git tags to mark stable states for easy rollback. This is especially important during development when breaking changes are introduced.

### Tag Format

```
phase-XX-plan-YY    # Individual plan completion
phase-XX-complete   # Full phase completion
milestone-NAME      # Major milestone
rollback-YYYYMMDD   # Safe rollback point
```

### Creating Tags

**Manual tagging (recommended for development):**

```bash
# Tag a completed plan
bash scripts/tag-checkpoint.sh phase-01-plan-01

# Tag with custom message
bash scripts/tag-checkpoint.sh phase-01-complete "Phase 1 MVP ready"

# Tag a milestone
bash scripts/tag-checkpoint.sh milestone-alpha "Alpha release"
```

**GitHub Actions (automatic):**

The CI workflow automatically creates tags when plan completion commits are pushed:
- Commits starting with `docs(XX-YY): complete` trigger automatic tagging
- Commits mentioning "Phase X complete" create phase-complete tags

### Rolling Back

```bash
# List all checkpoints
git tag -l "phase-*"

# Rollback to a specific plan
git checkout phase-01-plan-01

# Rollback to phase completion
git checkout phase-01-complete

# Return to main
git checkout main
```

### Tagging Conventions

1. **Always use annotated tags** (`-a`) - they store metadata like date and committer
2. **Tag after verification** - ensure the code works before tagging
3. **Write descriptive messages** - explain what state the tag represents
4. **Push tags explicitly** - don't rely on `git push --tags` in CI

### Phase Completion Checklist

Before creating a phase-complete tag:

- [ ] All tests passing
- [ ] Code formatted (black)
- [ ] Type checking passes (mypy)
- [ ] Documentation updated
- [ ] SUMMARY.md created for the phase
- [ ] `butler doctor` shows all green

## Code Style

- **Python**: Black formatter, 100 character line length
- **Type hints**: Required for all public functions
- **Tests**: Required for new functionality
- **Commits**: Use conventional commit format

## Commit Format

```
type(scope): description

[optional body]

[optional footer]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `test`: Test-only changes
- `refactor`: Code restructuring
- `docs`: Documentation only
- `chore`: Build/tooling changes

Example:
```
feat(01-02): add event bus with blinker

- Implement EventBus class with lifecycle events
- Add test suite for event publishing
- Document usage patterns in README
```

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=butler --cov-report=html

# Run specific test file
pytest tests/cli/test_doctor.py -v

# Run with debugging
pytest tests/ -v --pdb
```

## Pull Request Process

1. Ensure tests pass locally
2. Update documentation if needed
3. Create checkpoint tag if it's a plan completion
4. Request review from maintainers
5. Address feedback promptly

## Questions?

Open an issue or join the discussion in GitHub Discussions.
