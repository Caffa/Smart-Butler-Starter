# Smart Butler - Voice-to-Obsidian Plugin

A macOS plugin that automatically transcribes your iPhone voice memos and saves them as daily notes in Obsidian.

## 🎉 Quick Start

```bash
# 1. Install with one command
curl -sSL https://raw.githubusercontent.com/yourusername/smart-butler/main/scripts/install.sh | bash

# 2. Verify installation
butler doctor

# 3. Trigger voice processing (launchd does this automatically)
butler process-voice

# 4. Drop a voice memo in ~/Music/Voice Memos
# → Watch it appear in Obsidian daily notes!
```

## 🚀 Features

- **Voice Input**: Auto-discovers iPhone voice memos in `~/Music/Voice Memos`
- **Local Transcription**: Uses `parakeet-mlx` for Apple Silicon-optimized transcription
- **Obsidian Integration**: Writes to `~/Documents/Obsidian/Vault/Daily/YYYY-MM-DD.md`
- **Safe File Operations**: Atomic writes prevent Obsidian corruption
- **Plugin System**: Auto-discovery and lifecycle management
- **Event Bus**: Signal-based communication between components
- **Task Queue**: SQLite-backed background processing with crash recovery
- **Smart Throttling**: Defers tasks when CPU/RAM/power limits exceeded

## 📋 Requirements

- **macOS 14.0+** (for Apple Silicon features)
- **Python 3.10+**
- **Ollama** (for AI models)
- **parakeet-mlx** (for transcription, macOS only)

## 🛠️ Installation

### One-Command Install

```bash
curl -sSL https://raw.githubusercontent.com/yourusername/smart-butler/main/scripts/install.sh | bash
```

The script will:

- Create `~/.butler/` directory structure
- Install Python package
- Set up launchd for automatic folder watching
- Run `butler doctor` to verify dependencies

### Manual Install

```bash
# Clone the repo
git clone https://github.com/yourusername/smart-butler.git
cd smart-butler

# Install dependencies
pip install -e .

# Set up directories
mkdir -p ~/.butler/{logs,plugins,data}

# Install launchd (macOS)
cp launchd/com.butler.voicewatch.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.butler.voicewatch.plist

# Verify installation
butler doctor
```

## 🧪 Health Check

```bash
butler doctor
```

This checks:

- Python version
- macOS compatibility
- Ollama installation and models
- parakeet-mlx availability
- Disk space and permissions

### Auto-Fix Missing Models

```bash
butler doctor --fix
```

This downloads required AI models (llama3.1:8b, nomic-embed-text).

## 💬 Usage

### Voice Processing

Voice memos are automatically processed when:

1. Drop audio files in `~/Music/Voice Memos`
2. launchd triggers `butler process-voice`
3. Manual run: `butler process-voice`

### Manual Processing

```bash
# Process all pending voice memos
butler process-voice

# Show help
butler --help
```

### Configuration

Configuration is in `~/.butler/config.yaml`. Edit with:

```bash
butler config  # Opens in default editor
```

## 📁 Directory Structure

```
~/.butler/
├── config.yaml              # Main configuration
├── logs/
│   ├── verbose.log        # DEBUG level logs
│   └── error.log          # WARNING+ level logs
├── plugins/
│   ├── voice_input/
│   │   ├── plugin.yaml
│   │   └── user-data.json
│   └── daily_writer/
│       ├── plugin.yaml
│       └── user-data.json
└── data/
    └── tasks.db            # Huey task queue
```

## 🔧 Troubleshooting

### Common Issues

**Voice memos not appearing in Obsidian?**

- Check `butler doctor` for missing dependencies
- Verify `~/Music/Voice Memos` folder exists
- Check `~/.butler/logs/error.log` for errors
- Run `butler process-voice` manually to test

**Permission denied errors?**

- Ensure you have write permissions to `~/.butler/`
- Check launchd logs: `launchctl list | grep butler`

**Transcription not working?**

- Install parakeet-mlx: `pip install parakeet-mlx`
- Download models: `butler doctor --fix`
- Check model availability: `ollama list`

### Debug Mode

```bash
# Verbose logging
BUTLER_DEBUG=1 butler process-voice

# Check launchd status
launchctl list | grep butler
launchctl load ~/Library/LaunchAgents/com.butler.voicewatch.plist
```

## 🔄 Rollback

```bash
# Rollback to stable phase 1 state
git checkout phase-01-complete

# Or reinstall fresh
curl -sSL https://raw.githubusercontent.com/yourusername/smart-butler/main/scripts/install.sh | bash
```

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## 📄 License

MIT License - see [LICENSE](LICENSE) file.

## 📝 Version History

- **v0.1.0** (2026-02-18) - Phase 1 Complete: Core Infrastructure with voice-to-Obsidian pipeline
- **v0.0.1** (2026-02-17) - Initial prototype

---

**Smart Butler** - Making voice memos work for you, automatically.
