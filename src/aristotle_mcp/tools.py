"""Tool implementations for the Aristotle MCP server."""

from __future__ import annotations

import logging
import os
import shutil
import tarfile
import tempfile
import threading
import time
from typing import TYPE_CHECKING

from dotenv import load_dotenv

from aristotle_mcp.mock import (
    mock_cancel_project,
    mock_check_formalize,
    mock_check_proof,
    mock_check_prove_file,
    mock_formalize,
    mock_get_input,
    mock_get_project,
    mock_get_solution,
    mock_get_solution_if_complete,
    mock_prove,
    mock_prove_file,
)
from aristotle_mcp.models import (
    FormalizeResult,
    ProjectFileResult,
    ProjectResult,
    ProveFileResult,
    ProveResult,
    ResultDict,
    ResultValue,
)

if TYPE_CHECKING:
    from aristotlelib import Project

# Configure module logger
_logger = logging.getLogger(__name__)

# Re-export types for backwards compatibility
__all__ = [
    "ResultDict",
    "ResultValue",
    "ProveResult",
    "ProveFileResult",
    "FormalizeResult",
    "ProjectResult",
    "ProjectFileResult",
    "is_mock_mode",
    "has_api_key",
    "prove",
    "check_proof",
    "prove_file",
    "check_prove_file",
    "formalize",
    "check_formalize",
    "get_project",
    "cancel_project",
    "get_solution",
    "get_solution_if_complete",
    "get_input",
]


# Track whether .env has been loaded
_dotenv_loaded = False

# Thread lock for accessing shared state
_metadata_lock = threading.Lock()

# Metadata store for async proof jobs (persists across polls within server lifetime)
# Maps project_id -> metadata dict with timestamp for cleanup
# Access must be protected by _metadata_lock
_async_job_metadata: dict[str, dict[str, str | int | float]] = {}

# Cleanup jobs older than 30 days (memory impact is negligible)
_METADATA_TTL_SECONDS = 30 * 24 * 60 * 60  # 2,592,000 seconds

# Input size limits (defense-in-depth)
_MAX_CODE_SIZE = 1_000_000  # 1MB for code input
_MAX_DESCRIPTION_SIZE = 100_000  # 100KB for natural language descriptions
_MAX_FILE_SIZE = 10_000_000  # 10MB for file inputs

_CANCELABLE_PROJECT_STATUSES = {"NOT_STARTED", "QUEUED", "IN_PROGRESS"}
_SOLUTION_AVAILABLE_STATUSES = {"COMPLETE", "COMPLETE_WITH_ERRORS", "OUT_OF_BUDGET"}
_TERMINAL_PROJECT_STATUSES = _SOLUTION_AVAILABLE_STATUSES | {"FAILED", "CANCELED"}

# Helpful error message for missing API key
_API_KEY_ERROR = (
    "ARISTOTLE_API_KEY environment variable not set. "
    "Get your API key at https://aristotle.harmonic.fun/ and set it with: "
    "export ARISTOTLE_API_KEY=your-key-here. "
    "For testing without an API key, set ARISTOTLE_MOCK=true."
)


def _find_unique_path(path: str, max_attempts: int = 1000) -> str:
    """Find a unique path by adding a number suffix if the file exists.

    Uses atomic file creation to avoid TOCTOU race conditions.

    Example: foo_aristotle.lean -> foo_aristotle.1.lean -> foo_aristotle.2.lean

    Args:
        path: The base path to check
        max_attempts: Maximum number of suffixes to try before raising

    Returns:
        A path that was atomically created (empty file)

    Raises:
        RuntimeError: If no unique path found within max_attempts
    """
    # Try the original path first, then numbered variants
    candidates = [path] + [
        f"{os.path.splitext(path)[0]}.{i}{os.path.splitext(path)[1]}"
        for i in range(1, max_attempts + 1)
    ]

    for candidate in candidates:
        try:
            # O_CREAT | O_EXCL atomically creates file only if it doesn't exist
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)
            return candidate
        except FileExistsError:
            continue

    raise RuntimeError(f"Could not find unique path after {max_attempts} attempts: {path}")


def _safe_project_filename(project_id: str, suffix: str) -> str:
    """Create a safe local filename from an Aristotle project ID."""
    safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in project_id)
    if not safe_id:
        safe_id = "project"
    return f"{safe_id}{suffix}"


def _reserve_download_path(
    project_id: str,
    output_path: str | None,
    default_suffix: str,
    overwrite: bool,
) -> tuple[str, bool]:
    """Resolve and reserve a download path before passing it to aristotlelib.

    Returns:
        Tuple of (absolute path, whether this function created a placeholder).
    """
    if output_path is None:
        default_path = _canonicalize_path(_safe_project_filename(project_id, default_suffix))
        os.makedirs(os.path.dirname(default_path) or ".", exist_ok=True)
        return _find_unique_path(default_path), True

    absolute_path = _canonicalize_path(output_path)
    os.makedirs(os.path.dirname(absolute_path) or ".", exist_ok=True)

    if overwrite:
        return absolute_path, False

    fd = os.open(absolute_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    os.close(fd)
    return absolute_path, True


def _remove_reserved_path(path: str, reserved: bool) -> None:
    """Remove an empty placeholder file if a reserved download fails."""
    if not reserved or not os.path.exists(path):
        return
    try:
        if os.path.getsize(path) == 0:
            os.unlink(path)
    except OSError:
        _logger.debug("Could not remove reserved download path: %s", path, exc_info=True)


def _validate_archive_member(member_name: str, extract_dir: str) -> None:
    """Ensure an archive member cannot escape the extraction directory."""
    destination = os.path.realpath(os.path.join(extract_dir, member_name))
    extract_root = os.path.realpath(extract_dir)
    if os.path.commonpath([extract_root, destination]) != extract_root:
        raise ValueError(f"Unsafe path in solution archive: {member_name}")


def _extract_solution_archive(solution_path: str, extract_dir: str) -> None:
    """Extract an Aristotle solution archive into a temporary directory."""
    with tarfile.open(solution_path, "r:gz") as tar:
        for member in tar.getmembers():
            _validate_archive_member(member.name, extract_dir)
        if hasattr(tarfile, "data_filter"):
            tar.extractall(extract_dir, filter="data")
        else:
            tar.extractall(extract_dir)


def _find_lean_file(extract_dir: str, preferred_filename: str | None = None) -> str | None:
    """Find the preferred Lean file from an extracted solution archive."""
    if preferred_filename:
        preferred_path = os.path.join(extract_dir, preferred_filename)
        if os.path.exists(preferred_path):
            return preferred_path

        for root, dirs, files in os.walk(extract_dir):
            dirs.sort()
            for filename in sorted(files):
                if filename == preferred_filename:
                    return os.path.join(root, filename)

    for root, dirs, files in os.walk(extract_dir):
        dirs.sort()
        for filename in sorted(files):
            if filename.endswith(".lean"):
                return os.path.join(root, filename)

    return None


def _read_lean_from_solution_archive(
    solution_path: str,
    preferred_filename: str | None = None,
) -> str | None:
    """Read Lean code from an Aristotle solution archive."""
    extract_dir = tempfile.mkdtemp()
    try:
        _extract_solution_archive(solution_path, extract_dir)
        lean_path = _find_lean_file(extract_dir, preferred_filename)
        if lean_path is None:
            return None
        with open(lean_path) as f:
            return f.read()
    finally:
        shutil.rmtree(extract_dir)


def _copy_lean_from_solution_archive(
    solution_path: str,
    output_path: str,
    preferred_filename: str | None = None,
) -> bool:
    """Copy Lean code from an Aristotle solution archive to output_path."""
    extract_dir = tempfile.mkdtemp()
    try:
        _extract_solution_archive(solution_path, extract_dir)
        lean_path = _find_lean_file(extract_dir, preferred_filename)
        if lean_path is None:
            return False
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        shutil.copy2(lean_path, output_path)
        return True
    finally:
        shutil.rmtree(extract_dir)


def _duplicate_context_basename_error(
    context_files: list[str],
    reserved_filenames: set[str],
) -> str | None:
    """Return an error if context files would collide in the submission directory."""
    seen = set(reserved_filenames)
    for ctx_file in context_files:
        filename = os.path.basename(ctx_file)
        if filename in seen:
            return f"Context file basename would overwrite another input file: {filename}"
        seen.add(filename)
    return None


def _ensure_dotenv() -> None:
    """Load .env file if not already loaded."""
    global _dotenv_loaded
    if not _dotenv_loaded:
        load_dotenv()
        _dotenv_loaded = True


def _cleanup_stale_metadata() -> None:
    """Remove metadata entries older than TTL to prevent memory leaks.

    Thread-safe: acquires _metadata_lock.
    """
    now = time.time()
    with _metadata_lock:
        stale_ids = [
            pid for pid, meta in _async_job_metadata.items()
            if now - float(meta.get("timestamp", 0)) > _METADATA_TTL_SECONDS
        ]
        for pid in stale_ids:
            _async_job_metadata.pop(pid, None)


def _canonicalize_path(path: str) -> str:
    """Canonicalize a file path to prevent path traversal issues.

    Resolves symlinks, removes . and .. components, and returns absolute path.

    Args:
        path: The path to canonicalize

    Returns:
        Canonicalized absolute path
    """
    return os.path.realpath(os.path.abspath(path))


def _sanitize_api_error(error: Exception) -> str:
    """Sanitize an API error for safe return to clients.

    Logs the full error for debugging but returns a generic message
    to avoid leaking internal details.

    Args:
        error: The exception to sanitize

    Returns:
        A safe error message for the client
    """
    # Log full error for debugging
    _logger.exception("API error occurred")

    error_str = str(error).lower()

    # Return specific messages for known error types
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
        # This is actually useful information, pass it through
        return str(error)

    # Generic fallback
    return "An error occurred while processing your request."


def _map_api_status(status_str: str, percent_complete: int | None) -> tuple[str, str]:
    """Map aristotlelib API status to our status and message.

    Args:
        status_str: Status string from the API (e.g., "COMPLETE", "QUEUED")
        percent_complete: Percent complete from the API

    Returns:
        Tuple of (status, message) for our result types
    """
    pct = percent_complete or 0

    if status_str == "COMPLETE":
        return "complete", "Proof completed"
    elif status_str == "COMPLETE_WITH_ERRORS":
        return "complete", "Proof completed with errors"
    elif status_str == "OUT_OF_BUDGET":
        return "failed", "Proof ran out of budget"
    elif status_str == "CANCELED":
        return "failed", "Proof was canceled"
    elif status_str in ("QUEUED", "NOT_STARTED"):
        return "queued", "Proof is queued, waiting to start"
    elif status_str == "IN_PROGRESS":
        return "in_progress", f"Proof is being computed ({pct}% complete)"
    elif status_str == "PENDING_RETRY":
        return "in_progress", "Proof is pending retry"
    elif status_str == "FAILED":
        return "failed", "Proof failed"
    else:
        return "in_progress", f"Status: {status_str}"


def _map_project_status(status_str: str) -> str:
    """Map aristotlelib project status to a stable MCP status string."""
    status_map = {
        "UNKNOWN": "unknown",
        "NOT_STARTED": "not_started",
        "QUEUED": "queued",
        "IN_PROGRESS": "in_progress",
        "COMPLETE": "complete",
        "COMPLETE_WITH_ERRORS": "complete_with_errors",
        "OUT_OF_BUDGET": "out_of_budget",
        "FAILED": "failed",
        "CANCELED": "canceled",
    }
    return status_map.get(status_str, status_str.lower())


def _project_status_name(project: Project) -> str:
    """Return the raw aristotlelib status name for a project."""
    return project.status.name


def _project_to_result(
    project: Project,
    message: str | None = None,
    status_override: str | None = None,
) -> ProjectResult:
    """Convert an aristotlelib Project into an MCP project result."""
    raw_status = _project_status_name(project)
    status = status_override or _map_project_status(raw_status)
    result_message = message or f"Project status: {status}"

    return ProjectResult(
        status=status,
        project_id=str(project.project_id),
        raw_status=raw_status,
        percent_complete=project.percent_complete,
        created_at=project.created_at.isoformat(),
        last_updated_at=project.last_updated_at.isoformat(),
        input_prompt=project.input_prompt,
        file_name=project.file_name,
        description=project.description,
        output_summary=project.output_summary,
        message=result_message,
    )


async def _download_solution_from_project(
    project: Project,
    output_path: str | None,
    overwrite: bool,
) -> ProjectFileResult:
    """Download a solution archive for a project with overwrite protection."""
    project_id = str(project.project_id)
    raw_status = _project_status_name(project)
    reserved_path, reserved = _reserve_download_path(
        project_id=project_id,
        output_path=output_path,
        default_suffix="_aristotle.tar.gz",
        overwrite=overwrite,
    )

    try:
        saved_path = await project.get_solution(destination=reserved_path)
    except Exception:
        _remove_reserved_path(reserved_path, reserved)
        raise

    return ProjectFileResult(
        status="saved",
        project_id=project_id,
        output_path=os.path.abspath(str(saved_path)),
        raw_status=raw_status,
        percent_complete=project.percent_complete,
        message="Solution archive downloaded.",
    )


async def _download_input_from_project(
    project: Project,
    output_path: str | None,
    overwrite: bool,
) -> ProjectFileResult:
    """Download an input archive for a project with overwrite protection."""
    project_id = str(project.project_id)
    raw_status = _project_status_name(project)
    reserved_path, reserved = _reserve_download_path(
        project_id=project_id,
        output_path=output_path,
        default_suffix="_input.tar.gz",
        overwrite=overwrite,
    )

    try:
        saved_path = await project.get_input(destination=reserved_path)
    except Exception:
        _remove_reserved_path(reserved_path, reserved)
        raise

    return ProjectFileResult(
        status="saved",
        project_id=project_id,
        output_path=os.path.abspath(str(saved_path)),
        raw_status=raw_status,
        percent_complete=project.percent_complete,
        message="Input archive downloaded.",
    )


def _analyze_solution_file(
    solution_path: str,
    project_id: str | None = None,
) -> ProveFileResult:
    """Analyze a completed solution file and return the appropriate result.

    Args:
        solution_path: Path to the solution file
        project_id: Optional project ID to include in result

    Returns:
        ProveFileResult with status based on whether solution was generated
    """
    absolute_path = os.path.abspath(solution_path)

    if not os.path.exists(absolute_path):
        return ProveFileResult(
            status="failed",
            project_id=project_id,
            percent_complete=100,
            message="Completed but solution file not found",
        )

    return ProveFileResult(
        status="proved",
        output_path=absolute_path,
        project_id=project_id,
        percent_complete=100,
        message="Proof completed successfully",
    )


def is_mock_mode() -> bool:
    """Check if we're running in mock mode."""
    _ensure_dotenv()
    return os.environ.get("ARISTOTLE_MOCK", "").lower() in ("true", "1", "yes")


def has_api_key() -> bool:
    """Check if an API key is configured."""
    _ensure_dotenv()
    return bool(os.environ.get("ARISTOTLE_API_KEY"))


async def get_project(project_id: str) -> ProjectResult:
    """Get current metadata for a single Aristotle project.

    Args:
        project_id: The Aristotle project ID to inspect.

    Returns:
        ProjectResult with status, timestamps, prompt, and summary fields when available.
    """
    if not project_id.strip():
        return ProjectResult(
            status="error",
            project_id=project_id,
            message="project_id is required.",
        )

    if is_mock_mode():
        return mock_get_project(project_id)

    if not has_api_key():
        return ProjectResult(status="error", project_id=project_id, message=_API_KEY_ERROR)

    try:
        from aristotlelib import Project

        project = await Project.from_id(project_id)
        return _project_to_result(project)
    except Exception as e:
        return ProjectResult(
            status="error",
            project_id=project_id,
            message=_sanitize_api_error(e),
        )


async def cancel_project(project_id: str) -> ProjectResult:
    """Cancel a queued or in-progress Aristotle project.

    Args:
        project_id: The Aristotle project ID to cancel.

    Returns:
        ProjectResult with the resulting project status.
    """
    if not project_id.strip():
        return ProjectResult(
            status="error",
            project_id=project_id,
            message="project_id is required.",
        )

    if is_mock_mode():
        return mock_cancel_project(project_id)

    if not has_api_key():
        return ProjectResult(status="error", project_id=project_id, message=_API_KEY_ERROR)

    try:
        from aristotlelib import Project

        project = await Project.from_id(project_id)
        raw_status = _project_status_name(project)

        if raw_status in _TERMINAL_PROJECT_STATUSES:
            status = _map_project_status(raw_status)
            return _project_to_result(
                project,
                message=f"Project is already {status}; nothing to cancel.",
            )

        if raw_status not in _CANCELABLE_PROJECT_STATUSES:
            return _project_to_result(
                project,
                message=f"Project status {raw_status} cannot be canceled.",
            )

        await project.cancel()
        return _project_to_result(project, message="Project canceled.")
    except Exception as e:
        return ProjectResult(
            status="error",
            project_id=project_id,
            message=_sanitize_api_error(e),
        )


async def get_solution(
    project_id: str,
    output_path: str | None = None,
    overwrite: bool = False,
) -> ProjectFileResult:
    """Download a completed project's solution archive.

    Args:
        project_id: The Aristotle project ID.
        output_path: Optional local path for the solution archive.
        overwrite: Whether to overwrite output_path if it already exists.

    Returns:
        ProjectFileResult with output_path when the archive is saved.
    """
    if not project_id.strip():
        return ProjectFileResult(
            status="error",
            project_id=project_id,
            message="project_id is required.",
        )

    if is_mock_mode():
        return mock_get_solution(project_id, output_path=output_path, overwrite=overwrite)

    if not has_api_key():
        return ProjectFileResult(status="error", project_id=project_id, message=_API_KEY_ERROR)

    try:
        from aristotlelib import Project

        project = await Project.from_id(project_id)
        raw_status = _project_status_name(project)

        if raw_status not in _SOLUTION_AVAILABLE_STATUSES:
            return ProjectFileResult(
                status=_map_project_status(raw_status),
                project_id=project_id,
                raw_status=raw_status,
                percent_complete=project.percent_complete,
                message="Project does not have a downloadable solution archive.",
            )

        return await _download_solution_from_project(project, output_path, overwrite)
    except FileExistsError:
        return ProjectFileResult(
            status="error",
            project_id=project_id,
            message="Output file already exists. Pass overwrite=True to replace it.",
        )
    except Exception as e:
        return ProjectFileResult(
            status="error",
            project_id=project_id,
            message=_sanitize_api_error(e),
        )


async def get_solution_if_complete(
    project_id: str,
    output_path: str | None = None,
    overwrite: bool = False,
) -> ProjectFileResult:
    """Download a project solution archive only when Aristotle has output available.

    Args:
        project_id: The Aristotle project ID.
        output_path: Optional local path for the solution archive.
        overwrite: Whether to overwrite output_path if it already exists.

    Returns:
        ProjectFileResult with status indicating whether a file was saved.
    """
    if not project_id.strip():
        return ProjectFileResult(
            status="error",
            project_id=project_id,
            message="project_id is required.",
        )

    if is_mock_mode():
        return mock_get_solution_if_complete(
            project_id,
            output_path=output_path,
            overwrite=overwrite,
        )

    if not has_api_key():
        return ProjectFileResult(status="error", project_id=project_id, message=_API_KEY_ERROR)

    try:
        from aristotlelib import Project

        project = await Project.from_id(project_id)
        raw_status = _project_status_name(project)

        if raw_status not in _SOLUTION_AVAILABLE_STATUSES:
            return ProjectFileResult(
                status=_map_project_status(raw_status),
                project_id=project_id,
                raw_status=raw_status,
                percent_complete=project.percent_complete,
                message="Project is not complete; no solution archive was downloaded.",
            )

        return await _download_solution_from_project(project, output_path, overwrite)
    except FileExistsError:
        return ProjectFileResult(
            status="error",
            project_id=project_id,
            message="Output file already exists. Pass overwrite=True to replace it.",
        )
    except Exception as e:
        return ProjectFileResult(
            status="error",
            project_id=project_id,
            message=_sanitize_api_error(e),
        )


async def get_input(
    project_id: str,
    output_path: str | None = None,
    overwrite: bool = False,
) -> ProjectFileResult:
    """Download the original input archive for an Aristotle project.

    Args:
        project_id: The Aristotle project ID.
        output_path: Optional local path for the input archive.
        overwrite: Whether to overwrite output_path if it already exists.

    Returns:
        ProjectFileResult with output_path when the archive is saved.
    """
    if not project_id.strip():
        return ProjectFileResult(
            status="error",
            project_id=project_id,
            message="project_id is required.",
        )

    if is_mock_mode():
        return mock_get_input(project_id, output_path=output_path, overwrite=overwrite)

    if not has_api_key():
        return ProjectFileResult(status="error", project_id=project_id, message=_API_KEY_ERROR)

    try:
        from aristotlelib import Project

        project = await Project.from_id(project_id)
        return await _download_input_from_project(project, output_path, overwrite)
    except FileExistsError:
        return ProjectFileResult(
            status="error",
            project_id=project_id,
            message="Output file already exists. Pass overwrite=True to replace it.",
        )
    except Exception as e:
        return ProjectFileResult(
            status="error",
            project_id=project_id,
            message=_sanitize_api_error(e),
        )


async def prove(
    code: str,
    context_files: list[str] | None = None,
    hint: str | None = None,
    wait: bool = True,
) -> ProveResult:
    """Attempt to prove Lean code containing sorry statements.

    Args:
        code: Lean 4 code containing `sorry` statements
        context_files: Optional list of paths to Lean files to use as imports.
                       These files provide definitions and lemmas the proof can reference.
        hint: Optional natural language hint to guide the prover
        wait: If True, block until proof completes. If False, return immediately
              with a project_id that can be polled with check_proof.

    Returns:
        ProveResult with status and either filled code or counterexample.
        If wait=False, returns status="submitted" with project_id for polling.
    """
    # Validate input size
    if len(code) > _MAX_CODE_SIZE:
        return ProveResult(
            status="error",
            message=f"Code exceeds maximum size of {_MAX_CODE_SIZE} bytes.",
        )

    if is_mock_mode():
        return mock_prove(code, context_files, hint, wait=wait)

    # Real API implementation
    if not has_api_key():
        return ProveResult(status="error", message=_API_KEY_ERROR)

    # Validate and canonicalize context files before making API calls
    canonicalized_context: list[str] | None = None
    if context_files:
        canonicalized_context = []
        for ctx_file in context_files:
            canonical = _canonicalize_path(ctx_file)
            if not os.path.exists(canonical):
                return ProveResult(
                    status="error",
                    message=f"Context file not found: {ctx_file}",
                )
            canonicalized_context.append(canonical)

        basename_error = _duplicate_context_basename_error(
            canonicalized_context,
            reserved_filenames={"proof.lean"},
        )
        if basename_error:
            return ProveResult(status="error", message=basename_error)

    try:
        from aristotlelib import Project

        with tempfile.TemporaryDirectory() as temp_dir:
            code_filename = "proof.lean"
            code_path = os.path.join(temp_dir, code_filename)

            code_with_hint = f"-- Hint: {hint}\n{code}" if hint else code
            with open(code_path, "w") as f:
                f.write(code_with_hint)

            if canonicalized_context:
                for ctx_file in canonicalized_context:
                    shutil.copy2(ctx_file, os.path.join(temp_dir, os.path.basename(ctx_file)))

            project = await Project.create_from_directory(
                prompt="Please prove all sorry statements in the provided Lean code.",
                project_dir=temp_dir,
            )

            project_id = str(project.project_id)

            if not wait:
                return ProveResult(
                    status="submitted",
                    project_id=project_id,
                    message="Proof submitted. Use check_proof to poll for results.",
                )

            solution_path = await project.wait_for_completion()

            if solution_path and os.path.exists(solution_path):
                try:
                    solved_code = _read_lean_from_solution_archive(
                        str(solution_path),
                        preferred_filename=code_filename,
                    )
                    if solved_code is not None:
                        return ProveResult(
                            status="proved",
                            code=solved_code,
                            project_id=project_id,
                            message="Successfully proved",
                        )
                    return ProveResult(
                        status="failed",
                        project_id=project_id,
                        message="Solution file not found in archive",
                    )
                finally:
                    os.unlink(solution_path)
            else:
                await project.refresh()
                return ProveResult(
                    status="failed",
                    project_id=project_id,
                    message=f"Project status: {project.status}",
                )

    except Exception as e:
        error_msg = str(e)
        # Try to detect counterexamples in error messages
        if "counterexample" in error_msg.lower():
            return ProveResult(
                status="counterexample",
                counterexample=error_msg,
                message="Statement appears to be false",
            )
        return ProveResult(
            status="error",
            message=_sanitize_api_error(e),
        )


async def check_proof(project_id: str) -> ProveResult:
    """Poll for the status of a previously submitted proof.

    Args:
        project_id: The project ID returned from prove(wait=False)

    Returns:
        ProveResult with current status. If complete, includes the proof code.
    """
    if is_mock_mode():
        return mock_check_proof(project_id)

    if not has_api_key():
        return ProveResult(status="error", message=_API_KEY_ERROR)

    try:
        from aristotlelib import Project

        # Load existing project
        project = await Project.from_id(project_id)
        await project.refresh()

        # Get status name from enum (e.g., ProjectStatus.QUEUED -> "QUEUED")
        status_str = (
            project.status.name if hasattr(project.status, "name") else str(project.status).upper()
        )
        pct = project.percent_complete

        # Map API status to our status
        our_status, message = _map_api_status(status_str, pct)

        if our_status == "complete":
            # Get the solution
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as f:
                output_path = f.name

            try:
                solution_path = await project.get_solution(destination=output_path)
                if solution_path and os.path.exists(solution_path):
                    solved_code = _read_lean_from_solution_archive(
                        str(solution_path),
                        preferred_filename="proof.lean",
                    )
                    if solved_code is not None:
                        return ProveResult(
                            status="proved",
                            code=solved_code,
                            project_id=project_id,
                            percent_complete=100,
                            message="Proof completed successfully",
                        )
            finally:
                if os.path.exists(output_path):
                    os.unlink(output_path)

            return ProveResult(
                status="failed",
                project_id=project_id,
                percent_complete=pct,
                message="Completed but no solution available",
            )

        return ProveResult(
            status=our_status,
            project_id=project_id,
            percent_complete=pct if our_status != "queued" else 0,
            message=message,
        )

    except Exception as e:
        return ProveResult(
            status="error",
            project_id=project_id,
            message=_sanitize_api_error(e),
        )


async def prove_file(
    file_path: str,
    output_path: str | None = None,
    wait: bool = True,
) -> ProveFileResult:
    """Prove all sorry statements in a Lean file.

    Args:
        file_path: Path to Lean file with sorry statements
        output_path: Where to write solution (default: {file}_aristotle.lean)
        wait: If True (default), block until complete. If False, return immediately
              with a project_id that can be polled with check_prove_file.

    Returns:
        ProveFileResult with status and counts.
        If wait=False, returns status="submitted" with project_id for polling.
    """
    # Canonicalize path to prevent traversal issues
    canonical_path = _canonicalize_path(file_path)

    if not os.path.exists(canonical_path):
        return ProveFileResult(
            status="error",
            message=f"File not found: {file_path}",
        )

    # Check file size before reading
    file_size = os.path.getsize(canonical_path)
    if file_size > _MAX_FILE_SIZE:
        return ProveFileResult(
            status="error",
            message=f"File exceeds maximum size of {_MAX_FILE_SIZE} bytes.",
        )

    # Determine the actual output path (matches aristotlelib's default naming)
    actual_output_path: str
    if output_path is None:
        base, ext = os.path.splitext(canonical_path)
        actual_output_path = f"{base}_aristotle{ext}"
    else:
        actual_output_path = _canonicalize_path(output_path)

    # Atomically check if output would overwrite existing file
    try:
        fd = os.open(actual_output_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.close(fd)
        # File created successfully, remove it so API can create it
        os.unlink(actual_output_path)
    except FileExistsError:
        return ProveFileResult(
            status="error",
            message=f"Output file already exists: {actual_output_path}",
        )

    if is_mock_mode():
        return mock_prove_file(file_path, output_path, wait=wait)

    # Real API implementation
    if not has_api_key():
        return ProveFileResult(status="error", message=_API_KEY_ERROR)

    try:
        from aristotlelib import Project

        file_dir = os.path.dirname(canonical_path) or "."
        file_name = os.path.basename(canonical_path)

        project = await Project.create_from_directory(
            prompt=f"Please prove all sorry statements in {file_name}.",
            project_dir=file_dir,
        )

        project_id = str(project.project_id)

        if not wait:
            # Cleanup stale metadata before adding new entry
            _cleanup_stale_metadata()
            # Store metadata for retrieval when polling (thread-safe)
            with _metadata_lock:
                _async_job_metadata[project_id] = {
                    "file_path": canonical_path,
                    "output_path": actual_output_path,
                    "timestamp": time.time(),
                }

            return ProveFileResult(
                status="submitted",
                output_path=actual_output_path,
                project_id=project_id,
                message="Proof submitted. Use check_prove_file to poll for results.",
            )

        solution_path = await project.wait_for_completion()

        if solution_path and os.path.exists(solution_path):
            try:
                copied = _copy_lean_from_solution_archive(
                    str(solution_path),
                    actual_output_path,
                    preferred_filename=file_name,
                )
                if copied:
                    return _analyze_solution_file(actual_output_path, project_id)
                return ProveFileResult(
                    status="failed",
                    project_id=project_id,
                    message="Solution file not found in archive",
                )
            finally:
                os.unlink(solution_path)
        else:
            await project.refresh()
            return ProveFileResult(
                status="failed",
                project_id=project_id,
                message=f"Project status: {project.status}",
            )

    except Exception as e:
        return ProveFileResult(
            status="error",
            message=_sanitize_api_error(e),
        )


async def check_prove_file(
    project_id: str,
    output_path: str | None = None,
    save: bool = False,
) -> ProveFileResult:
    """Poll for the status of a previously submitted file proof.

    Args:
        project_id: The project ID returned from prove_file(wait=False)
        output_path: Where to write the solution. If not provided, uses the path
                     from the original prove_file call (stored for up to 30 days).
        save: If False (default), only return status without writing the solution file.
              If True, write the solution file to output_path when complete.

    Returns:
        ProveFileResult with current status. If complete and save=True, includes output_path.
    """
    if is_mock_mode():
        return mock_check_prove_file(project_id, output_path=output_path, save=save)

    if not has_api_key():
        return ProveFileResult(status="error", message=_API_KEY_ERROR)

    # Retrieve stored metadata if available (thread-safe)
    with _metadata_lock:
        metadata = _async_job_metadata.get(project_id, {}).copy()
    stored_output_path = metadata.get("output_path")

    # Use stored output path if none provided
    if output_path is None and isinstance(stored_output_path, str):
        output_path = stored_output_path

    try:
        from aristotlelib import Project

        # Load existing project
        project = await Project.from_id(project_id)
        await project.refresh()

        # Get status and progress
        status_str = (
            project.status.name if hasattr(project.status, "name") else str(project.status).upper()
        )
        pct = project.percent_complete

        # Map API status to our status
        our_status, message = _map_api_status(status_str, pct)

        if our_status == "complete":
            # If save=False, just return status without writing the file
            if not save:
                return ProveFileResult(
                    status="proved",
                    project_id=project_id,
                    percent_complete=100,
                    message="Proof complete. Call again with save=True to write the solution.",
                )

            # Require output_path when saving (stored path may have expired)
            if not output_path:
                return ProveFileResult(
                    status="error",
                    project_id=project_id,
                    percent_complete=100,
                    message="Proof complete but output_path required to save.",
                )

            # Find a unique path to avoid overwriting existing files
            safe_output_path = _find_unique_path(output_path)

            # Get the solution
            try:
                solution_path = await project.get_solution(destination=safe_output_path)
                file_path = metadata.get("file_path")
                preferred_filename = (
                    os.path.basename(file_path) if isinstance(file_path, str) else None
                )
                copied = _copy_lean_from_solution_archive(
                    str(solution_path),
                    safe_output_path,
                    preferred_filename=preferred_filename,
                )
                if not copied:
                    return ProveFileResult(
                        status="failed",
                        project_id=project_id,
                        percent_complete=100,
                        message="Solution file not found in archive",
                    )
            finally:
                if os.path.exists(safe_output_path) and tarfile.is_tarfile(safe_output_path):
                    os.unlink(safe_output_path)

            # Note: metadata is NOT cleared here - TTL cleanup handles it.
            # This allows saving to multiple paths if needed.

            return _analyze_solution_file(safe_output_path, project_id)

        # Note: metadata cleanup is handled by TTL (_cleanup_stale_metadata),
        # not on completion/failure. This keeps the interface simpler.

        return ProveFileResult(
            status=our_status,
            project_id=project_id,
            percent_complete=pct if our_status != "queued" else 0,
            message=message,
        )

    except Exception as e:
        return ProveFileResult(
            status="error",
            project_id=project_id,
            message=_sanitize_api_error(e),
        )


async def formalize(
    description: str,
    prove: bool = False,
    context_file: str | None = None,
    wait: bool = True,
) -> FormalizeResult:
    """Convert natural language math to Lean 4 code.

    Args:
        description: Natural language math statement or problem
        prove: Whether to also prove the formalized statement
        context_file: Optional path to a single Lean file providing definitions
                      for the formalization. (Note: unlike prove's context_files,
                      this accepts only one file per the underlying API.)
        wait: If True (default), block until complete. If False, submit
              and return immediately with project_id for polling.

    Returns:
        FormalizeResult with status and Lean code.
        If wait=False, returns status="submitted" with project_id for polling.
    """
    # Validate input size
    if len(description) > _MAX_DESCRIPTION_SIZE:
        return FormalizeResult(
            status="error",
            message=f"Description exceeds maximum size of {_MAX_DESCRIPTION_SIZE} bytes.",
        )

    if is_mock_mode():
        return mock_formalize(description, prove, context_file, wait=wait)

    # Real API implementation
    if not has_api_key():
        return FormalizeResult(status="error", message=_API_KEY_ERROR)

    # Validate and canonicalize context file if provided
    canonical_context: str | None = None
    if context_file:
        canonical_context = _canonicalize_path(context_file)
        if not os.path.exists(canonical_context):
            return FormalizeResult(
                status="error",
                message=f"Context file not found: {context_file}",
            )
        basename_error = _duplicate_context_basename_error(
            [canonical_context],
            reserved_filenames={"description.txt"},
        )
        if basename_error:
            return FormalizeResult(status="error", message=basename_error)

    try:
        from aristotlelib import Project

        with tempfile.TemporaryDirectory() as temp_dir:
            with open(os.path.join(temp_dir, "description.txt"), "w") as f:
                f.write(description)

            if canonical_context:
                ctx_name = os.path.basename(canonical_context)
                shutil.copy2(canonical_context, os.path.join(temp_dir, ctx_name))

            prove_instruction = " and prove it" if prove else ""
            prompt_text = (
                f"Please formalize the following mathematical statement"
                f"{prove_instruction}: {description}"
            )
            project = await Project.create_from_directory(
                prompt=prompt_text,
                project_dir=temp_dir,
            )

            project_id = str(project.project_id)

            if not wait:
                return FormalizeResult(
                    status="submitted",
                    project_id=project_id,
                    message="Formalization submitted. Use check_formalize to poll for results.",
                )

            solution_path = await project.wait_for_completion()

            if solution_path and os.path.exists(solution_path):
                try:
                    lean_code = _read_lean_from_solution_archive(str(solution_path))
                    if lean_code is not None:
                        status = "proved" if prove else "formalized"
                        if prove:
                            msg = "Successfully formalized and proved"
                        else:
                            msg = "Successfully formalized"

                        return FormalizeResult(
                            status=status,
                            lean_code=lean_code,
                            message=msg,
                        )
                    else:
                        return FormalizeResult(
                            status="failed",
                            message="No Lean code found in result",
                        )
                finally:
                    os.unlink(solution_path)
            else:
                await project.refresh()
                return FormalizeResult(
                    status="failed",
                    message=f"Project status: {project.status}",
                )

    except Exception as e:
        return FormalizeResult(
            status="error",
            message=_sanitize_api_error(e),
        )


async def check_formalize(project_id: str) -> FormalizeResult:
    """Poll for the status of a previously submitted formalization.

    Args:
        project_id: The project ID returned from formalize(wait=False)

    Returns:
        FormalizeResult with current status. If complete, includes the Lean code.
    """
    if is_mock_mode():
        return mock_check_formalize(project_id)

    if not has_api_key():
        return FormalizeResult(status="error", message=_API_KEY_ERROR)

    try:
        from aristotlelib import Project

        # Load existing project
        project = await Project.from_id(project_id)
        await project.refresh()

        # Get status name from enum
        status_str = (
            project.status.name if hasattr(project.status, "name") else str(project.status).upper()
        )
        pct = project.percent_complete

        # Map API status to our status
        our_status, message = _map_api_status(status_str, pct)

        if our_status == "complete":
            # Get the solution
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as f:
                output_path = f.name

            try:
                solution_path = await project.get_solution(destination=output_path)
                if solution_path and os.path.exists(solution_path):
                    lean_code = _read_lean_from_solution_archive(str(solution_path))
                    if lean_code is not None:
                        return FormalizeResult(
                            status="formalized",
                            lean_code=lean_code,
                            project_id=project_id,
                            percent_complete=100,
                            message="Formalization completed successfully",
                        )
            finally:
                if os.path.exists(output_path):
                    os.unlink(output_path)

            return FormalizeResult(
                status="failed",
                project_id=project_id,
                percent_complete=pct,
                message="Completed but no result available",
            )

        return FormalizeResult(
            status=our_status,
            project_id=project_id,
            percent_complete=pct if our_status != "queued" else 0,
            message=message,
        )

    except Exception as e:
        return FormalizeResult(
            status="error",
            project_id=project_id,
            message=_sanitize_api_error(e),
        )
