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
import logging
from typing import Any

from pydantic import BaseModel, Field

from server.config.settings import VertexConfig
from server.telemetry.errors import ErrorCode, emit_structured_error

logger = logging.getLogger(__name__)

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


class AttemptRecord(BaseModel):
    """Records one failed navigation or extraction attempt for cross-retry AI context.

    Replaces the flat list[str] previously used for prior_attempts, enabling
    Gemini to reason about what was tried, which selectors failed, and in what
    phase each failure occurred — rather than reading unstructured error strings.
    """

    phase: str                  # Phase where this attempt occurred, e.g. "AI_REASON"
    action: str                 # Action type, e.g. "click", "generate_navigation_plan"
    detail: str                 # Selector, URL, or parameter detail used
    outcome: str                # "failure" | "rejected" | "empty_plan" | "timeout"
    obstruction_type: str = ""  # Obstruction context at time of attempt
    dom_hash: str = ""          # DOM fingerprint at time of attempt


# --- Allowed Function Names (Trust Boundary) ---

ALLOWED_NAVIGATION_FUNCTIONS = frozenset(
    {
        "click",
        "scroll",
        "fill_form",
        "hover",
        "press_key",
        "wait_for",
        "navigate_url",
    }
)

ALLOWED_ASSESSMENT_FUNCTIONS = frozenset(
    {
        "classify_page",
        "classify_obstruction",
        "identify_content_region",
        "assess_completeness",
    }
)

ALLOWED_EXTRACTION_FUNCTIONS = frozenset(
    {
        "extract_structured",
        "repair_extraction",
        "deduplicate",
        "convert_prose_to_fields",
    }
)

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
        "description": (
            "Navigate to a specific URL (must be same-origin unless cross-origin allowed)"
        ),
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
        self._client: Any = None
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
        except Exception as exc:
            emit_structured_error(
                logger,
                code=ErrorCode.AI_INITIALIZATION_FAILED,
                message=str(exc),
                suppressed=True,
            )
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
                "You are an expert web intelligence analyst. Your task is to classify "
                "the state of the HTML page below.\n\n"
                "Page state definitions:\n"
                "  CONTENT_VISIBLE — Main content is accessible with no obstruction\n"
                "  GATED — Content is behind a login wall, paywall, age gate, or "
                "subscription prompt\n"
                "  BLOCKED — Access is denied: bot detection, IP ban, geo-restriction, "
                "or CAPTCHA\n"
                "  ERROR — The server returned an error page (404, 500, 503, etc.)\n"
                "  LOADING — Page is still loading: spinner, skeleton screen, or "
                "'please wait' message\n"
                "  REDIRECT — A redirect stub with no meaningful content\n"
                "  EMPTY — Page loaded successfully but contains no meaningful content\n\n"
                "For obstruction_indicators, list specific observable signals you see "
                "in the HTML, e.g. 'cookie consent modal', 'login form overlay', "
                "'CAPTCHA challenge', 'paywall blur', 'age verification gate'.\n\n"
                f"HTML:\n{dom_html[:50000]}"
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
        except Exception as exc:
            emit_structured_error(
                logger,
                code=ErrorCode.AI_CLASSIFICATION_FAILED,
                message=str(exc),
                suppressed=True,
            )
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
        prior_attempts: list[AttemptRecord] | None = None,
    ) -> NavigationPlan:
        """Generate a navigation plan to resolve an obstruction.

        Returns structured function calls, not prose.
        """
        if not self.is_available:
            return NavigationPlan(actions=[], confidence=0.0)

        try:
            from vertexai.generative_models import GenerationConfig

            attempts_context = ""
            failed_selectors: list[str] = []
            if prior_attempts:
                lines = []
                for i, rec in enumerate(prior_attempts):
                    line = (
                        f"  {i + 1}. phase={rec.phase} action={rec.action} "
                        f"detail={rec.detail!r} outcome={rec.outcome}"
                    )
                    if rec.obstruction_type:
                        line += f" obstruction={rec.obstruction_type}"
                    lines.append(line)
                    if rec.action in ("click", "fill_form", "hover", "wait_for") and rec.detail:
                        failed_selectors.append(rec.detail)
                attempts_context = (
                    "\nPrior failed attempts (do NOT repeat these same strategies):\n"
                    + "\n".join(lines)
                    + "\n"
                )
                if failed_selectors:
                    attempts_context += (
                        "\nDo NOT use these selectors — they already failed:\n"
                        + "\n".join(f"  - {s}" for s in failed_selectors)
                        + "\n"
                    )

            prompt = (
                "You are an expert web automation agent. Your task is to generate a "
                "precise, minimal browser action plan to resolve a page obstruction.\n\n"
                f"Obstruction type: {obstruction_type}\n"
                f"Target extraction schema: {json.dumps(target_schema)}\n"
                f"{attempts_context}\n"
                "Permitted browser functions — use ONLY these, never others:\n"
                "  click(selector, wait_after_ms?) — click element by CSS selector\n"
                "  scroll(direction, amount) — direction: 'up'/'down'; "
                "amount: pixels, 'page', or 'end'\n"
                "  fill_form(selector, value) — type text into a form field\n"
                "  hover(selector) — hover over an element\n"
                "  press_key(key) — send a key: Escape, Enter, Tab, Space, etc.\n"
                "  wait_for(selector, timeout_ms?) — wait for element to appear in DOM\n"
                "  navigate_url(url) — navigate to URL (same-origin only)\n\n"
                "Selector guidance: prefer stable attributes — [data-*], [aria-label], "
                "[id], semantic tags (<button>, <input>). Avoid short dynamically "
                "generated class names like .cls-abc123.\n\n"
                "Return JSON: {actions: [{function, parameters, expected_outcome}], "
                "estimated_steps: int, confidence: float 0-1}.\n\n"
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
        except Exception as exc:
            emit_structured_error(
                logger,
                code=ErrorCode.AI_PLAN_GENERATION_FAILED,
                message=str(exc),
                suppressed=True,
            )
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
                "You are an expert data extraction specialist. Extract structured "
                "records from the HTML below, strictly following the provided schema.\n\n"
                f"Schema: {json.dumps(schema)}\n"
                f"Source URL: {source_url}\n\n"
                "Extraction rules:\n"
                "  1. Return one record per distinct entity found in the page.\n"
                "  2. Match schema field types exactly: numbers as JSON numbers (not "
                "strings), dates as ISO-8601 strings (YYYY-MM-DD), booleans as "
                "true/false.\n"
                "  3. For optional schema fields absent from the page, use null — "
                "never an empty string.\n"
                "  4. If two records share identical values for all fields, count only "
                "one and increment duplicates_detected.\n"
                "  5. Set completeness_score to the fraction of schema fields that are "
                "non-null across all extracted records (0.0–1.0).\n\n"
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
        except Exception as exc:
            emit_structured_error(
                logger,
                code=ErrorCode.AI_EXTRACTION_FAILED,
                message=str(exc),
                suppressed=True,
            )
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

            # Build a human-readable diagnosis of what went wrong
            issues: list[str] = []
            records_list = partial_data.get("records", [])
            if not records_list:
                issues.append("no records were extracted at all")
            else:
                schema_fields = set(schema.keys()) if isinstance(schema, dict) else set()
                for idx, rec in enumerate(records_list):
                    rec_fields = set(rec.keys()) if isinstance(rec, dict) else set()
                    missing = schema_fields - rec_fields
                    if missing:
                        issues.append(f"record {idx}: missing fields {sorted(missing)}")
                    low_conf = [
                        k
                        for k, v in rec.items()
                        if isinstance(v, dict) and v.get("confidence", 1.0) < 0.5
                    ]
                    if low_conf:
                        issues.append(f"record {idx}: low-confidence fields {low_conf}")
            issues_text = (
                "\n".join(f"  - {issue}" for issue in issues)
                if issues
                else "  - completeness_score is below threshold"
            )

            prompt = (
                "You are an expert data extraction repair specialist. The previous "
                "extraction attempt was incomplete or contained errors. "
                "Your task is to repair it.\n\n"
                "What went wrong:\n"
                f"{issues_text}\n\n"
                f"Partial extraction data:\n{json.dumps(partial_data)}\n\n"
                f"Target schema:\n{json.dumps(schema)}\n\n"
                "Repair rules:\n"
                "  1. Output only records that improve upon the partial data.\n"
                "  2. For any field already present with confidence >= 0.5, preserve it.\n"
                "  3. Fill missing fields by locating them in the HTML below.\n"
                "  4. Match schema field types: numbers as JSON numbers, dates as "
                "ISO-8601 strings, missing optional fields as null.\n"
                "  5. Set completeness_score to the fraction of schema fields now "
                "non-null.\n\n"
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
        except Exception as exc:
            emit_structured_error(
                logger,
                code=ErrorCode.AI_REPAIR_FAILED,
                message=str(exc),
                suppressed=True,
            )
            return ExtractionResult()
