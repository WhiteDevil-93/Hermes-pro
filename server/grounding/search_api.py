"""Custom Search API for self-grounding.

Exposes Hermes extraction history as a search endpoint that Vertex AI Gemini
can use for grounding. This creates a self-improving extraction loop:

1. Hermes scrapes Site A and extracts structured records (Run 1).
2. Records are indexed in the local extraction store.
3. On Run 2, Hermes's extraction store is provided as a grounding source.
4. Gemini references prior successful extractions to inform its current strategy.
5. Extraction accuracy improves over time without model fine-tuning.

The endpoint conforms to Vertex AI's required interface:
- Accept a query string
- Return JSON array of objects with 'snippet' and 'uri' fields
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from server.config.settings import PipelineConfig

router = APIRouter()
_pipeline_config = PipelineConfig()


def _search_extraction_store(query: str, data_dir: Path) -> list[dict[str, str]]:
    """Search persisted extraction records for relevant matches.

    Simple substring search across all persisted records.
    """
    results: list[dict[str, str]] = []

    if not data_dir.exists():
        return results

    for run_dir in data_dir.iterdir():
        if not run_dir.is_dir():
            continue

        records_path = run_dir / "records.jsonl"
        metadata_path = run_dir / "metadata.json"

        if not records_path.exists():
            continue

        # Load run metadata for URI
        run_url = ""
        if metadata_path.exists():
            try:
                meta = json.loads(metadata_path.read_text())
                run_url = meta.get("target_url", "")
            except Exception:
                pass

        # Search through records
        try:
            with open(records_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    if query.lower() in line.lower():
                        record = json.loads(line)
                        # Build snippet from field values
                        fields = record.get("fields", {})
                        snippet_parts = []
                        for name, field in fields.items():
                            val = field.get("value") if isinstance(field, dict) else field
                            if val:
                                snippet_parts.append(f"{name}: {val}")
                        snippet = "; ".join(snippet_parts[:5])

                        results.append(
                            {
                                "snippet": snippet[:500],
                                "uri": run_url or f"hermes://run/{run_dir.name}",
                            }
                        )

                        if len(results) >= 10:
                            return results
        except Exception:
            continue

    return results


@router.get("/search")
async def search(
    request: Request,
    q: str = Query(..., description="Search query"),
) -> list[dict[str, str]]:
    """Search the Hermes extraction history.

    Returns results in Vertex AI grounding format:
    [{"snippet": "...", "uri": "..."}]

    Note: caller-controlled `data_dir` overrides are blocked.
    """
    if "data_dir" in request.query_params:
        raise HTTPException(
            status_code=400,
            detail="data_dir override is disabled; configure HERMES_DATA_DIR on the server",
        )

    return _search_extraction_store(q, Path(_pipeline_config.data_dir))
