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
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()
logger = logging.getLogger(__name__)


def _resolve_search_dir(data_dir: str | None) -> Path:
    """Resolve and validate search directory under configured base data directory."""
    base_dir = Path(os.getenv("HERMES_DATA_DIR", "./data")).resolve()

    if not data_dir:
        return base_dir

    candidate_input = Path(data_dir)
    candidate_dir = (
        candidate_input.resolve()
        if candidate_input.is_absolute()
        else (base_dir / candidate_input).resolve()
    )

    if base_dir in candidate_dir.parents:
        return candidate_dir

    logger.warning(
        "Blocked grounding search data_dir outside HERMES_DATA_DIR",
        extra={
            "requested_data_dir": data_dir,
            "resolved_data_dir": str(candidate_dir),
            "base_data_dir": str(base_dir),
        },
    )
    raise HTTPException(status_code=400, detail="Invalid data_dir")


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
    q: str = Query(..., description="Search query"),
    data_dir: str | None = Query(None, description="Data directory path"),
) -> list[dict[str, str]]:
    """Search the Hermes extraction history.

    Returns results in Vertex AI grounding format:
    [{"snippet": "...", "uri": "..."}]
    """
    resolved_data_dir = _resolve_search_dir(data_dir)
    return _search_extraction_store(q, resolved_data_dir)
