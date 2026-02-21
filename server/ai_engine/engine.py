"""AI Engine — Sidecar reasoning system backed by Vertex AI Gemini.

The AI Engine provides intelligence without authority. It is invoked by the Conduit,
receives context, returns structured decisions, and has no ability to act on its own.

Authority boundary (HARD CONSTRAINT):
The AI Engine cannot: mutate global config, execute arbitrary code, change runtime
state silently, persist data without Conduit approval, invoke browser actions directly,
or modify its own system prompt.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from server.config.settings import VertexConfig


# --- Function Call Models ---

class FunctionCall(BaseModel):
    """A structured function call returned by the AI Engine."""

    function: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    expected_outcome: str = ""
    fallback: str | None = None


class NavigationPlan(BaseModel):
    """AI-generated navigation plan."""

    actions: list[FunctionCall]
    estimated_steps: int = 0
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class PageClassification(BaseModel):
    """AI classification of the current page state."""

    page_state: str  # CONTENT_VISIBLE, GATED, BLOCKED, ERROR, LOADING, REDIRECT, EMPTY
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    content_regions_detected: int = 0
    obstruction_indicators: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    """AI extraction result with structured records."""

    records: list[dict[str, Any]] = Field(default_factory=list)
    completeness_score: float = Field(ge=0.0, le=1.0, default=0.0)
    duplicates_detected: int = 0


# --- Allowed Function Names (Trust Boundary) ---

ALLOWED_NAVIGATION_FUNCTIONS = frozenset({
    "click",
    "scroll",
    "fill_form",
    "hover",
    "press_key",
    "wait_for",
    "navigate_url",
})

ALLOWED_ASSESSMENT_FUNCTIONS = frozenset({
    "classify_page",
    "classify_obstruction",
    "identify_content_region",
    "assess_completeness",
})

ALLOWED_EXTRACTION_FUNCTIONS = frozenset({
    "extract_structured",
    "repair_extraction",
    "deduplicate",
    "convert_prose_to_fields",
})

ALL_ALLOWED_FUNCTIONS = (
    ALLOWED_NAVIGATION_FUNCTIONS | ALLOWED_ASSESSMENT_FUNCTIONS | ALLOWED_EXTRACTION_FUNCTIONS
)

# Maximum function calls per single AI invocation (circuit breaker)
MAX_FUNCTION_CALLS_PER_INVOCATION = 20


# --- Function Declarations for Gemini ---

NAVIGATION_FUNCTION_DECLARATIONS = [
    {
        "name": "click",
        "description": "Click an element identified by CSS selector",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector for the element"},
                "wait_after_ms": {
                    "type": "integer",
                    "description": "Milliseconds to wait after click",
                    "default": 1000,
                },
            },
            "required": ["selector"],
        },
    },
    {
        "name": "scroll",
        "description": "Scroll the viewport",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                    "description": "Scroll direction",
                },
                "amount": {
                    "type": "string",
                    "description": "Scroll amount: pixels, 'page', or 'end'",
                },
            },
            "required": ["direction", "amount"],
        },
    },
    {
        "name": "fill_form",
        "description": "Type a value into a form field",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["selector", "value"],
        },
    },
    {
        "name": "hover",
        "description": "Hover over an element to trigger interaction",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
            },
            "required": ["selector"],
        },
    },
    {
        "name": "press_key",
        "description": "Press a keyboard key",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Key name (Enter, Escape, Tab, etc.)",
                },
            },
            "required": ["key"],
        },
    },
    {
        "name": "wait_for",
        "description": "Wait for an element to appear in DOM",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "timeout_ms": {"type": "integer", "default": 10000},
            },
            "required": ["selector"],
        },
    },
    {
        "name": "navigate_url",
        "description": "Navigate to a specific URL (must be same-origin unless cross-origin allowed)",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
            },
            "required": ["url"],
        },
    },
]

EXTRACTION_FUNCTION_DECLARATIONS = [
    {
        "name": "extract_structured",
        "description": "Extract structured data from a DOM region according to a schema",
        "parameters": {
            "type": "object",
            "properties": {
                "dom_region": {
                    "type": "string",
                    "description": "CSS selector or HTML of the target region",
                },
                "schema": {"type": "object", "description": "Target extraction schema"},
            },
            "required": ["dom_region", "schema"],
        },
    },
    {
        "name": "repair_extraction",
        "description": "Repair incomplete extraction with AI guidance",
        "parameters": {
            "type": "object",
            "properties": {
                "partial": {"type": "object", "description": "Partial extraction result"},
                "schema": {"type": "object", "description": "Target schema"},
                "dom": {"type": "string", "description": "Raw DOM content"},
            },
            "required": ["partial", "schema", "dom"],
        },
    },
]


def validate_function_call(call: FunctionCall, allow_cross_origin: bool = False) -> str | None:
    """Validate a function call against the allowlist.

    Returns None if valid, or an error string if invalid.
    This is the trust boundary between AI and execution.
    """
    if call.function not in ALL_ALLOWED_FUNCTIONS:
        return f"Unknown function: {call.function}"

    # Type validation for known parameters
    if call.function == "click":
        if "selector" not in call.parameters:
            return "click requires 'selector' parameter"

    if call.function == "scroll":
        direction = call.parameters.get("direction")
        if direction not in ("up", "down"):
            return f"scroll direction must be 'up' or 'down', got '{direction}'"

    if call.function == "fill_form":
        if "selector" not in call.parameters or "value" not in call.parameters:
            return "fill_form requires 'selector' and 'value' parameters"

    if call.function == "navigate_url":
        url = call.parameters.get("url", "")
        if not url:
            return "navigate_url requires a non-empty 'url' parameter"
        # Cross-origin check would be done by the Conduit with the current page URL

    return None


class AIEngine:
    """AI Engine client for Vertex AI Gemini.

    This class handles communication with the Vertex AI API.
    It is stateless — the Conduit manages all state.
    """

    def __init__(self, config: VertexConfig) -> None:
        self._config = config
        self._client = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the Vertex AI client.

        Returns True if initialization succeeds, False otherwise.
        AI Engine is optional — the system works without it (heuristic-only mode).
        """
        if not self._config.project_id:
            return False

        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel

            vertexai.init(
                project=self._config.project_id,
                location=self._config.location,
            )
            self._client = GenerativeModel(self._config.flash_model)
            self._initialized = True
            return True
        except Exception:
            self._initialized = False
            return False

    @property
    def is_available(self) -> bool:
        return self._initialized and self._client is not None

    async def classify_page(self, dom_html: str) -> PageClassification:
        """Classify the current page state using AI.

        Sends DOM snapshot to Gemini, receives structured classification.
        """
        if not self.is_available:
            return PageClassification(
                page_state="CONTENT_VISIBLE",
                confidence=0.3,
                content_regions_detected=0,
            )

        try:
            from vertexai.generative_models import GenerationConfig

            prompt = (
                "Analyze this HTML page and classify its state.\n"
                "Return a JSON object with:\n"
                "- page_state: one of CONTENT_VISIBLE, GATED, BLOCKED, ERROR, LOADING, REDIRECT, EMPTY\n"
                "- confidence: float 0.0-1.0\n"
                "- content_regions_detected: integer count of main content areas\n"
                "- obstruction_indicators: list of strings describing any obstructions\n\n"
                f"HTML:\n{dom_html[:50000]}"  # Truncate to control token usage
            )

            response = await self._client.generate_content_async(
                prompt,
                generation_config=GenerationConfig(
                    response_mime_type="application/json",
                    response_schema={
                        "type": "object",
                        "properties": {
                            "page_state": {"type": "string"},
                            "confidence": {"type": "number"},
                            "content_regions_detected": {"type": "integer"},
                            "obstruction_indicators": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["page_state", "confidence"],
                    },
                ),
            )

            data = json.loads(response.text)
            return PageClassification(**data)
        except Exception:
            return PageClassification(
                page_state="CONTENT_VISIBLE",
                confidence=0.2,
                content_regions_detected=0,
            )

    async def generate_navigation_plan(
        self,
        dom_html: str,
        obstruction_type: str,
        target_schema: dict[str, Any],
        prior_attempts: list[str] | None = None,
    ) -> NavigationPlan:
        """Generate a navigation plan to resolve an obstruction.

        Returns structured function calls, not prose.
        """
        if not self.is_available:
            return NavigationPlan(actions=[], confidence=0.0)

        try:
            from vertexai.generative_models import GenerationConfig

            attempts_context = ""
            if prior_attempts:
                attempts_context = (
                    f"\nPrior failed attempts:\n" + "\n".join(f"- {a}" for a in prior_attempts)
                )

            prompt = (
                f"You are navigating a web page that has an obstruction of type: {obstruction_type}\n"
                f"Target extraction schema: {json.dumps(target_schema)}\n"
                f"{attempts_context}\n\n"
                "Generate a navigation plan as a list of browser actions.\n"
                "Each action must be one of: click, scroll, fill_form, hover, press_key, "
                "wait_for, navigate_url.\n"
                "Return JSON with: actions (list of {function, parameters, expected_outcome}), "
                "estimated_steps (int), confidence (float 0-1).\n\n"
                f"HTML:\n{dom_html[:50000]}"
            )

            response = await self._client.generate_content_async(
                prompt,
                generation_config=GenerationConfig(
                    response_mime_type="application/json",
                    response_schema={
                        "type": "object",
                        "properties": {
                            "actions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "function": {"type": "string"},
                                        "parameters": {"type": "object"},
                                        "expected_outcome": {"type": "string"},
                                    },
                                    "required": ["function", "parameters"],
                                },
                            },
                            "estimated_steps": {"type": "integer"},
                            "confidence": {"type": "number"},
                        },
                        "required": ["actions"],
                    },
                ),
            )

            data = json.loads(response.text)
            actions = [FunctionCall(**a) for a in data.get("actions", [])]

            # Enforce circuit breaker
            if len(actions) > MAX_FUNCTION_CALLS_PER_INVOCATION:
                actions = actions[:MAX_FUNCTION_CALLS_PER_INVOCATION]

            return NavigationPlan(
                actions=actions,
                estimated_steps=data.get("estimated_steps", len(actions)),
                confidence=data.get("confidence", 0.5),
            )
        except Exception:
            return NavigationPlan(actions=[], confidence=0.0)

    async def extract_structured(
        self,
        dom_html: str,
        schema: dict[str, Any],
        source_url: str,
    ) -> ExtractionResult:
        """AI-assisted extraction: send DOM + schema to Gemini, receive structured data."""
        if not self.is_available:
            return ExtractionResult()

        try:
            from vertexai.generative_models import GenerationConfig

            prompt = (
                "Extract structured data from this HTML according to the given schema.\n"
                f"Schema: {json.dumps(schema)}\n"
                f"Source URL: {source_url}\n\n"
                "Return JSON with:\n"
                "- records: list of objects matching the schema fields\n"
                "- completeness_score: float 0-1\n"
                "- duplicates_detected: integer\n\n"
                f"HTML:\n{dom_html[:50000]}"
            )

            response = await self._client.generate_content_async(
                prompt,
                generation_config=GenerationConfig(
                    response_mime_type="application/json",
                ),
            )

            data = json.loads(response.text)
            return ExtractionResult(**data)
        except Exception:
            return ExtractionResult()

    async def repair_extraction(
        self,
        partial_data: dict[str, Any],
        schema: dict[str, Any],
        dom_html: str,
    ) -> ExtractionResult:
        """Repair incomplete extraction using AI guidance."""
        if not self.is_available:
            return ExtractionResult()

        try:
            from vertexai.generative_models import GenerationConfig

            prompt = (
                "The following extraction is incomplete or has errors. "
                "Repair it using the DOM content.\n\n"
                f"Partial data: {json.dumps(partial_data)}\n"
                f"Target schema: {json.dumps(schema)}\n\n"
                f"HTML:\n{dom_html[:50000]}"
            )

            response = await self._client.generate_content_async(
                prompt,
                generation_config=GenerationConfig(
                    response_mime_type="application/json",
                ),
            )

            data = json.loads(response.text)
            return ExtractionResult(**data)
        except Exception:
            return ExtractionResult()
