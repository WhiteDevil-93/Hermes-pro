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

### Extraction Modes

- **heuristic** — CSS selectors, fast and deterministic, no AI cost
- **ai** — Vertex AI Gemini extracts data from DOM snapshots
- **hybrid** — Heuristic first, AI fills gaps for ambiguous fields


## Temporary Security Posture (API hardening)

The API currently enforces conservative safeguards while deeper SSRF and path hardening work is in progress:

- `POST /api/v1/runs` accepts only `http://` and `https://` targets.
- `target_url` values that clearly target local/private networks are rejected (for example `localhost`, loopback, and RFC1918/private IP ranges).
- `GET /api/v1/grounding/search` rejects caller-provided `data_dir`; it reads only from the server-configured `HERMES_DATA_DIR`.

### Known limitations

- URL validation is intentionally minimal and blocks only obvious local/private targets; it does not perform DNS resolution or full SSRF defense.
- Grounding data access is now restricted to the configured data directory, but file-level authorization and tenancy boundaries are not yet implemented.

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

Proprietary — Themyscira Project
