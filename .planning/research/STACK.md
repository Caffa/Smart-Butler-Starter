# Stack Research

**Domain:** Local-first personal AI assistant with voice input and Obsidian integration
**Researched:** 2026-02-18
**Confidence:** HIGH

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.11+ | Primary language | Project constraint; 3.11+ offers performance improvements (10-25% faster than 3.10), exception groups, and TOML support. 3.12 also viable. |
| Ollama | 0.6.1 | Local LLM runtime | Official Python SDK with synchronous and streaming support. Handles model management, embeddings, and chat completion. Required for llama3.1:8b and nomic-embed-text. |
| parakeet-mlx | latest | Voice transcription | Optimized for Apple Silicon via MLX framework. Faster than whisper-mlx for real-time transcription on M-series chips. NVIDIA's Parakeet models ported to Apple's MLX. |
| SQLite | 3.45+ | Primary database | Local-first by design. Single-file, zero-config, ACID compliant. Use as application file format per sqlite.org recommendations. No external dependencies. |
| ChromaDB | 1.5.0 | Vector memory | Embedded vector database with native Python support. No server required. Automatic embedding with Ollama integration. Persistent storage to disk. |

### Application Framework

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Textual | 8.0.0 | TUI framework | Production-stable, async-native, CSS-based styling. Active development (weekly releases). Supports browser export via `textual serve`. Widget library includes inputs, data tables, trees. |
| rumps | 0.4.0 | macOS menu bar | Only mature Python option for macOS status bar apps. Wraps PyObjC with clean API. 3.3k stars, proven in production. Lightweight—no heavy dependencies. |
| blinker | 1.9.0 | Event bus | Pallets ecosystem (same as Flask). Decoupled publish/subscribe signaling. Thread-safe. Zero dependencies. Industry standard for Python event systems. |
| huey | 2.6.0 | Task queue | Lightweight alternative to Celery. SQLite backend built-in (no Redis required). Supports scheduling, retries, periodic tasks. Single-process ideal for local apps. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| watchdog | 6.0.0 | Vault watching | Cross-platform file system monitoring. Uses native OS APIs (FSEvents on macOS). Detects file changes for Obsidian vault sync. |
| python-telegram-bot | 22.6 | Telegram integration | Official async library for Telegram Bot API 9.3. Supports webhooks and polling. Mature, well-documented. |
| obsidianmd-parser | 0.4.0 | Obsidian markdown | Parses wikilinks, tags, frontmatter, Dataview queries. Python 3.12+ only. New but purpose-built for Obsidian. |
| python-frontmatter | 1.1.0 | YAML frontmatter | Parse/edit YAML metadata in markdown files. Works with Obsidian note format. Lightweight, well-tested. |
| PyYAML | 6.0.2 | YAML processing | Required by frontmatter and config parsing. Standard library for YAML in Python. |

### AI/ML Stack

| Component | Model/Version | Purpose | Why |
|-----------|---------------|---------|-----|
| LLM | llama3.1:8b | Primary reasoning | Project constraint. Good balance of quality and speed on Apple Silicon. 8B parameters fit in memory. |
| Embeddings | nomic-embed-text | Vector embeddings | 8192 token context. Surpasses OpenAI ada-002 and text-embedding-3-small. 137M parameters. Apache 2.0 licensed. Runs via Ollama. |
| Transcription | parakeet-mlx | Voice-to-text | Real-time capable on Apple Silicon. MLX-native, no GPU required. Outperforms whisper-mlx for speed on M-series. |

## Installation

```bash
# Core dependencies
pip install ollama==0.6.1
pip install chromadb==1.5.0
pip install textual==8.0.0

# Application framework
pip install rumps==0.4.0
pip install blinker==1.9.0
pip install huey==2.6.0

# Supporting libraries
pip install watchdog==6.0.0
pip install python-telegram-bot==22.6
pip install obsidianmd-parser==0.4.0
pip install python-frontmatter==1.1.0

# Install Ollama and pull models
# brew install ollama
ollama pull llama3.1:8b
ollama pull nomic-embed-text

# Install parakeet-mlx for transcription
pip install parakeet-mlx
```

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Voice STT | parakeet-mlx | whisper-mlx | Slower on Apple Silicon. OpenAI has deprecated Whisper development. Parakeet purpose-built for M-series. |
| Voice STT | parakeet-mlx | Apple Speech framework | Less control, no offline guarantee, macOS version-dependent. |
| Task Queue | huey + SQLite | Celery + Redis | Overkill for single-user local app. Redis adds external dependency. Huey's SQLite backend is perfect for local-first. |
| Task Queue | huey + SQLite | Django-Q2 | Requires Django. Huey is framework-agnostic. |
| Vector DB | ChromaDB | Pinecone | Cloud-only, not local-first. Defeats privacy requirement. |
| Vector DB | ChromaDB | qdrant | Requires server process. ChromaDB embedded mode is simpler. |
| TUI | Textual | Rich | Rich is for output only. Textual provides full app framework with events, widgets, and layout. |
| Event Bus | blinker | pyee | Less mature, smaller community. Blinker is Pallets ecosystem standard. |
| Menu Bar | rumps | Swift/SwiftUI | Requires learning Swift, Xcode, separate build process. rumps keeps everything in Python. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Celery | Heavyweight, requires Redis/RabbitMQ broker. Designed for distributed systems, not local apps. | huey with SQLite backend |
| Redis | External dependency for a single-user local app. Adds complexity without benefit. | SQLite for all persistence |
| OpenAI API | Cloud-dependent, violates local-first principle. Per-token costs. | Ollama with local models |
| LangChain | Heavy abstraction layer. Adds complexity for simple use case. Direct Ollama SDK is cleaner. | ollama Python SDK directly |
| whisper (OpenAI) | OpenAI has moved on from Whisper. parakeet-mlx is faster on Apple Silicon. | parakeet-mlx |
| Electron | Massive memory footprint. Inappropriate for "invisible when idle" requirement. | Textual TUI + rumps menu bar |
| FastAPI | No web server needed for local-first desktop app. Adds unnecessary HTTP layer. | Direct Python with blinker events |

## Stack Patterns by Variant

**If targeting multi-user/teams:**
- Add SQLite Sync extension for CRDT-based sync
- Consider SQLite Cloud or Turso for hosted SQLite
- Would require significant architecture changes

**If voice needs real-time streaming:**
- Use parakeet-mlx with streaming mode
- Implement audio buffer in separate thread
- VAD (Voice Activity Detection) with webrtcvad for silence detection

**If memory exceeds local storage:**
- ChromaDB supports external storage backends
- But this violates local-first principle—consider pruning strategies instead

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| Python 3.11+ | All recommended packages | 3.12 required for obsidianmd-parser |
| textual 8.0 | Python 3.9-3.14 | Async-compatible with all other libs |
| chromadb 1.5 | Python 3.9+ | Embedding functions work with Ollama |
| huey 2.6 | Python 2 and 3 | SQLite backend stable across versions |
| parakeet-mlx | Apple Silicon only | Requires M1/M2/M3/M4, won't work on Intel Macs |

## Configuration Patterns

### Ollama Client Setup
```python
import ollama

# Default client connects to localhost:11434
# No configuration needed if Ollama running locally

response = ollama.chat(
    model='llama3.1:8b',
    messages=[{'role': 'user', 'content': '...'}]
)

# Embeddings
embeddings = ollama.embed(
    model='nomic-embed-text',
    input='text to embed'
)
```

### ChromaDB with Ollama Embeddings
```python
import chromadb
from chromadb.utils import embedding_functions

ollama_ef = embedding_functions.OllamaEmbeddingFunction(
    url="http://localhost:11434",
    model_name="nomic-embed-text"
)

client = chromadb.PersistentClient(path="./chroma_db")
collection = client.create_collection(
    name="memories",
    embedding_function=ollama_ef
)
```

### Huey with SQLite
```python
from huey import SqliteHuey

huey = SqliteHuey('butler', filename='./butler_tasks.db')

@huey.task()
def process_voice_memo(audio_path: str):
    # Transcription and processing
    pass

@huey.periodic_task(crontab(minute='0', hour='*/4'))
def cleanup_old_memories():
    # Maintenance task
    pass
```

### Blinker Event Bus
```python
from blinker import signal

# Define signals
voice_captured = signal('voice-captured')
note_created = signal('note-created')
memory_stored = signal('memory-stored')

# Subscribe
@voice_captured.connect
def on_voice_captured(sender, **kwargs):
    transcript = kwargs['transcript']
    # Process transcript

# Emit
voice_captured.send(this, transcript=text)
```

## Sources

- PyPI — Package versions verified: textual 8.0.0, chromadb 1.5.0, watchdog 6.0.0, huey 2.6.0, blinker 1.9.0, ollama 0.6.1, python-telegram-bot 22.6
- ollama.com/library/nomic-embed-text — Embedding model specs (8192 context, 137M params)
- github.com/senstella/parakeet-mlx — Apple Silicon voice transcription
- sqlite.org/appfileformat.html — SQLite as application file format
- realpython.com/ollama-python (Jan 2026) — Ollama Python integration patterns
- medium.com/@g.suryawanshi/lightweight-django-task-queues-2025 — Huey comparison
- localaimaster.com/blog/rag-local-setup-guide (Feb 2026) — Local RAG stack with ChromaDB

---
*Stack research for: Local-first personal AI assistant*
*Researched: 2026-02-18*
