"""Heuristic obstruction detection — DOM pattern matching without AI.

The Conduit uses these heuristics as a first pass before invoking the AI Engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ObstructionType(str, Enum):
    CONSENT_GATE = "CONSENT_GATE"
    CONTENT_REVEAL = "CONTENT_REVEAL"
    MULTI_CLICK_FLOW = "MULTI_CLICK_FLOW"
    DYNAMIC_LOAD = "DYNAMIC_LOAD"
    JS_ROUTING = "JS_ROUTING"
    BEHAVIORAL_PUZZLE = "BEHAVIORAL_PUZZLE"
    HARD_BLOCK = "HARD_BLOCK"
    NONE = "NONE"


@dataclass
class ObstructionResult:
    """Result of obstruction detection."""

    obstruction_type: ObstructionType
    confidence: float
    selector: str | None = None
    requires_ai: bool = False


# Known cookie/consent banner selectors (common patterns)
CONSENT_SELECTORS = [
    # Common consent management platforms
    "#onetrust-accept-btn-handler",
    ".onetrust-accept-btn-handler",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    '[id*="cookie"] [class*="accept"]',
    '[id*="cookie"] [class*="agree"]',
    '[id*="consent"] [class*="accept"]',
    '[id*="consent"] [class*="agree"]',
    '[class*="cookie-banner"] button',
    '[class*="cookie-consent"] button',
    '[class*="gdpr"] [class*="accept"]',
    'button[class*="accept-cookie"]',
    'button[class*="cookie-accept"]',
    'a[class*="accept-cookie"]',
    # Generic patterns
    '[aria-label*="accept" i][aria-label*="cookie" i]',
    '[aria-label*="consent" i]',
]

# Selectors that indicate hard blocks
HARD_BLOCK_INDICATORS = [
    '[class*="captcha"]',
    '[id*="captcha"]',
    'iframe[src*="recaptcha"]',
    'iframe[src*="hcaptcha"]',
    '[class*="login-wall"]',
    '[class*="paywall"]',
    '[id*="login-gate"]',
]

# Selectors for content reveal patterns
CONTENT_REVEAL_SELECTORS = [
    '[class*="read-more"]',
    '[class*="show-more"]',
    '[class*="expand"]',
    'button[class*="accordion"]',
    '[data-toggle="collapse"]',
    "details > summary",
]


def _selector_to_html_pattern(selector: str) -> str:
    """Normalize a CSS selector to a substring that can be found in raw HTML.

    Handles:
    - #id            -> id="id"
    - .class          -> class="class" (partial, for substring matching)
    - [attr*="val"]  -> val
    - other selectors -> strip brackets and split on *=
    """
    s = selector.lower().strip()
    if s.startswith("#"):
        return f'id="{s[1:]}"'
    if s.startswith("."):
        return s[1:]  # class name will appear as-is inside class="..."
    # Attribute selector: strip [] and extract value after *=
    return s.strip("[]").split("*=")[-1].strip('"').strip("'")


def detect_obstruction(html: str) -> ObstructionResult:
    """Detect obstructions using DOM heuristic patterns.

    This is the first-pass detection. If it fails to classify,
    the Conduit will escalate to the AI Engine.
    """
    html_lower = html.lower()

    # Check for hard blocks first (highest priority)
    for indicator in HARD_BLOCK_INDICATORS:
        clean_indicator = _selector_to_html_pattern(indicator)
        if clean_indicator in html_lower:
            return ObstructionResult(
                obstruction_type=ObstructionType.HARD_BLOCK,
                confidence=0.8,
                requires_ai=False,
            )

    # Check for consent gates
    for selector in CONSENT_SELECTORS:
        # Simple substring matching on known patterns
        clean_selector = _selector_to_html_pattern(selector)
        if clean_selector in html_lower:
            return ObstructionResult(
                obstruction_type=ObstructionType.CONSENT_GATE,
                confidence=0.7,
                selector=selector,
                requires_ai=False,
            )

    # Check for content reveal patterns
    for selector in CONTENT_REVEAL_SELECTORS:
        clean_selector = _selector_to_html_pattern(selector)
        if clean_selector in html_lower:
            return ObstructionResult(
                obstruction_type=ObstructionType.CONTENT_REVEAL,
                confidence=0.6,
                selector=selector,
                requires_ai=True,  # May need AI to determine which to click
            )

    return ObstructionResult(
        obstruction_type=ObstructionType.NONE,
        confidence=1.0,
    )
