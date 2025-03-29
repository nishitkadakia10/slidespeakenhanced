# slidespeak-mcp

## Usage with Claude Desktop

To use this with Claude Desktop, add the following to your claude_desktop_config.json:

### Docker

```json
{
  "mcpServers": {
    "slidespeak": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "SLIDESPEAK_API_KEY",
        "slidespeak/slidespeak-mcp:0.0.1"
      ],
      "env": {
        "SLIDESPEAK_API_KEY": "YOUR-API-KEY-HERE"
      }
    }
  }
}
```

## Building the Docker Image

```bash
docker build . -t slidespeak/slidespeak-mcp:0.0.1
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

### Using the server directly without Docker

Add the following to your claude_desktop_config.json:

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

## Versions

The version needs to be updated in the following files:

- pyproject.toml -> version
- slidespeak.py -> USER_AGENT