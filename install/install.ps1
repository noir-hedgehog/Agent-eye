# Eye Vision Capture Tool - Windows Installation Script
# Based on actuation-control pattern, customized for Eye's dual-binary structure
# SPDX-License-Identifier: GPL-3.0-or-later
# Derivative of https://github.com/nullvoider07/the-eyes — fork: https://github.com/noir-hedgehog/Agent-eye

$ErrorActionPreference = "Stop"

# ============================================================================
# Configuration
# ============================================================================
$REPO = "nullvoider07/the-eyes"
$SERVER_BINARY = "eye-server.exe"
$CLI_BINARY = "eye.exe"

if (Get-Command "eye" -ErrorAction SilentlyContinue) {
    Write-Host "⚠️  Eye Vision Capture Tool is already installed." -ForegroundColor Yellow
    Write-Host "💡 To update to the latest version, simply run:" -ForegroundColor Cyan
    Write-Host "   eye update" -ForegroundColor White
    Write-Host ""
    
    $Confirmation = Read-Host "Do you still want to force a reinstall? [y/N]"
    if ($Confirmation -notmatch "^[Yy]$") {
        Write-Host "Installation cancelled." -ForegroundColor Gray
        exit 0
    }
    Write-Host "Proceeding with reinstall..." -ForegroundColor Gray
}

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Eye Vision Capture Tool - Installer" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================================
# Detect Architecture
# ============================================================================
$ARCH_TYPE = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }
Write-Host "Detected: Windows ($ARCH_TYPE)"

# ============================================================================
# Get Latest Release
# ============================================================================
Write-Host "Fetching latest version from GitHub..."

try {
    $ReleaseUrl = "https://api.github.com/repos/$REPO/releases/latest"
    $LatestRelease = Invoke-RestMethod -Uri $ReleaseUrl
    $LATEST_TAG = $LatestRelease.tag_name
    $VERSION = $LATEST_TAG.TrimStart('v')
    
    Write-Host "Latest Version: $VERSION" -ForegroundColor Green
} catch {
    Write-Host "Error: Could not fetch latest release" -ForegroundColor Red
    Write-Host "Check: https://github.com/$REPO/releases" -ForegroundColor Yellow
    exit 1
}

# ============================================================================
# Construct Download URL
# ============================================================================
$FILE_NAME = "eye-$VERSION-win-$ARCH_TYPE.zip"
$DOWNLOAD_URL = "https://github.com/$REPO/releases/download/$LATEST_TAG/$FILE_NAME"

Write-Host "Download URL: $DOWNLOAD_URL"

# ============================================================================
# Download Release Package
# ============================================================================
Write-Host "Downloading Eye v$VERSION..."

$TempZip = "$env:TEMP\eye-$VERSION-win.zip"

try {
    Invoke-WebRequest -Uri $DOWNLOAD_URL -OutFile $TempZip -UseBasicParsing
    Write-Host "Downloaded successfully" -ForegroundColor Green
} catch {
    Write-Host "Download failed" -ForegroundColor Red
    Write-Host "Please check:" -ForegroundColor Yellow
    Write-Host "  1. Release exists: https://github.com/$REPO/releases/tag/$LATEST_TAG"
    Write-Host "  2. Asset exists: $FILE_NAME"
    if (Test-Path $TempZip) { Remove-Item $TempZip -Force }
    exit 1
}

# ============================================================================
# Install to AppData\Local\Programs\Eye
# (Following actuation pattern)
# ============================================================================
$INSTALL_DIR = "$env:LOCALAPPDATA\Programs\Eye"

Write-Host "Installing to $INSTALL_DIR..."

if (-not (Test-Path $INSTALL_DIR)) {
    New-Item -ItemType Directory -Path $INSTALL_DIR | Out-Null
}

# Extract directly to install directory
try {
    Expand-Archive -Path $TempZip -DestinationPath $INSTALL_DIR -Force
} catch {
    Write-Host "Extraction failed" -ForegroundColor Red
    Remove-Item $TempZip -Force -ErrorAction SilentlyContinue
    exit 1
}

# ============================================================================
# Verify Binaries Exist
# (Package structure: bin/eye-server.exe and bin/eye.exe)
# ============================================================================
$SERVER_PATH = Join-Path $INSTALL_DIR "bin\$SERVER_BINARY"
$CLI_PATH = Join-Path $INSTALL_DIR "bin\$CLI_BINARY"

if (-not (Test-Path $SERVER_PATH)) {
    Write-Host "Error: $SERVER_BINARY not found" -ForegroundColor Red
    Write-Host "Expected at: $SERVER_PATH" -ForegroundColor Yellow
    Write-Host "Package contents:" -ForegroundColor Yellow
    Get-ChildItem $INSTALL_DIR -Recurse | Select-Object FullName
    Remove-Item $TempZip -Force
    exit 1
}

if (-not (Test-Path $CLI_PATH)) {
    Write-Host "Error: $CLI_BINARY not found" -ForegroundColor Red
    Write-Host "Expected at: $CLI_PATH" -ForegroundColor Yellow
    Write-Host "Package contents:" -ForegroundColor Yellow
    Get-ChildItem $INSTALL_DIR -Recurse | Select-Object FullName
    Remove-Item $TempZip -Force
    exit 1
}

Write-Host "Binaries verified" -ForegroundColor Green

# ============================================================================
# Add bin directory to PATH
# (Following actuation pattern)
# ============================================================================
$BIN_DIR = Join-Path $INSTALL_DIR "bin"
$USER_PATH = [Environment]::GetEnvironmentVariable("Path", "User")

if ($USER_PATH -notlike "*$BIN_DIR*") {
    Write-Host "Adding to PATH..." -ForegroundColor Yellow
    [Environment]::SetEnvironmentVariable("Path", "$USER_PATH;$BIN_DIR", "User")
    $env:Path += ";$BIN_DIR"
    $PATH_UPDATED = $true
} else {
    Write-Host "PATH already configured" -ForegroundColor Green
    $PATH_UPDATED = $false
}

# ============================================================================
# Clean Up
# ============================================================================
Remove-Item $TempZip -Force

# ============================================================================
# Installation Complete
# ============================================================================
Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "Eye v$VERSION installed successfully!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Installed to: $INSTALL_DIR" -ForegroundColor Cyan
Write-Host ""
Write-Host "Binaries:"
Write-Host "  • eye-server.exe" -ForegroundColor Cyan
Write-Host "  • eye.exe" -ForegroundColor Cyan
Write-Host ""
Write-Host "Quick Start:"
Write-Host "  # Terminal 1: Start server"
Write-Host "  eye-server" -ForegroundColor Yellow
Write-Host ""
Write-Host "  # Terminal 2: Start agent"
Write-Host "  eye agent start --server http://localhost:8080 --token mytoken" -ForegroundColor Yellow
Write-Host ""
Write-Host "Uninstallation:"
Write-Host "  To remove Eye from your system:"
Write-Host "  eye uninstall" -ForegroundColor Yellow
Write-Host ""

if ($PATH_UPDATED) {
    Write-Host "✅ Path updated. You may need to restart your terminal." -ForegroundColor Green
    Write-Host ""
    Write-Host "Or run this to refresh current session:" -ForegroundColor Yellow
    Write-Host '  $env:Path = [Environment]::GetEnvironmentVariable("Path", "User")' -ForegroundColor Cyan
} else {
    Write-Host "Try it now:"
    Write-Host "  eye --help" -ForegroundColor Yellow
    Write-Host "  eye-server --help" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "🎉 Installation Complete!" -ForegroundColor Green