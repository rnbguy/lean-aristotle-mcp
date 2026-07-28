"""Translation of expected SDK and local failures to MCP results."""

from __future__ import annotations

import logging
import tarfile
from typing import Literal

from aristotlelib import AristotleAPIError
from aristotlelib.local_file_utils import LeanProjectError

from aristotle_mcp.models import ErrorResult

ErrorType = Literal["validation", "api", "filesystem", "archive"]
_logger = logging.getLogger(__name__)


def _sanitize_api_error(error: AristotleAPIError) -> str:
    """Return a safe client message while retaining full server-side details."""
    _logger.exception("API error occurred", exc_info=error)
    error_message = str(error)
    error_str = error_message.lower()
    if "timeout" in error_str or "timed out" in error_str:
        return "Request timed out. Please try again."
    if "connection" in error_str or "network" in error_str:
        return "Connection error. Please check your network and try again."
    if "unauthorized" in error_str or "authentication" in error_str:
        return "Authentication failed. Please check your API key."
    if "rate limit" in error_str or "too many" in error_str:
        return "Rate limit exceeded. Please wait before retrying."
    if "not found" in error_str:
        return "Resource not found."
    if "counterexample" in error_str:
        return "Counterexample found."
    return "An error occurred while processing your request."


def error_result(
    error: AristotleAPIError | LeanProjectError | OSError | tarfile.TarError | ValueError,
) -> ErrorResult:
    """Convert an expected boundary failure to the wire error shape."""
    error_type: ErrorType = "validation"
    match error:
        case AristotleAPIError():
            error_type = "api"
        case LeanProjectError():
            error_type = "validation"
        case tarfile.TarError():
            error_type = "archive"
        case OSError():
            error_type = "filesystem"
        case ValueError():
            error_type = "validation"
    message = _sanitize_api_error(error) if isinstance(error, AristotleAPIError) else str(error)
    return ErrorResult("error", error_type, message)
