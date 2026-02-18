#!/usr/bin/env bash
#
# Tag Checkpoint Script
# 
# Creates annotated Git tags for rollback checkpoints.
# Usage: bash scripts/tag-checkpoint.sh <tag-name> [message]
#
# Examples:
#   bash scripts/tag-checkpoint.sh "phase-01-plan-01"
#   bash scripts/tag-checkpoint.sh "phase-01-complete" "Phase 1: Core Infrastructure MVP"
#   bash scripts/tag-checkpoint.sh "milestone-v1" "v1.0 Release"
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Validate arguments
if [ $# -lt 1 ]; then
    echo "Smart Butler - Checkpoint Tagger"
    echo
    echo "Usage: bash scripts/tag-checkpoint.sh <tag-name> [message]"
    echo
    echo "Examples:"
    echo "  bash scripts/tag-checkpoint.sh phase-01-plan-01"
    echo "  bash scripts/tag-checkpoint.sh phase-01-complete 'Phase 1 MVP'"
    echo "  bash scripts/tag-checkpoint.sh milestone-v1 'Version 1.0 Release'"
    echo
    echo "Common tag patterns:"
    echo "  phase-XX-plan-YY    - Individual plan completion"
    echo "  phase-XX-complete   - Full phase completion"
    echo "  milestone-NAME      - Major milestone"
    echo "  rollback-XXXX       - Safe rollback point"
    echo
    exit 1
fi

TAG_NAME="$1"
MESSAGE="${2:-Checkpoint: $TAG_NAME}"

# Validate tag name
if [[ ! "$TAG_NAME" =~ ^[a-z0-9_-]+$ ]]; then
    print_error "Invalid tag name: $TAG_NAME"
    print_info "Tag names should only contain lowercase letters, numbers, hyphens, and underscores"
    exit 1
fi

# Check if we're in a git repo
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    print_error "Not a git repository"
    exit 1
fi

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    print_warning "You have uncommitted changes"
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Tagging cancelled"
        exit 0
    fi
fi

# Check if tag already exists
if git rev-parse "$TAG_NAME" >/dev/null 2>&1; then
    print_warning "Tag '$TAG_NAME' already exists"
    
    # Show existing tag details
    echo
    print_info "Existing tag details:"
    git log -1 --format="  Date: %ai%n  Commit: %h%n  Message: %s" "$TAG_NAME"
    echo
    
    read -p "Delete and recreate? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "Deleting existing tag..."
        git tag -d "$TAG_NAME" 2>/dev/null || true
        git push origin ":refs/tags/$TAG_NAME" 2>/dev/null || true
    else
        print_info "Tagging cancelled"
        exit 0
    fi
fi

# Generate detailed tag message
current_date=$(date "+%Y-%m-%d %H:%M:%S")
last_commit=$(git log -1 --format="%h %s")
committer=$(git config user.name || echo "Unknown")

detailed_message="$MESSAGE

Created: $current_date
Committer: $committer
Last Commit: $last_commit

To rollback to this checkpoint:
  git checkout $TAG_NAME

To see all checkpoints:
  git tag -l 'phase-*'"

# Create the annotated tag
print_info "Creating tag: $TAG_NAME"
git tag -a "$TAG_NAME" -m "$detailed_message"

print_success "Created local tag: $TAG_NAME"

# Ask about pushing
read -p "Push tag to origin? [Y/n] " -n 1 -r
echo

if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    print_info "Pushing tag to origin..."
    git push origin "$TAG_NAME"
    print_success "Tag pushed to origin"
else
    print_info "Tag created locally only"
    print_info "Push later with: git push origin $TAG_NAME"
fi

echo
print_success "Checkpoint tagged successfully!"
echo
print_info "Rollback command:"
echo "  git checkout $TAG_NAME"
echo
