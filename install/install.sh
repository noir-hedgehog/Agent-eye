#!/bin/bash
# Eye Vision Capture Tool - Installation Script
# SPDX-License-Identifier: GPL-3.0-or-later
# Derivative of https://github.com/nullvoider07/the-eyes — fork: https://github.com/noir-hedgehog/Agent-eye

set -e

# ============================================================================
# Configuration
# ============================================================================
REPO="nullvoider07/the-eyes"
INSTALL_DIR="$HOME/.local/bin"
SERVER_BINARY="eye-server"
CLI_BINARY="eye"

# ============================================================================
# Check Existing Installation
# ============================================================================
if command -v "$CLI_BINARY" &> /dev/null; then
    echo "⚠️  Eye Vision Capture Tool is already installed."
    echo "💡 To update to the latest version, simply run:"
    echo "   $CLI_BINARY update"
    echo ""
    read -p "Do you still want to force a reinstall? [y/N] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 0
    fi
    echo "Proceeding with reinstall..."
fi

# ============================================================================
# Detect OS
# ============================================================================
OS="$(uname -s)"
case "${OS}" in
    Linux*)     OS_TYPE="linux";;
    Darwin*)    OS_TYPE="osx";;
    *)          echo "❌ Unsupported OS: ${OS}"; exit 1;;
esac

# ============================================================================
# Detect Architecture
# ============================================================================
ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64)    ARCH_TYPE="x64";;
    arm64)     ARCH_TYPE="arm64";;
    aarch64)   ARCH_TYPE="arm64";;
    *)         echo "❌ Unsupported Architecture: ${ARCH}"; exit 1;;
esac

echo "Detected: ${OS_TYPE} (${ARCH_TYPE})"

# ============================================================================
# Get Latest Release
# ============================================================================
echo "Fetching latest version from GitHub..."
LATEST_TAG=$(curl -s "https://api.github.com/repos/$REPO/releases/latest" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')

if [ -z "$LATEST_TAG" ]; then
    echo "❌ Error: Could not find latest release."
    echo "Check: https://github.com/$REPO/releases"
    exit 1
fi

# Extract version
VERSION=${LATEST_TAG#v}
echo "Latest Version: ${VERSION}"

# ============================================================================
# Construct Download URL
# ============================================================================
FILE_NAME="eye-${VERSION}-${OS_TYPE}-${ARCH_TYPE}.tar.gz"
DOWNLOAD_URL="https://github.com/$REPO/releases/download/$LATEST_TAG/$FILE_NAME"

echo "Download URL: $DOWNLOAD_URL"

# ============================================================================
# Download Release Package
# ============================================================================
echo "Downloading Eye v${VERSION}..."
TMP_FILE="/tmp/eye-install-$$.tar.gz"

if ! curl -L -f -o "$TMP_FILE" "$DOWNLOAD_URL"; then
    echo "❌ Download failed."
    echo "Please check:"
    echo "  1. Release exists: https://github.com/$REPO/releases/tag/$LATEST_TAG"
    echo "  2. Asset exists: $FILE_NAME"
    exit 1
fi

echo "✅ Downloaded successfully"

# ============================================================================
# Extract Archive
# ============================================================================
echo "Extracting..."
TMP_DIR="/tmp/eye-extract-$$"
mkdir -p "$TMP_DIR"

tar -xzf "$TMP_FILE" -C "$TMP_DIR"

# ============================================================================
# Verify Binaries Exist
# ============================================================================
if [ ! -f "$TMP_DIR/bin/$SERVER_BINARY" ]; then
    echo "❌ Error: $SERVER_BINARY not found in package"
    ls -la "$TMP_DIR"
    exit 1
fi

if [ ! -f "$TMP_DIR/bin/$CLI_BINARY" ]; then
    echo "❌ Error: $CLI_BINARY not found in package"
    ls -la "$TMP_DIR"
    exit 1
fi

# ============================================================================
# Install Binaries
# ============================================================================
echo "Installing to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

# Copy both binaries
cp "$TMP_DIR/bin/$SERVER_BINARY" "$INSTALL_DIR/"
cp "$TMP_DIR/bin/$CLI_BINARY" "$INSTALL_DIR/"

# Make executable
chmod +x "$INSTALL_DIR/$SERVER_BINARY"
chmod +x "$INSTALL_DIR/$CLI_BINARY"

# ============================================================================
# macOS Specific: Remove Quarantine
# ============================================================================
if [[ "$OS_TYPE" == "osx" ]]; then
    echo "Removing macOS quarantine attributes..."
    xattr -d com.apple.quarantine "$INSTALL_DIR/$SERVER_BINARY" 2>/dev/null || true
    xattr -d com.apple.quarantine "$INSTALL_DIR/$CLI_BINARY" 2>/dev/null || true
fi

# ============================================================================
# Clean Up
# ============================================================================
rm -rf "$TMP_FILE" "$TMP_DIR"

# ============================================================================
# Update PATH if Needed
# ============================================================================
SHELL_CONFIG=""
case "$SHELL" in
    */zsh)  SHELL_CONFIG="$HOME/.zshrc" ;;
    */bash) SHELL_CONFIG="$HOME/.bashrc" ;;
    *)      SHELL_CONFIG="$HOME/.profile" ;;
esac

if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
    echo ""
    echo "Adding $INSTALL_DIR to PATH in $SHELL_CONFIG..."
    echo "" >> "$SHELL_CONFIG"
    echo "# Eye Vision Capture Tool" >> "$SHELL_CONFIG"
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_CONFIG"
    
    PATH_UPDATED=true
else
    PATH_UPDATED=false
fi

# ============================================================================
# Installation Complete
# ============================================================================
echo ""
echo "========================================="
echo "✅ Eye v${VERSION} installed successfully!"
echo "========================================="
echo ""
echo "Installed binaries:"
echo "  • eye-server  → $INSTALL_DIR/$SERVER_BINARY"
echo "  • eye         → $INSTALL_DIR/$CLI_BINARY"
echo ""
echo "Quick Start:"
echo "  # Terminal 1: Start server"
echo "  eye-server"
echo ""
echo "  # Terminal 2: Start agent"
echo "  eye agent start --server http://localhost:8080 --token mytoken"
echo ""
echo "Uninstallation:"
echo "  To remove Eye from your system:"
echo "  eye uninstall"
echo ""

if [ "$PATH_UPDATED" = true ]; then
    echo "⚠️  PATH updated. Apply changes with:"
    echo "  source $SHELL_CONFIG"
    echo ""
    echo "Or restart your terminal."
else
    echo "Try it now:"
    echo "  eye --help"
    echo "  eye-server --help"
fi

echo ""