# Hermes

**Autonomous Web Intelligence Engine**

Hermes is a deterministic scraping engine that uses AI reasoning to navigate and extract structured data from complex, adversarial websites while maintaining full execution authority and observability.

## Quick Start

### Option 1: Docker (recommended)

```bash
git clone <repo-url> && cd Hermes-pro
docker-compose up
```

Server starts at `http://localhost:8080`. Health check: `GET /health`.

### Option 2: Local Development

```bash
git clone <repo-url> && cd Hermes-pro
pip install -e ".[dev]"
playwright install chromium --with-deps
uvicorn server.api.app:app --host 0.0.0.0 --port 8080
```

### Option 3: GitHub Codespaces

Click **Code > Codespaces > New codespace** on the repo page. The devcontainer auto-installs all dependencies and Playwright. The server port 8080 is forwarded automatically.

## Architecture

Hermes consists of four layers:

| Layer | Name | Role |
|-------|------|------|
| A | **Conduit** | Execution engine, lifecycle controller, finite state machine |
| B | **AI Engine** | Reasoning sidecar via Vertex AI Gemini (advisory only) |
| C | **Browser Layer** | Headless browser automation (Playwright) |
| D | **Signals** | Observability, phase tracking, audit trail |

**Core principle:** The Conduit owns execution. The AI Engine advises. Every state transition is observable. Every decision is traceable. Every failure is recoverable.

## API

### Start a scrape run

```bash
curl -X POST http://localhost:8080/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{
    "target_url": "https://example.com",
    "extraction_mode": "heuristic",
    "heuristic_selectors": {
      "title": "h1",
      "content": "p"
    }
  }'
```

### Monitor a run

```bash
# Status
curl http://localhost:8080/api/v1/runs/{run_id}

# Signals (full audit trail)
curl http://localhost:8080/api/v1/runs/{run_id}/signals

# Extracted records
curl http://localhost:8080/api/v1/runs/{run_id}/records

# Real-time via WebSocket
wscat -c ws://localhost:8080/api/v1/ws/runs/{run_id}
```

### List all runs

```bash
curl http://localhost:8080/api/v1/runs
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `VERTEX_PROJECT_ID` | Google Cloud project for Vertex AI | (empty) |
| `VERTEX_LOCATION` | Vertex AI region | `us-central1` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account key | (empty) |
| `HERMES_DATA_DIR` | Local directory for extraction data | `./data` |
| `HERMES_PORT` | Server port | `8080` |
| `HERMES_LOG_LEVEL` | Logging verbosity | `INFO` |
| `HERMES_MAX_CONCURRENT_RUNS` | Parallel run limit | `1` |
| `HERMES_ENV` | Runtime environment (`development`, `local`, `dev`, `production`) | `development` |
| `HERMES_ALLOWED_ORIGINS` | Comma-separated trusted CORS origins (required outside development/local/dev) | (empty) |
| `HERMES_DEV_ALLOW_ALL_ORIGINS` | Enable permissive `*` CORS only for local development | `false` |
| `HERMES_CORS_ALLOW_CREDENTIALS` | Enable CORS credentials (ignored when wildcard origin is active) | `false` |


### CORS Configuration

Hermes is **deny-by-default** for CORS unless origins are explicitly configured.

- In `production` (or any `HERMES_ENV` value other than `development`, `local`, `dev`), you **must** set `HERMES_ALLOWED_ORIGINS`.
- If production starts without `HERMES_ALLOWED_ORIGINS`, Hermes exits at startup with a clear configuration error.
- For local development convenience, set `HERMES_DEV_ALLOW_ALL_ORIGINS=true` to allow `*`. This toggle is ignored outside development/local/dev environments.

Example production configuration:

```bash
export HERMES_ENV=production
export HERMES_ALLOWED_ORIGINS="https://app.example.com,https://admin.example.com"
export HERMES_CORS_ALLOW_CREDENTIALS=true
```

### Extraction Modes

- **heuristic** — CSS selectors, fast and deterministic, no AI cost
- **ai** — Vertex AI Gemini extracts data from DOM snapshots
- **hybrid** — Heuristic first, AI fills gaps for ambiguous fields

## Project Structure

```
server/
  conduit/      # Execution engine (state machine)
  ai_engine/    # Vertex AI Gemini integration
  browser/      # Playwright automation layer
  signals/      # Observability system
  pipeline/     # Data pipeline (raw -> staging -> processed -> persisted)
  grounding/    # Self-grounding search API
  api/          # FastAPI REST + WebSocket endpoints
  config/       # Configuration models
schemas/        # JSON Schemas
tests/          # Test suite
```

## Testing

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Conduit Phases

```
INIT -> NAVIGATE -> ASSESS -> EXTRACT -> VALIDATE -> PERSIST -> COMPLETE
                      |                     |
                      v                     v
                   OBSTRUCT -> AI_REASON  REPAIR
                      |          |
                      v          v
                   (retry)   EXECUTE_PLAN -> ASSESS
```

Any phase can transition to `FAIL`. Every transition emits a Signal.

## License

This project is licensed under the [MIT License](LICENSE).
