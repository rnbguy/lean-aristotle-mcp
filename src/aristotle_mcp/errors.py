"""Translation of expected SDK and local failures to MCP results."""

from __future__ import annotations

import tarfile
from typing import Literal

from aristotlelib import AristotleAPIError
from aristotlelib.local_file_utils import LeanProjectError

from aristotle_mcp.models import ErrorResult

ErrorType = Literal["validation", "api", "filesystem", "archive"]


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
    return ErrorResult("error", error_type, str(error))
