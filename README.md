# slidespeak-mcp

## Adding the MCP to Claude

```json
{
  "mcpServers": {
    "slidespeak": {
      "command": "/path/to/.local/bin/uv",
      "args": [
        "--directory",
        "/path/to/slidespeak-mcp",
        "run",
        "slidespeak.py"
      ],
      "env": {
        "SLIDESPEAK_API_KEY": "API-KEY-HERE"
      }
    }
  }
}
```

## Development

### Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Create virtual environment and activate it

uv venv
source .venv/bin/activate

### Install dependencies

```bash
uv pip install -r requirements.txt
```