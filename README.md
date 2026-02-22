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

## Architecture and Project Status

### Implemented today

- **Conduit state machine** with explicit phases, transitions, and failure handling.
- **FastAPI API surface** for run creation, run state, records, and signal streams.
- **Playwright browser layer** for deterministic page interaction and obstruction handling.
- **Signals pipeline** for observability and auditability of run execution.
- **Extraction pipeline** with heuristic and AI-assisted modes.
- **CI coverage** for lint, typecheck, tests (multi-Python), schema validation, and Docker smoke tests.

### Planned / in progress

- Hardening of long-running orchestration and retry policies for hostile sites.
- Broader extraction strategies and schema-aware post-processing.
- Expanded grounding/search integrations.
- Production deployment docs and operations playbooks.

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

## Testing (matches CI)

```bash
pip install -e '.[dev]'
ruff check server/ tests/
ruff format --check server/ tests/
mypy server/ --ignore-missing-imports --no-error-summary
pytest tests/ -v --cov=server --cov-report=term-missing --cov-report=xml
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
