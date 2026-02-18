#!/usr/bin/env bash
#
# Smart Butler 2.0 - Installation Script
# 
# One-line installation:
#   curl -sSL https://raw.githubusercontent.com/yourusername/smart-butler/main/scripts/install.sh | bash
#
# Dry run:
#   bash install.sh --dry-run
#

set -e

# Colors for friendly output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
BUTLER_HOME="${HOME}/.butler"
BUTLER_CONFIG="${BUTLER_HOME}/config.yaml"
BUTLER_LOGS="${BUTLER_HOME}/logs"
BUTLER_PLUGINS="${BUTLER_HOME}/plugins"
BUTLER_DATA="${BUTLER_HOME}/data"
REPO_URL="https://github.com/yourusername/smart-butler.git"
DRY_RUN=false

# Helper functions
print_header() {
    echo -e "${BLUE}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                                                              ║"
    echo "║     🎩  Hello! I'm Butler, your AI assistant                 ║"
    echo "║                                                              ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

# Check if running on macOS
check_os() {
    if [[ "$OSTYPE" != "darwin"* ]]; then
        print_error "Butler currently only supports macOS (Apple Silicon optimized)"
        exit 1
    fi
    print_success "macOS detected"
}

# Check Python version
check_python() {
    print_info "Checking Python version..."
    
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is not installed. Please install Python 3.10 or higher."
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f1)
    PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f2)
    
    if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 10 ]]; then
        print_error "Python 3.10+ required, found $PYTHON_VERSION"
        exit 1
    fi
    
    print_success "Python $PYTHON_VERSION"
}

# Check for existing installation
check_existing() {
    if [[ -d "$BUTLER_HOME" ]]; then
        print_warning "Existing Butler installation found at $BUTLER_HOME"
        
        if [[ "$DRY_RUN" == true ]]; then
            print_info "[DRY RUN] Would prompt to backup and overwrite"
            return
        fi
        
        read -p "Backup existing config and reinstall? [Y/n] " -n 1 -r
        echo
        
        if [[ $REPLY =~ ^[Nn]$ ]]; then
            print_info "Installation cancelled"
            exit 0
        fi
        
        # Backup existing config
        if [[ -f "$BUTLER_CONFIG" ]]; then
            BACKUP_FILE="${BUTLER_HOME}/config.yaml.backup.$(date +%Y%m%d%H%M%S)"
            cp "$BUTLER_CONFIG" "$BACKUP_FILE"
            print_success "Config backed up to $BACKUP_FILE"
        fi
    fi
}

# Create directory structure
create_directories() {
    print_info "Creating Butler home directory..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Would create:"
        print_info "  - $BUTLER_HOME"
        print_info "  - $BUTLER_LOGS"
        print_info "  - $BUTLER_PLUGINS"
        print_info "  - $BUTLER_DATA"
        return
    fi
    
    mkdir -p "$BUTLER_HOME"
    mkdir -p "$BUTLER_LOGS"
    mkdir -p "$BUTLER_PLUGINS"
    mkdir -p "$BUTLER_DATA"
    
    # Set permissions
    chmod 755 "$BUTLER_HOME"
    chmod 755 "$BUTLER_LOGS"
    chmod 755 "$BUTLER_PLUGINS"
    chmod 755 "$BUTLER_DATA"
    
    print_success "Created ~/.butler/ structure"
}

# Create default config
create_config() {
    print_info "Creating default configuration..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Would create $BUTLER_CONFIG"
        return
    fi
    
    cat > "$BUTLER_CONFIG" << 'EOF'
# Smart Butler 2.0 Configuration
# 
# This is your personal configuration file.
# Edit these settings to customize Butler for your workflow.

app:
  name: "Smart Butler"
  version: "2.0.0"
  
# Audio settings
audio:
  input_directory: "~/Library/Mobile Documents/com~apple~CloudDocs/Voice Memos"
  sample_rate: 16000
  
# AI model settings
models:
  llm: "llama3.1:8b"      # Local LLM via Ollama
  embedding: "nomic-embed-text"  # For semantic search
  
# Note routing
routing:
  obsidian_vault: "~/Documents/Obsidian Vault"
  default_destination: "inbox"
  
# Memory settings
memory:
  db_path: "~/.butler/data/memory.db"
  vector_store: "~/.butler/data/vectors"
  
# Logging
logging:
  level: "INFO"
  file: "~/.butler/logs/butler.log"
  max_size_mb: 100
  
# Plugin settings
plugins:
  auto_discover: true
  directory: "~/.butler/plugins"
EOF
    
    chmod 644 "$BUTLER_CONFIG"
    print_success "Created default config.yaml"
}

# Install Python package
install_package() {
    print_info "Installing Smart Butler package..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Would install via pip"
        return
    fi
    
    # Check if we're in a git repo
    if [[ -d ".git" ]] && [[ -f "pyproject.toml" ]]; then
        print_info "Installing from local repository..."
        pip install -e "." --quiet
    else
        print_info "Installing from PyPI..."
        pip install smart-butler --quiet
    fi
    
    print_success "Package installed"
}

# Install launchd plist for auto-start
install_launchd() {
    print_info "Setting up auto-start (launchd)..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Would create ~/Library/LaunchAgents/com.butler.smart.plist"
        return
    fi
    
    PLIST_PATH="${HOME}/Library/LaunchAgents/com.butler.smart.plist"
    
    cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.butler.smart</string>
    <key>ProgramArguments</key>
    <array>
        <string>$(which butler)</string>
        <string>process-voice</string>
    </array>
    <key>StartInterval</key>
    <integer>60</integer>
    <key>StandardOutPath</key>
    <string>${BUTLER_LOGS}/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>${BUTLER_LOGS}/launchd.error.log</string>
</dict>
</plist>
EOF
    
    chmod 644 "$PLIST_PATH"
    print_success "Created launchd plist"
    print_info "To enable auto-start, run: launchctl load $PLIST_PATH"
}

# Run doctor check
run_doctor() {
    print_info "Running health check..."
    
    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Would run: butler doctor"
        return
    fi
    
    if command -v butler &> /dev/null; then
        butler doctor || print_warning "Doctor check had issues (this is OK during initial setup)"
    else
        print_warning "Butler command not found in PATH yet"
    fi
}

# Print completion message
print_completion() {
    echo
    echo -e "${GREEN}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                     ✨ All done! ✨                          ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo
    echo "Butler is installed at: $BUTLER_HOME"
    echo
    echo "Quick start:"
    echo "  butler --help        Show all available commands"
    echo "  butler doctor        Check system health"
    echo "  butler doctor --fix  Download missing AI models"
    echo
    echo "Configuration:"
    echo "  Edit ~/.butler/config.yaml to customize settings"
    echo
    echo "Next steps:"
    echo "  1. Install Ollama: https://ollama.com/download"
    echo "  2. Run 'butler doctor' to verify everything"
    echo "  3. Run 'butler doctor --fix' to download AI models"
    echo
    echo "Need help? Visit: https://github.com/yourusername/smart-butler/issues"
    echo
}

# Parse arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)
                DRY_RUN=true
                print_info "Running in DRY RUN mode (no changes will be made)"
                shift
                ;;
            --help|-h)
                echo "Smart Butler 2.0 - Installation Script"
                echo
                echo "Usage: bash install.sh [OPTIONS]"
                echo
                echo "Options:"
                echo "  --dry-run    Show what would be installed without making changes"
                echo "  --help, -h   Show this help message"
                echo
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
}

# Main installation flow
main() {
    parse_args "$@"
    
    print_header
    
    check_os
    check_python
    check_existing
    create_directories
    create_config
    install_package
    install_launchd
    run_doctor
    
    print_completion
}

# Run main function
main "$@"
