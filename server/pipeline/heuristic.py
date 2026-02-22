"""Heuristic extraction engine — CSS/XPath selectors for deterministic extraction.

Fast, deterministic, no AI cost. Used when site structure is known and stable.
"""

from __future__ import annotations

from datetime import datetime, timezone

from playwright.async_api import Page

from server.pipeline.extraction import ExtractionRecord, FieldValue, RecordMetadata


async def heuristic_extract(
    page: Page,
    selectors: dict[str, str],
    source_url: str,
    dom_hash: str,
) -> list[ExtractionRecord]:
    """Extract structured data using CSS selectors.

    Args:
        page: Playwright page to extract from.
        selectors: Mapping of field_name -> CSS selector.
        source_url: URL of the page being extracted.
        dom_hash: Hash of the DOM at extraction time.

    Returns:
        List of ExtractionRecord with extracted fields.
    """
    if not selectors:
        return []

    fields: dict[str, FieldValue] = {}
    total_fields = len(selectors)
    extracted_count = 0

    for field_name, selector in selectors.items():
        try:
            # Try to find all matching elements
            elements = await page.query_selector_all(selector)
            if elements:
                # For single-value fields, take the first match
                text = await elements[0].text_content()
                if text:
                    text = text.strip()
                    fields[field_name] = FieldValue(
                        value=text,
                        confidence=1.0,  # Heuristic extraction is deterministic
                        source_selector=selector,
                    )
                    extracted_count += 1
                else:
                    fields[field_name] = FieldValue(
                        value=None,
                        confidence=0.0,
                        source_selector=selector,
                    )
            else:
                fields[field_name] = FieldValue(
                    value=None,
                    confidence=0.0,
                    source_selector=selector,
                )
        except Exception:
            fields[field_name] = FieldValue(
                value=None,
                confidence=0.0,
                source_selector=selector,
            )

    completeness = extracted_count / total_fields if total_fields > 0 else 0.0

    record = ExtractionRecord(
        fields=fields,
        metadata=RecordMetadata(
            source_url=source_url,
            dom_hash=dom_hash,
            extracted_at=datetime.now(timezone.utc),
            extraction_mode="heuristic",
        ),
        completeness_score=completeness,
        is_partial=completeness < 1.0,
    )

    return [record]


async def heuristic_extract_list(
    page: Page,
    container_selector: str,
    item_selectors: dict[str, str],
    source_url: str,
    dom_hash: str,
) -> list[ExtractionRecord]:
    """Extract a list of structured records from a repeating container.

    Args:
        page: Playwright page to extract from.
        container_selector: CSS selector for each item container.
        item_selectors: Mapping of field_name -> CSS selector (relative to container).
        source_url: URL of the page.
        dom_hash: Hash of the DOM.

    Returns:
        List of ExtractionRecord, one per container match.
    """
    containers = await page.query_selector_all(container_selector)
    if not containers:
        return []

    records: list[ExtractionRecord] = []

    for container in containers:
        fields: dict[str, FieldValue] = {}
        total = len(item_selectors)
        extracted = 0

        for field_name, selector in item_selectors.items():
            try:
                element = await container.query_selector(selector)
                if element:
                    text = await element.text_content()
                    if text:
                        text = text.strip()
                        fields[field_name] = FieldValue(
                            value=text,
                            confidence=1.0,
                            source_selector=f"{container_selector} {selector}",
                        )
                        extracted += 1
                    else:
                        fields[field_name] = FieldValue(
                            value=None, confidence=0.0, source_selector=selector
                        )
                else:
                    fields[field_name] = FieldValue(
                        value=None, confidence=0.0, source_selector=selector
                    )
            except Exception:
                fields[field_name] = FieldValue(
                    value=None, confidence=0.0, source_selector=selector
                )

        completeness = extracted / total if total > 0 else 0.0

        # Only include records that have at least one extracted field
        if extracted > 0:
            records.append(
                ExtractionRecord(
                    fields=fields,
                    metadata=RecordMetadata(
                        source_url=source_url,
                        dom_hash=dom_hash,
                        extracted_at=datetime.now(timezone.utc),
                        extraction_mode="heuristic",
                    ),
                    completeness_score=completeness,
                    is_partial=completeness < 1.0,
                )
            )

    return records
