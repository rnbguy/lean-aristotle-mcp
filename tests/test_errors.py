"""Tests for expected error translation."""

import pytest
from aristotlelib import AristotleAPIError

from aristotle_mcp.errors import error_result


@pytest.mark.parametrize(
    ("detail", "message"),
    [
        ("request timeout", "Request timed out. Please try again."),
        ("connection refused", "Connection error. Please check your network and try again."),
        ("authentication failed", "Authentication failed. Please check your API key."),
        ("rate limit exceeded", "Rate limit exceeded. Please wait before retrying."),
        ("resource not found", "Resource not found."),
    ],
)
def test_api_errors_use_historical_safe_messages(detail: str, message: str) -> None:
    result = error_result(AristotleAPIError(detail))

    assert result.error_type == "api"
    assert result.message == message


def test_counterexample_api_error_hides_backend_detail() -> None:
    detail = "counterexample; backend-internal-detail"

    result = error_result(AristotleAPIError(detail))

    assert result.message == "Counterexample found."
    assert "backend-internal-detail" not in result.message


def test_unknown_api_error_hides_backend_detail() -> None:
    result = error_result(AristotleAPIError("private database hostname"))

    assert result.message == "An error occurred while processing your request."
    assert "private database hostname" not in result.message


def test_non_api_error_preserves_message() -> None:
    result = error_result(ValueError("invalid input"))

    assert result.error_type == "validation"
    assert result.message == "invalid input"
