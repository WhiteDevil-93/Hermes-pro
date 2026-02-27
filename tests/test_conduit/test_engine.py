"""Tests for the Conduit engine — phase transitions and state machine integrity."""

from server.ai_engine.engine import (
    ALL_ALLOWED_FUNCTIONS,
    FunctionCall,
    validate_function_call,
)
from server.browser.obstruction import ObstructionType, detect_obstruction
from server.config.settings import HermesConfig


class TestFunctionCallValidation:
    """Test the trust boundary: AI function call validation."""

    def test_valid_click(self):
        call = FunctionCall(function="click", parameters={"selector": "#btn"})
        assert validate_function_call(call) is None

    def test_click_missing_selector(self):
        call = FunctionCall(function="click", parameters={})
        error = validate_function_call(call)
        assert error is not None
        assert "selector" in error

    def test_valid_scroll(self):
        call = FunctionCall(function="scroll", parameters={"direction": "down", "amount": "page"})
        assert validate_function_call(call) is None

    def test_scroll_invalid_direction(self):
        call = FunctionCall(function="scroll", parameters={"direction": "left", "amount": "page"})
        error = validate_function_call(call)
        assert error is not None

    def test_valid_fill_form(self):
        call = FunctionCall(
            function="fill_form",
            parameters={"selector": "#search", "value": "query"},
        )
        assert validate_function_call(call) is None

    def test_fill_form_missing_value(self):
        call = FunctionCall(function="fill_form", parameters={"selector": "#search"})
        error = validate_function_call(call)
        assert error is not None

    def test_unknown_function_rejected(self):
        call = FunctionCall(function="execute_js", parameters={"code": "alert(1)"})
        error = validate_function_call(call)
        assert error is not None
        assert "Unknown" in error

    def test_navigate_url_requires_url(self):
        call = FunctionCall(function="navigate_url", parameters={})
        error = validate_function_call(call)
        assert error is not None

    def test_valid_navigate_url(self):
        call = FunctionCall(
            function="navigate_url",
            parameters={"url": "https://example.com/page2"},
        )
        assert validate_function_call(call) is None

    def test_all_navigation_functions_in_allowlist(self):
        nav_functions = {
            "click",
            "scroll",
            "fill_form",
            "hover",
            "press_key",
            "wait_for",
            "navigate_url",
        }
        assert nav_functions.issubset(ALL_ALLOWED_FUNCTIONS)

    def test_all_extraction_functions_in_allowlist(self):
        ext_functions = {
            "extract_structured",
            "repair_extraction",
            "deduplicate",
            "convert_prose_to_fields",
        }
        assert ext_functions.issubset(ALL_ALLOWED_FUNCTIONS)


class TestObstructionDetection:
    """Test heuristic obstruction detection."""

    def test_no_obstruction_on_clean_html(self):
        html = "<html><body><h1>Hello World</h1><p>Content here</p></body></html>"
        result = detect_obstruction(html)
        assert result.obstruction_type == ObstructionType.NONE

    def test_detects_cookie_banner(self):
        html = (
            '<html><body><div id="cookie-consent">'
            '<button class="accept">Accept</button>'
            "</div></body></html>"
        )
        result = detect_obstruction(html)
        assert result.obstruction_type == ObstructionType.CONSENT_GATE

    def test_detects_captcha(self):
        html = (
            '<html><body><div class="captcha-container">'
            '<iframe src="https://recaptcha.example.com">'
            "</iframe></div></body></html>"
        )
        result = detect_obstruction(html)
        assert result.obstruction_type == ObstructionType.HARD_BLOCK

    def test_detects_content_reveal(self):
        html = (
            '<html><body><button class="read-more">Read More</button><p>Content</p></body></html>'
        )
        result = detect_obstruction(html)
        assert result.obstruction_type == ObstructionType.CONTENT_REVEAL

    def test_hard_block_has_highest_priority(self):
        html = (
            '<html><body><div class="captcha"></div>'
            '<div class="cookie-consent"></div></body></html>'
        )
        result = detect_obstruction(html)
        assert result.obstruction_type == ObstructionType.HARD_BLOCK


class TestURLPolicyInEngine:
    """Test URL policy enforcement for function call navigation."""

    def test_navigate_url_loopback_blocked(self):
        from server.config.settings import URLPolicyConfig
        from server.config.url_policy import validate_target_url

        result = validate_target_url("http://127.0.0.1:9200", URLPolicyConfig())
        assert not result.allowed

    def test_navigate_url_private_blocked(self):
        from server.config.settings import URLPolicyConfig
        from server.config.url_policy import validate_target_url

        result = validate_target_url("http://10.0.0.1/admin", URLPolicyConfig())
        assert not result.allowed

    def test_navigate_url_file_scheme_blocked(self):
        from server.config.settings import URLPolicyConfig
        from server.config.url_policy import validate_target_url

        result = validate_target_url("file:///etc/shadow", URLPolicyConfig())
        assert not result.allowed


class TestHermesConfig:
    """Test configuration validation."""

    def test_minimal_config(self):
        config = HermesConfig(target_url="https://example.com")
        assert config.target_url == "https://example.com"
        assert config.extraction_mode == "heuristic"

    def test_full_config(self):
        config = HermesConfig(
            target_url="https://example.com",
            extraction_mode="hybrid",
            heuristic_selectors={"title": "h1", "content": ".main-content"},
            allow_cross_origin=False,
            retry={"max_retries": 5},
            timeouts={"global_timeout_s": 600},
        )
        assert config.retry.max_retries == 5
        assert config.timeouts.global_timeout_s == 600
        assert len(config.heuristic_selectors) == 2

    def test_config_includes_security_models(self):
        config = HermesConfig(target_url="https://example.com")
        assert hasattr(config, "auth")
        assert hasattr(config, "url_policy")
        assert hasattr(config, "retention")
        assert config.auth.require_auth is False
        assert "http" in config.url_policy.allowed_schemes
        assert config.retention.max_completed_runs == 100
