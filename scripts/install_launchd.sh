#!/bin/bash
# Install launchd plist for voice watch service
#
# Usage: ./install_launchd.sh
#
# This script:
# 1. Replaces USER placeholder with actual username
# 2. Copies plist to ~/Library/LaunchAgents/
# 3. Loads the service with launchctl
# 4. Verifies the service is running

set -e

PLIST_SOURCE="$(dirname "$0")/../launchd/com.butler.voicewatch.plist"
USER_HOME="$HOME"
USER_NAME="$(whoami)"

echo "Installing voice watch launchd service..."

# Check if plist exists
if [ ! -f "$PLIST_SOURCE" ]; then
	echo "Error: plist file not found at $PLIST_SOURCE"
	exit 1
fi

# Create LaunchAgents directory if needed
mkdir -p "$USER_HOME/Library/LaunchAgents"

# Copy plist and replace USER placeholder
DEST_PATH="$USER_HOME/Library/LaunchAgents/com.butler.voicewatch.plist"
sed "s|USER|$USER_NAME|g" "$PLIST_SOURCE" >"$DEST_PATH"

echo "Copied plist to $DEST_PATH"

# Load the service
echo "Loading service..."
launchctl load "$DEST_PATH"

# Verify it's loaded
if launchctl list | grep -q "com.butler.voicewatch"; then
	echo "Service loaded successfully"
else
	echo "Warning: Service may not have loaded properly"
fi

echo "Voice watch service installed and running"
echo ""
echo "To check status: launchctl list | grep butler"
echo "To view logs: tail -f ~/.butler/logs/voicewatch.log"
echo "To stop: launchctl unload ~/Library/LaunchAgents/com.butler.voicewatch.plist"
