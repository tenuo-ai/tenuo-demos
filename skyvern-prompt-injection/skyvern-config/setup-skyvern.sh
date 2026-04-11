#!/bin/bash
# Setup Skyvern for the SoundHaven demo
# Run this once before running tasks

set -e

SKYVERN_DIR="${SKYVERN_DIR:-../../skyvern}"

echo "============================================"
echo "  Skyvern Setup for SoundHaven Demo"
echo "============================================"
echo ""

# Check Skyvern directory
if [ ! -d "$SKYVERN_DIR" ]; then
    echo "[ERROR] Skyvern directory not found at: $SKYVERN_DIR"
    echo "        Set SKYVERN_DIR to your Skyvern installation path"
    exit 1
fi

cd "$SKYVERN_DIR"
echo "[*] Skyvern directory: $(pwd)"

# Create .env if it doesn't exist
if [ ! -f .env ]; then
    cp .env.example .env
    echo "[*] Created .env from .env.example"
else
    echo "[*] .env already exists"
fi

# Check for Anthropic API key
if ! grep -q "ANTHROPIC_API_KEY=\"sk-" .env 2>/dev/null; then
    echo ""
    echo "[!] ANTHROPIC_API_KEY is not set in $SKYVERN_DIR/.env"
    echo "    Please add your Anthropic API key:"
    echo ""
    echo "    ENABLE_ANTHROPIC=true"
    echo "    ANTHROPIC_API_KEY=\"sk-ant-...\""
    echo "    LLM_KEY=\"ANTHROPIC_CLAUDE4.5_SONNET\""
    echo ""
fi

# Verify required settings
echo ""
echo "[*] Required .env settings for this demo:"
echo "    ENABLE_ANTHROPIC=true"
echo "    ANTHROPIC_API_KEY=\"sk-ant-...\""
echo "    LLM_KEY=\"ANTHROPIC_CLAUDE4.5_SONNET\""
echo "    SECONDARY_LLM_KEY=\"ANTHROPIC_CLAUDE4.5_HAIKU\""
echo ""

echo "[*] To start Skyvern:"
echo "    cd $SKYVERN_DIR && skyvern run server"
echo ""
echo "[*] To start the demo store:"
echo "    cd demo-store && python -m http.server 3000"
echo ""
echo "[*] To run a task:"
echo "    python skyvern-config/task.py clean    # Happy path"
echo "    python skyvern-config/task.py attack   # Prompt injection"
echo "    python skyvern-config/task.py defended  # With Tenuo"
echo ""
echo "[OK] Setup complete"
