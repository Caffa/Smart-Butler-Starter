# Smart Butler 2.0

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![macOS](https://img.shields.io/badge/platform-macos-lightgrey.svg)](https://www.apple.com/macos/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> Voice-first AI assistant that processes voice memos and routes notes to Obsidian

**Core Value:** Butler is invisible when idle and useful when needed — never the reason your computer is slow.

## Quick Start

### One-Line Installation

```bash
curl -sSL https://github.com/Caffa/Smart-Butler-Starter/blob/6d4a7ceb5173eef68a603ecd52dab7c4f8235b56/scripts/install.sh | bash
```

### Verify Installation

```bash
butler doctor
```

### Manual Installation

```bash
# Clone the repository
git clone git@github.com:Caffa/Smart-Butler-Starter.git
cd smart-butler

# Install with pip
pip install -e .

# Or install with development dependencies
pip install -e ".[dev]"

# Verify installation
butler --help
```

## Usage

```bash
# Check system health and dependencies
butler doctor

# Fix missing dependencies automatically
butler doctor --fix

# Process voice input (typically called by launchd)
butler process-voice

# Show version
butler version

# Open configuration (opens in default editor)
butler config
```

## Requirements

- **macOS 14.0+** (Apple Silicon optimized)
- **Python 3.11+**
- **Ollama** (local LLM inference)
- **~2GB free disk space** (for AI models)

## Architecture

Smart Butler uses a modular, event-driven architecture:

- **Event Bus**: Blinker-based lifecycle events for loose coupling
- **Gateway Pattern**: Input adapters (voice, Telegram, email)
- **Pipeline Pattern**: Transcription → Classification → Routing
- **Memory Tiers**: Session → Working → Learning → Vector (ChromaDB)

## Development

```bash
# Run tests
pytest

# Format code
black src/ tests/

# Type checking
mypy src/

# Linting
ruff check src/ tests/
```

## Rollback Checkpoints

Git tags mark stable states for easy rollback:

```bash
# Rollback to Phase 1 completion
git checkout phase-01-complete

# List all checkpoints
git tag -l "phase-*"
```

## License

MIT License - see [LICENSE](LICENSE) file.

## Acknowledgments

- [Ollama](https://ollama.com/) for local LLM inference
- [parakeet-mlx](https://github.com/huggingface/parakeet-mlx) for Apple Silicon transcription
- [ChromaDB](https://www.trychroma.com/) for vector storage

