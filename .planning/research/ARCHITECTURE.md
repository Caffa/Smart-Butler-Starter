# Architecture Research

**Domain:** Local-first personal AI assistant with voice input and Obsidian integration
**Researched:** 2026-02-18
**Confidence:** HIGH

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           INTERFACE LAYER                                │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────────────┐    │
│  │ Voice In  │  │ Text In   │  │ Message   │  │ CLI / API         │    │
│  │ (STT)     │  │           │  │ Channels  │  │                   │    │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────────┬─────────┘    │
│        │              │              │                  │               │
├────────┴──────────────┴──────────────┴──────────────────┴───────────────┤
│                        GATEWAY / CONTROL PLANE                           │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    Event Bus (lifecycle)                         │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │ Session     │  │ Pipeline    │  │ Plugin      │  │ Capabilities│    │
│  │ Manager     │  │ Orchestrator│  │ Registry    │  │ Registry    │    │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘    │
│         │                │                │                │            │
├─────────┴────────────────┴────────────────┴────────────────┴────────────┤
│                          INTELLIGENCE LAYER                              │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                      LLM Router (Brain)                          │    │
│  │   Local (Ollama) │ Cloud (Claude/GPT) │ Hybrid                   │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                     │
│  │ Skills      │  │ Memory      │  │ Tool        │                     │
│  │ System      │  │ Manager     │  │ Executor    │                     │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                     │
│         │                │                │                             │
├─────────┴────────────────┴────────────────┴─────────────────────────────┤
│                           STORAGE LAYER                                  │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────┐  ┌──────────────────────────────────────┐     │
│  │ ~/.butler/ (System)  │  │ User Vault (Obsidian/PKM)            │     │
│  │ ├── config/          │  │ ├── Inbox/                           │     │
│  │ ├── cache/           │  │ ├── Notes/                           │     │
│  │ ├── memory/          │  │ ├── Daily/                           │     │
│  │ ├── plugins/         │  │ └── Projects/                        │     │
│  │ └── queue.db         │  │                                      │     │
│  └──────────────────────┘  └──────────────────────────────────────┘     │
│  ┌──────────────────────┐  ┌──────────────────────┐                     │
│  │ Task Queue (Huey)    │  │ Vector Index        │                     │
│  │ SQLite (recovery)    │  │ (Memory search)     │                     │
│  └──────────────────────┘  └──────────────────────┘                     │
└─────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| **Gateway** | Central control plane, owns all session state, coordinates all subsystems | Node.js/Python long-lived process |
| **Event Bus** | Decoupled lifecycle events, hooks system, async coordination | Blinker (Python), EventEmitter patterns |
| **Pipeline Orchestrator** | Ordered data transforms: transcription → cleaning → routing → saving | Chain of responsibility pattern |
| **Session Manager** | Conversation history, context windowing, state transitions | State machine with reducers |
| **Plugin Registry** | Auto-discovery, capability advertisement, dependency resolution | Plugin architecture with manifest files |
| **Capabilities Registry** | Service locator pattern, tool discovery, permission management | Registry with typed interfaces |
| **Memory Manager** | Multi-tier memory: session, working, learning, long-term | Layered storage with vector search |
| **LLM Router** | Model selection, failover, cost optimization, local/cloud routing | Strategy pattern with health checks |
| **Task Queue** | Background job processing, crash recovery, throttling | Huey + SQLite, Redis alternative |
| **Safe Write Protocol** | Race condition prevention with Obsidian, atomic writes | mtime double-check, file locks |

## Recommended Project Structure

```
src/
├── core/                    # Core orchestrator and gateway
│   ├── gateway.py           # Central control plane
│   ├── event_bus.py         # Blinker-based event system
│   └── session.py           # Session state management
├── pipeline/                # Data transformation pipeline
│   ├── base.py              # Pipeline stage interface
│   ├── stages/
│   │   ├── transcription.py # STT processing
│   │   ├── cleaning.py      # Text normalization
│   │   ├── routing.py       # Destination selection
│   │   └── saving.py        # File persistence
│   └── orchestrator.py      # Pipeline execution
├── plugins/                 # Plugin system
│   ├── base.py              # Plugin interface
│   ├── registry.py          # Plugin discovery
│   └── builtin/             # Built-in plugins
├── memory/                  # Memory system
│   ├── tiers/               # Session, working, learning
│   ├── index.py             # Vector indexing
│   └── retrieval.py         # Hybrid search (70/30 vector/BM25)
├── skills/                  # Domain expertise modules
│   ├── base.py              # Skill interface
│   └── builtin/             # Built-in skills
├── storage/                 # Storage abstractions
│   ├── system.py            # ~/.butler/ operations
│   ├── vault.py             # User vault operations
│   └── safe_write.py        # Race condition prevention
├── voice/                   # Voice pipeline
│   ├── stt.py               # Speech-to-text
│   ├── vad.py               # Voice activity detection
│   └── tts.py               # Text-to-speech (optional)
├── queue/                   # Background processing
│   ├── tasks.py             # Huey task definitions
│   └── throttling.py        # CPU/RAM/power awareness
└── utils/                   # Shared utilities
    ├── watch.py             # FSEvents watchdog
    └── hash_cache.py        # Change detection
```

### Structure Rationale

- **core/**: Gateway owns session state; must be independent and stable
- **pipeline/**: Ordered transforms are the core data flow; stages are pluggable
- **plugins/**: Extensibility is first-class; auto-discovery at startup
- **memory/**: Multi-tier memory is critical for personal AI; separate from storage
- **storage/**: Two domains (system vs user) require clear boundaries
- **voice/**: Voice pipeline has unique latency constraints; isolated for optimization

## Architectural Patterns

### Pattern 1: Gateway-Centric Control Plane

**What:** Single long-lived process that owns all session state, coordinates subsystems, and enforces policies.

**When to use:** Any local-first AI system with multiple interfaces (voice, text, messages).

**Trade-offs:** 
- Pros: Single source of truth, unified state, easier debugging
- Cons: Single point of failure, requires graceful degradation

**Example:**
```python
class Gateway:
    def __init__(self):
        self.event_bus = EventBus()
        self.sessions: dict[str, Session] = {}
        self.pipeline = PipelineOrchestrator()
        self.plugins = PluginRegistry()
        
    async def handle_input(self, source: str, content: bytes, metadata: dict):
        session = self.get_or_create_session(metadata["user_id"])
        event = InputEvent(source=source, content=content, metadata=metadata)
        await self.event_bus.emit("input.received", event)
        result = await self.pipeline.process(content, session)
        await self.event_bus.emit("output.ready", result)
        return result
```

### Pattern 2: Pipeline with Ordered Stages

**What:** Chain of responsibility where each stage transforms data and passes to next.

**When to use:** Data transformation flows where order matters and stages are swappable.

**Trade-offs:**
- Pros: Easy to add/remove stages, testable in isolation, clear data flow
- Cons: Overhead for simple operations, error handling complexity

**Example:**
```python
class PipelineStage(ABC):
    @abstractmethod
    async def process(self, data: PipelineData) -> PipelineData: ...

class TranscriptionStage(PipelineStage):
    async def process(self, data: PipelineData) -> PipelineData:
        if data.content_type == "audio":
            data.text = await self.stt.transcribe(data.content)
        return data

class Pipeline:
    def __init__(self, stages: list[PipelineStage]):
        self.stages = stages
    
    async def process(self, data: PipelineData) -> PipelineData:
        for stage in self.stages:
            data = await stage.process(data)
        return data
```

### Pattern 3: Multi-Tier Memory System

**What:** Layered memory with different persistence and retrieval strategies per tier.

**When to use:** Personal AI that needs both short-term context and long-term learning.

**Trade-offs:**
- Pros: Optimized for different access patterns, prevents context bloat
- Cons: Complexity, tier migration logic, consistency between tiers

**Example:**
```python
class MemorySystem:
    def __init__(self):
        self.session = SessionMemory()      # Ephemeral, in-memory
        self.working = WorkingMemory()       # File-based, task-scoped
        self.learning = LearningMemory()     # Curated, long-term
        self.vector_index = VectorIndex()    # Semantic search
    
    async def recall(self, query: str, scope: str = "all"):
        results = []
        if scope in ("session", "all"):
            results.extend(self.session.search(query))
        if scope in ("working", "all"):
            results.extend(self.working.search(query))
        if scope in ("learning", "all"):
            # Hybrid: 70% vector, 30% BM25
            results.extend(await self.vector_index.hybrid_search(query))
        return self.deduplicate(results)
```

### Pattern 4: Safe Write Protocol

**What:** Atomic writes with mtime verification to prevent race conditions with external editors (Obsidian).

**When to use:** File-based storage where external processes may modify files concurrently.

**Trade-offs:**
- Pros: No data loss, works without file locks
- Cons: Read-modify-write overhead, retry complexity

**Example:**
```python
async def safe_write(path: Path, content: str, expected_mtime: float | None = None):
    if expected_mtime is not None:
        current_mtime = path.stat().st_mtime
        if current_mtime != expected_mtime:
            raise ConflictError(f"File modified externally: {path}")
    
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(content)
    temp_path.replace(path)  # Atomic on POSIX
```

### Pattern 5: Event-Driven Hooks

**What:** Lifecycle events trigger registered hooks for extensibility without coupling.

**When to use:** Systems needing plugins to react to system events without modifying core.

**Trade-offs:**
- Pros: Decoupled, plugin-friendly, easy observability
- Cons: Debugging across hooks, execution order ambiguity

**Example:**
```python
from blinker import Signal

class Events:
    session_start = Signal()
    input_received = Signal()
    pre_tool_use = Signal()
    post_tool_use = Signal()
    output_ready = Signal()
    session_end = Signal()

@Events.pre_tool_use.connect
def security_validator(sender, **kwargs):
    tool = kwargs.get("tool")
    if tool.name in BLOCKED_TOOLS:
        raise SecurityError(f"Tool {tool.name} is blocked")
```

## Data Flow

### Primary Request Flow

```
[Voice/Text/Message Input]
         ↓
    [Gateway.handle_input()]
         ↓
    [Event: input.received]
         ↓
    ┌─────────────────────────────────────┐
    │        PIPELINE STAGES              │
    │  1. Transcription (if audio)        │
    │  2. Cleaning/Normalization          │
    │  3. Intent Classification           │
    │  4. Memory Retrieval                │
    │  5. LLM Processing                  │
    │  6. Tool Execution (if needed)      │
    │  7. Response Generation             │
    │  8. Routing Decision                │
    │  9. Safe Write to Destination       │
    └─────────────────────────────────────┘
         ↓
    [Event: output.ready]
         ↓
    [Return Response / Voice Output]
         ↓
    [Event: session.end] → [Memory Capture]
```

### Memory Flow

```
[User Interaction]
        ↓
[Session Memory] ← immediate context, ephemeral
        ↓ (on task completion)
[Working Memory] ← task artifacts, file-based
        ↓ (on explicit save / high-value)
[Learning Memory] ← curated facts, preferences
        ↓ (indexed)
[Vector Store] ← semantic search
```

### Background Task Flow

```
[FSEvents Watchdog] → [Hash Cache Check] → [Index Queue]
                                              ↓
                                        [Throttling Check]
                                        (CPU < 20%, RAM > 2GB)
                                              ↓
                                        [Index Task] → [Vector Store]
```

### Key Data Flows

1. **Voice Capture → Note:** Audio → STT → Cleaning → Classification → Safe Write to Obsidian
2. **Message → Task:** Message → Parse → Intent → LLM → Tool Execution → Queue → Result
3. **Memory Query:** Query → Hybrid Search (Vector 70% + BM25 30%) → Rank → Return
4. **Plugin Discovery:** Startup → Scan plugins/ → Load manifests → Register capabilities

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| Single user | Monolith gateway, SQLite queue, local embeddings |
| Power user (1000+ notes) | Add vector index optimization, memory tiering |
| Multi-device | Add sync layer (CRDT or last-write-wins) |

### Scaling Priorities

1. **First bottleneck:** Voice transcription latency — use streaming STT (Deepgram), local Whisper for offline
2. **Second bottleneck:** Vector search at scale — implement HNSW index, partition by time
3. **Third bottleneck:** Memory context bloat — aggressive summarization, relevance filtering

## Anti-Patterns

### Anti-Pattern 1: Cloud-First with Offline Afterthought

**What people do:** Build cloud-dependent, add offline as caching layer later.

**Why it's wrong:** Local-first requires inversion — local is source of truth, cloud is backup.

**Do this instead:** Start with local-first, treat cloud as optional sync/backup.

### Anti-Pattern 2: Chat History as Memory

**What people do:** Append all conversations to growing chat log, pass to LLM.

**Why it's wrong:** Unbounded context, expensive, lossy retrieval, no structure.

**Do this instead:** Layered memory with explicit capture, summarization, and structured storage.

### Anti-Pattern 3: Direct File Writes Without Race Protection

**What people do:** Write directly to Obsidian vault files without coordination.

**Why it's wrong:** Race conditions with Obsidian auto-save cause data loss.

**Do this instead:** Safe write protocol with mtime double-check, atomic temp+replace.

### Anti-Pattern 4: Monolithic Tool Permissions

**What people do:** All-or-nothing tool access (full filesystem access or none).

**Why it's wrong:** Security risk, no fine-grained control, hard to audit.

**Do this instead:** Capability registry with per-tool permissions, approval gates for destructive operations.

### Anti-Pattern 5: Synchronous Background Processing

**What people do:** Run indexing, embedding generation synchronously on every file change.

**Why it's wrong:** Blocks user interaction, resource spikes, poor UX.

**Do this instead:** Task queue with smart throttling (CPU < 20%, RAM > 2GB, power-aware).

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Obsidian | File system with safe write | No API — direct markdown files |
| OpenAI/Anthropic | HTTP API with failover | Cloud intelligence layer |
| Ollama | Local HTTP API | Local intelligence layer |
| Whisper/Deepgram | Streaming WebSocket | Voice transcription |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Gateway ↔ Pipeline | Direct call | Same process, async |
| Gateway ↔ Plugins | Event bus | Decoupled, plugin isolation |
| Pipeline ↔ Storage | Safe write protocol | Race condition prevention |
| Memory ↔ Index | Async queue | Throttled background |
| Gateway ↔ LLM | HTTP | External service |

## Build Order Implications

Based on architecture dependencies, recommended build order:

1. **Phase 1: Core Infrastructure**
   - Event bus (foundation for all coordination)
   - Gateway skeleton (central coordinator)
   - Storage abstractions (system + vault domains)
   - Safe write protocol (prevents data loss)

2. **Phase 2: Data Pipeline**
   - Pipeline orchestrator
   - Transcription stage (STT)
   - Cleaning/normalization stage
   - Saving stage (file persistence)

3. **Phase 3: Intelligence Layer**
   - LLM router (local/cloud)
   - Session manager
   - Basic memory (session tier)

4. **Phase 4: Extensibility**
   - Plugin system with auto-discovery
   - Capabilities registry
   - Skills system

5. **Phase 5: Advanced Features**
   - Multi-tier memory
   - Vector indexing
   - Background task queue
   - Smart throttling

**Dependency rationale:** Event bus has no dependencies (build first). Gateway needs events and storage. Pipeline needs gateway and storage. Memory needs storage and can enhance pipeline. Plugins need all core to integrate.

## Sources

- **Clawdbot Architecture** (HIGH confidence) — https://mmntm.net/articles/clawdbot-architecture — Local-first AI infrastructure patterns, gateway-centric design, memory architecture
- **AI Agents 2026 Architecture** (HIGH confidence) — https://andriifurmanets.com/blogs/ai-agents-2026-practical-architecture-tools-memory-evals-guardrails — Tool contracts, state machines, memory layers
- **Voice Agent Architecture** (HIGH confidence) — https://www.arunbaby.com/ai-agents/0017-voice-agent-architecture — STT/TTS pipeline, VAD, barge-in, latency requirements
- **Personal AI Infrastructure (PAI)** (HIGH confidence) — https://danielmiessler.com/blog/personal-ai-infrastructure — Seven component architecture, memory system, hook system
- **Local-First Architecture Guide** (MEDIUM confidence) — https://blog.4geeks.io/implementing-local-first-architecture — Local-first principles, sync patterns
- **Local-First Apps 2025** (MEDIUM confidence) — https://debugg.ai/resources/local-first-apps-2025-crdts-replication-edge-storage-offline-sync — CRDTs, replication patterns
- **Obsidian File I/O Patterns** (MEDIUM confidence) — https://forum.obsidian.md/t/file-i-o-patterns-to-best-cooperate-with-obsidian/105606 — Race condition prevention
- **Personal Knowledge Management at Scale** (MEDIUM confidence) — https://www.dsebastien.net/personal-knowledge-management-at-scale-analyzing-8-000-notes-and-64-000-links — PKM architecture, scaling considerations

---
*Architecture research for: local-first personal AI assistant*
*Researched: 2026-02-18*
