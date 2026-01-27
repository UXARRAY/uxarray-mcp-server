#!/bin/bash
# Setup script for UXarray MCP Server

echo "UXarray MCP Server Setup"
echo ""

# Check prerequisites
echo "[1/4] Checking prerequisites..."

if ! command -v uv &> /dev/null; then
    echo "[ERROR] uv not found. Installing..."
    pip install uv
else
    echo "[OK] uv is installed: $(which uv)"
fi

if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 not found. Please install Python 3.13+"
    exit 1
else
    echo "[OK] Python is installed: $(python3 --version)"
fi

# Install dependencies
echo ""
echo "[2/4] Installing dependencies..."
uv sync

# Test locally
echo ""
echo "[3/4] Testing locally..."
if [ -d "$HOME/Desktop/uxarray/test/meshfiles" ]; then
    uv run python test_local.py
else
    echo "[WARNING] Test mesh files not found at ~/Desktop/uxarray/test/meshfiles/"
    echo "          Clone uxarray repo: git clone https://github.com/UXARRAY/uxarray.git ~/Desktop/uxarray"
fi

# Configure Claude Desktop
echo ""
echo "[4/4] Configuring Claude Desktop..."

CONFIG_FILE="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
UV_PATH=$(which uv)
PROJECT_PATH=$(pwd)

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Creating new config file..."
    cat > "$CONFIG_FILE" << EOFCONFIG
{
  "mcpServers": {
    "uxarray": {
      "command": "$UV_PATH",
      "args": [
        "--directory",
        "$PROJECT_PATH",
        "run",
        "python",
        "-m",
        "uxarray_mcp.server"
      ]
    }
  }
}
EOFCONFIG
    echo "[OK] Created config file at: $CONFIG_FILE"
else
    echo "[WARNING] Config file already exists at: $CONFIG_FILE"
    echo "          Please manually add the uxarray server configuration."
fi

echo ""
echo "[SUCCESS] Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Restart Claude Desktop (Cmd+Q, then reopen)"
echo "  2. Test by asking: 'Do you have access to an inspect_mesh tool?'"
echo ""
echo "Documentation: cat README.md"
