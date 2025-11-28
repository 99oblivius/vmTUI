#!/bin/bash
# Build script for VM Manager using Nuitka
#
# This script compiles the VM Manager into a standalone binary.
# Requirements:
#   - Python 3.13+
#   - nuitka (pip install nuitka)
#   - C compiler (gcc/clang)
#   - patchelf (for Linux)

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}VM Manager - Nuitka Build Script${NC}"
echo "=================================="
echo ""

# Check for nuitka
if ! command -v nuitka &> /dev/null; then
    echo -e "${RED}Error: nuitka not found${NC}"
    echo "Install with: pip install nuitka ordered-set"
    exit 1
fi

# Check for C compiler
if ! command -v gcc &> /dev/null && ! command -v clang &> /dev/null; then
    echo -e "${RED}Error: No C compiler found${NC}"
    echo "Install gcc or clang"
    exit 1
fi

# Output directory
OUTPUT_DIR="dist"
mkdir -p "$OUTPUT_DIR"

echo -e "${YELLOW}Building VM Manager...${NC}"
echo ""

# Nuitka compilation
# --standalone: Include Python runtime
# --onefile: Single executable
# --python-flag=-m: Run as module (for packages with __main__)

python -m nuitka \
    --standalone \
    --onefile \
    --output-dir="$OUTPUT_DIR" \
    --output-filename="vm-manager" \
    --python-flag=-m \
    --nofollow-import-to=tkinter \
    --nofollow-import-to=unittest \
    --nofollow-import-to=test \
    --nofollow-import-to=distutils \
    --assume-yes-for-downloads \
    --remove-output \
    --company-name="VM Manager" \
    --product-name="VM Manager" \
    --product-version="0.1.0" \
    --file-description="TUI-based virtual machine manager" \
    vm_manager

echo ""
echo -e "${GREEN}Build complete!${NC}"
echo ""
echo "Binary location: $OUTPUT_DIR/vm-manager"
echo ""
echo "To install system-wide:"
echo "  sudo cp $OUTPUT_DIR/vm-manager /usr/local/bin/"
echo ""
