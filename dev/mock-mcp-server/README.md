# Mock MCP Server

A FastMCP server with predictable tool responses for testing the Quality Oracle evaluation engine.

## Tools

| Tool | Domain | Description |
|------|--------|-------------|
| `calculate` | general | Evaluate math expressions |
| `search_docs` | search | Search mock documentation |
| `get_weather` | data | Get deterministic weather data |
| `convert_units` | general | Unit conversion |

## Usage

### Standalone (stdio)
```bash
pip install mcp
python server.py
```

### Docker (via docker-compose)
```bash
docker compose --profile dev up mock-mcp-server
```

## Why predictable?

All responses are deterministic (no external APIs), so Quality Oracle can validate its own scoring against known-good outputs during development.
