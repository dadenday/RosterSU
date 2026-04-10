#!/bin/bash
# RosterSU - Quick Install Script
# Run this to install all dependencies before first use
# Usage: ./install.sh

set -e  # Exit on error

echo "============================================================"
echo "RosterSU - Dependency Installer"
echo "============================================================"
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "✗ Error: Python not found!"
    echo ""
    echo "Please install Python 3.9+ first:"
    echo "  - Ubuntu/Debian: sudo apt install python3"
    echo "  - Termux:        pkg install python"
    echo "  - macOS:         brew install python"
    exit 1
fi

# Determine Python command
if command -v python3 &> /dev/null; then
    PYTHON=python3
else
    PYTHON=python
fi

echo "Using Python: $($PYTHON --version)"
echo ""

# Check if pip is available
if ! $PYTHON -m pip --version &> /dev/null; then
    echo "✗ Error: pip not found!"
    echo ""
    echo "Please install pip first:"
    echo "  - Ubuntu/Debian: sudo apt install python3-pip"
    echo "  - Termux:        pkg install python"
    echo "  - macOS:         brew install pip"
    exit 1
fi

echo "Installing dependencies..."
echo "(This may take a few minutes)"
echo ""

# Install dependencies
$PYTHON -m pip install --upgrade -r requirements.txt

echo ""
echo "============================================================"
echo "✓ All dependencies installed successfully!"
echo "============================================================"
echo ""
echo "You can now run the application:"
echo "  $PYTHON roster_single_user.py"
echo ""
