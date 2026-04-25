"""Mock responses for testing without the Aristotle API."""

from __future__ import annotations

import os
import tarfile
import threading
import time
import uuid
from datetime import UTC, datetime
from io import BytesIO
from typing import TypedDict

from aristotle_mcp.models import (
    FormalizeResult,
    ProjectFileResult,
    ProjectResult,
    ProveFileResult,
    ProveResult,
)

# Thread lock for accessing shared mock state
_mock_lock = threading.Lock()

# In-memory store for mock async proofs
# Access must be protected by _mock_lock
_mock_projects: dict[str, _MockProjectData] = {}
_mock_file_projects: dict[str, _MockFileProjectData] = {}
_mock_formalize_projects: dict[str, _MockFormalizeProjectData] = {}


class _MockProjectData(TypedDict):
    """Internal storage for mock proof jobs."""

    status: str
    code: str | None
    counterexample: str | None
    message: str
    poll_count: int


class _MockFileProjectData(TypedDict):
    """Internal storage for mock file proof jobs."""

    status: str
    output_path: str | None
    message: str
    poll_count: int


class _MockFormalizeProjectData(TypedDict):
    """Internal storage for mock formalize jobs."""

    status: str
    lean_code: str | None
    message: str
    poll_count: int


def _mock_timestamp() -> str:
    """Return an ISO timestamp for mock project metadata."""
    return datetime.now(UTC).isoformat()


def _mock_raw_status(final_status: str, poll_count: int) -> tuple[str, str, int]:
    """Map mock job state to project metadata status."""
    if final_status == "canceled":
        return "CANCELED", "canceled", 100
    if poll_count <= 1:
        return "QUEUED", "queued", 0
    if poll_count == 2:
        return "IN_PROGRESS", "in_progress", 50
    if final_status in ("proved", "formalized"):
        return "COMPLETE", "complete", 100
    if final_status in ("partial", "counterexample"):
        return "COMPLETE_WITH_ERRORS", "complete_with_errors", 100
    if final_status == "failed":
        return "FAILED", "failed", 100
    return "UNKNOWN", "unknown", 0


def _mock_known_project(project_id: str) -> bool:
    """Return whether a mock project exists."""
    return (
        project_id in _mock_projects
        or project_id in _mock_file_projects
        or project_id in _mock_formalize_projects
    )


def _safe_mock_filename(project_id: str, suffix: str) -> str:
    """Create a safe local mock artifact filename."""
    safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in project_id)
    if not safe_id:
        safe_id = "project"
    return f"{safe_id}{suffix}"


def _mock_unique_path(path: str) -> str:
    """Return a unique path by adding a numeric suffix if needed."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    for i in range(1, 1001):
        candidate = f"{base}.{i}{ext}"
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError(f"Could not find unique path: {path}")


def _resolve_mock_output_path(
    project_id: str,
    output_path: str | None,
    suffix: str,
    overwrite: bool,
) -> tuple[str | None, str | None]:
    """Resolve a mock download path, returning an error message if unsafe."""
    if output_path is None:
        return os.path.abspath(_mock_unique_path(_safe_mock_filename(project_id, suffix))), None

    absolute_path = os.path.abspath(output_path)
    if os.path.exists(absolute_path) and not overwrite:
        return None, "Output file already exists. Pass overwrite=True to replace it."
    os.makedirs(os.path.dirname(absolute_path) or ".", exist_ok=True)
    return absolute_path, None


def _write_mock_archive(output_path: str, filename: str, content: str) -> None:
    """Write a small tar.gz archive for mock artifact downloads."""
    data = content.encode()
    info = tarfile.TarInfo(name=filename)
    info.size = len(data)
    info.mtime = int(time.time())
    with tarfile.open(output_path, "w:gz") as tar:
        tar.addfile(info, BytesIO(data))


def _mock_project_status(project_id: str) -> tuple[str, str, int, str | None]:
    """Return raw status, mapped status, percent, and summary for a mock project."""
    if project_id in _mock_projects:
        project = _mock_projects[project_id]
        raw_status, status, percent = _mock_raw_status(project["status"], project["poll_count"])
        return raw_status, status, percent, project["message"]
    if project_id in _mock_file_projects:
        file_project = _mock_file_projects[project_id]
        raw_status, status, percent = _mock_raw_status(
            file_project["status"],
            file_project["poll_count"],
        )
        return raw_status, status, percent, file_project["message"]
    formalize_project = _mock_formalize_projects[project_id]
    raw_status, status, percent = _mock_raw_status(
        formalize_project["status"],
        formalize_project["poll_count"],
    )
    return raw_status, status, percent, formalize_project["message"]


def _mock_solution_content(project_id: str) -> str | None:
    """Return mock solution content if the project has downloadable output."""
    if project_id in _mock_projects:
        project = _mock_projects[project_id]
        if project["status"] in ("proved", "counterexample"):
            return project["code"] or project["counterexample"]
        return None
    if project_id in _mock_file_projects:
        file_project = _mock_file_projects[project_id]
        if file_project["status"] in ("proved", "partial"):
            return "-- Mock Aristotle file solution\n"
        return None
    formalize_project = _mock_formalize_projects[project_id]
    if formalize_project["status"] in ("formalized", "proved"):
        return formalize_project["lean_code"]
    return None


def mock_prove(
    code: str,
    context_files: list[str] | None = None,
    hint: str | None = None,
    wait: bool = True,
) -> ProveResult:
    """Mock implementation of prove.

    Provides realistic responses based on the input:
    - If code contains 'false_theorem' or 'bad_lemma': returns counterexample
    - If code contains 'timeout' or 'hard': returns failed
    - Otherwise: returns proved

    If wait=False, stores the proof job and returns a project_id for polling.

    Args:
        code: Lean 4 code containing sorry statements
        context_files: Optional paths to context files (unused in mock)
        hint: Optional hint (unused in mock)
        wait: If True, return result immediately. If False, return project_id for polling.

    Returns:
        ProveResult with status and optional code/counterexample
    """
    # Silence unused argument warnings - these are part of the API
    _ = context_files
    _ = hint

    # Determine what the final result will be
    final_code: str | None
    final_counterexample: str | None

    if "false_theorem" in code.lower() or "bad_lemma" in code.lower():
        final_status = "counterexample"
        final_code = None
        final_counterexample = (
            "n = 0 provides a counterexample: the left-hand side evaluates to 0, "
            "but the right-hand side evaluates to 1"
        )
        final_message = "Statement is false; counterexample found"
    elif "timeout" in code.lower() or "hard" in code.lower():
        final_status = "failed"
        final_code = None
        final_counterexample = None
        final_message = (
            "Could not find a proof within the time limit. "
            "This does not mean the statement is false."
        )
    else:
        final_status = "proved"
        # Return the code with a mock proof comment appended
        final_code = code + "\n-- Proof filled by Aristotle (mock)"
        final_counterexample = None
        final_message = "Successfully proved"

    # Generate a project ID
    project_id = f"mock-{uuid.uuid4()}"

    # If not waiting, store the job and return immediately (thread-safe)
    if not wait:
        with _mock_lock:
            _mock_projects[project_id] = _MockProjectData(
                status=final_status,
                code=final_code,
                counterexample=final_counterexample,
                message=final_message,
                poll_count=0,
            )
        return ProveResult(
            status="submitted",
            project_id=project_id,
            message="Proof submitted. Use check_proof to poll for results.",
        )

    # Waiting - return the final result immediately
    with _mock_lock:
        _mock_projects[project_id] = _MockProjectData(
            status=final_status,
            code=final_code,
            counterexample=final_counterexample,
            message=final_message,
            poll_count=3,
        )

    return ProveResult(
        status=final_status,
        code=final_code,
        counterexample=final_counterexample,
        project_id=project_id,
        message=final_message,
    )


def mock_check_proof(project_id: str) -> ProveResult:
    """Mock implementation of check_proof.

    Simulates async polling:
    - First call: returns "queued"
    - Second call: returns "in_progress"
    - Third+ calls: returns the final result

    Args:
        project_id: The mock project ID to check

    Returns:
        ProveResult with current status
    """
    with _mock_lock:
        if project_id not in _mock_projects:
            return ProveResult(
                status="error",
                project_id=project_id,
                message=f"Unknown project ID: {project_id}",
            )

        project = _mock_projects[project_id]
        project["poll_count"] += 1
        poll_count = project["poll_count"]

        # Simulate progression through statuses
        if poll_count == 1:
            return ProveResult(
                status="queued",
                project_id=project_id,
                percent_complete=0,
                message="Proof is queued, waiting to start",
            )
        elif poll_count == 2:
            return ProveResult(
                status="in_progress",
                project_id=project_id,
                percent_complete=50,
                message="Proof is being computed (50% complete)",
            )
        else:
            # Return final result
            return ProveResult(
                status=project["status"],
                code=project["code"],
                counterexample=project["counterexample"],
                project_id=project_id,
                percent_complete=100,
                message=project["message"],
            )


def mock_prove_file(
    file_path: str,
    output_path: str | None = None,
    wait: bool = True,
) -> ProveFileResult:
    """Mock implementation of prove_file.

    Returns a simulated result based on the file path.

    Args:
        file_path: Path to the Lean file
        output_path: Optional output path for the solved file
        wait: If True, return result immediately. If False, return project_id for polling.

    Returns:
        ProveFileResult with status
    """
    if not os.path.exists(file_path):
        return ProveFileResult(status="error", message=f"File not found: {file_path}")

    # Determine output path (matches aristotlelib's default naming)
    if output_path is None:
        base, ext = os.path.splitext(file_path)
        output_path = f"{base}_aristotle{ext}"

    # Check if output would overwrite existing file
    if os.path.exists(output_path):
        return ProveFileResult(
            status="error",
            message=f"Output file already exists: {output_path}",
        )

    # Determine final result based on filename for testing different scenarios
    if "partial" in file_path.lower():
        final_status = "partial"
        final_message = "Some proofs could not be completed"
    elif "fail" in file_path.lower():
        final_status = "failed"
        final_message = "Could not find proofs within the time limit"
    else:
        final_status = "proved"
        final_message = "Successfully proved"

    # Generate project ID
    project_id = f"mock-file-{uuid.uuid4()}"

    # If not waiting, store the job and return immediately (thread-safe)
    if not wait:
        with _mock_lock:
            _mock_file_projects[project_id] = _MockFileProjectData(
                status=final_status,
                output_path=output_path,
                message=final_message,
                poll_count=0,
            )
        return ProveFileResult(
            status="submitted",
            project_id=project_id,
            message="Proof submitted. Use check_prove_file to poll for results.",
        )

    # Waiting - return final result
    with _mock_lock:
        _mock_file_projects[project_id] = _MockFileProjectData(
            status=final_status,
            output_path=output_path,
            message=final_message,
            poll_count=3,
        )

    return ProveFileResult(
        status=final_status,
        output_path=output_path,
        project_id=project_id,
        percent_complete=100,
        message=final_message,
    )


def mock_check_prove_file(
    project_id: str,
    output_path: str | None = None,
    save: bool = False,
) -> ProveFileResult:
    """Mock implementation of check_prove_file.

    Simulates async polling for file proofs:
    - First call: returns "queued"
    - Second call: returns "in_progress"
    - Third+ calls: returns the final result

    Args:
        project_id: The mock project ID to check
        output_path: Override the output path from original prove_file call.
                     If provided and save=True, uses this path instead.
        save: If False (default), just return status without writing the solution file.
              If True, include output_path when complete.

    Returns:
        ProveFileResult with current status
    """
    with _mock_lock:
        if project_id not in _mock_file_projects:
            return ProveFileResult(
                status="error",
                project_id=project_id,
                message=f"Unknown project ID: {project_id}",
            )

        project = _mock_file_projects[project_id]
        project["poll_count"] += 1
        poll_count = project["poll_count"]

        # Simulate progression through statuses
        if poll_count == 1:
            return ProveFileResult(
                status="queued",
                project_id=project_id,
                percent_complete=0,
                message="Proof is queued, waiting to start",
            )
        elif poll_count == 2:
            return ProveFileResult(
                status="in_progress",
                project_id=project_id,
                percent_complete=50,
                message="Proof is being computed (50% complete)",
            )
        else:
            # Return final result
            if save:
                # Use provided output_path or fall back to stored path
                final_output_path = output_path or project["output_path"]
                return ProveFileResult(
                    status=project["status"],
                    output_path=final_output_path,
                    project_id=project_id,
                    percent_complete=100,
                    message=project["message"],
                )
            else:
                # Don't include output_path when save=False
                message = project["message"]
                if project["status"] == "proved":
                    message = "Proof complete. Call again with save=True to write the solution."
                return ProveFileResult(
                    status=project["status"],
                    project_id=project_id,
                    percent_complete=100,
                    message=message,
                )


def _generate_mock_lean_code(
    description: str,
    prove: bool,
    context_file: str | None,
) -> tuple[str, str, str]:
    """Generate mock Lean code based on description keywords.

    Returns:
        Tuple of (lean_code, status, message)
    """
    # Add context import if provided
    context_header = ""
    if context_file:
        context_name = os.path.splitext(os.path.basename(context_file))[0]
        context_header = f"-- Using context from: {context_file}\nimport {context_name}\n\n"

    description_lower = description.lower()

    # Generate different formalizations based on keywords
    if "even" in description_lower and "sum" in description_lower:
        if prove:
            lean_code = """def even (n : Nat) : Prop := ∃ k, n = 2 * k

theorem sum_of_evens (a b : Nat) (ha : even a) (hb : even b) : even (a + b) := by
  obtain ⟨ka, hka⟩ := ha; obtain ⟨kb, hkb⟩ := hb; exact ⟨ka + kb, by omega⟩"""
        else:
            lean_code = """def even (n : Nat) : Prop := ∃ k, n = 2 * k

theorem sum_of_evens (a b : Nat) (ha : even a) (hb : even b) : even (a + b) := by
  sorry"""

    elif "prime" in description_lower:
        if prove:
            lean_code = """def prime (n : Nat) : Prop := n > 1 ∧ ∀ m, m ∣ n → m = 1 ∨ m = n

theorem prime_example : prime 7 := by
  decide"""
        else:
            lean_code = """def prime (n : Nat) : Prop := n > 1 ∧ ∀ m, m ∣ n → m = 1 ∨ m = n

theorem prime_example : prime 7 := by
  sorry"""

    elif "commut" in description_lower:
        if prove:
            lean_code = """theorem add_comm_example (a b : Nat) : a + b = b + a := by
  ring"""
        else:
            lean_code = """theorem add_comm_example (a b : Nat) : a + b = b + a := by
  sorry"""

    else:
        # Generic formalization
        if prove:
            lean_code = f"""-- Formalization of: {description}
theorem statement : True := by
  trivial"""
        else:
            lean_code = f"""-- Formalization of: {description}
theorem statement : True := by
  sorry"""

    lean_code = context_header + lean_code
    status = "proved" if prove else "formalized"
    message = "Formalized and proved" if prove else "Successfully formalized to Lean 4"
    if context_file:
        message += f" (using context from {context_file})"

    return lean_code, status, message


def mock_formalize(
    description: str,
    prove: bool = False,
    context_file: str | None = None,
    wait: bool = True,
) -> FormalizeResult:
    """Mock implementation of formalize.

    Generates plausible Lean code from natural language descriptions.

    Args:
        description: Natural language description of the theorem
        prove: Whether to also prove the formalized statement
        context_file: Optional Lean file providing context definitions
        wait: If True, return result immediately. If False, return project_id for polling.

    Returns:
        FormalizeResult with status and Lean code
    """
    lean_code, final_status, final_message = _generate_mock_lean_code(
        description, prove, context_file
    )

    # Generate project ID
    project_id = f"mock-formalize-{uuid.uuid4()}"

    # If not waiting, store the job and return immediately (thread-safe)
    if not wait:
        with _mock_lock:
            _mock_formalize_projects[project_id] = _MockFormalizeProjectData(
                status=final_status,
                lean_code=lean_code,
                message=final_message,
                poll_count=0,
            )
        return FormalizeResult(
            status="submitted",
            project_id=project_id,
            message="Formalization submitted. Use check_formalize to poll for results.",
        )

    # Waiting - return final result immediately
    with _mock_lock:
        _mock_formalize_projects[project_id] = _MockFormalizeProjectData(
            status=final_status,
            lean_code=lean_code,
            message=final_message,
            poll_count=3,
        )

    return FormalizeResult(
        status=final_status,
        lean_code=lean_code,
        project_id=project_id,
        message=final_message,
    )


def mock_check_formalize(project_id: str) -> FormalizeResult:
    """Mock implementation of check_formalize.

    Simulates async polling for formalization jobs:
    - First call: returns "queued"
    - Second call: returns "in_progress"
    - Third+ calls: returns the final result

    Args:
        project_id: The mock project ID to check

    Returns:
        FormalizeResult with current status
    """
    with _mock_lock:
        if project_id not in _mock_formalize_projects:
            return FormalizeResult(
                status="error",
                project_id=project_id,
                message=f"Unknown project ID: {project_id}",
            )

        project = _mock_formalize_projects[project_id]
        project["poll_count"] += 1
        poll_count = project["poll_count"]

        # Simulate progression through statuses
        if poll_count == 1:
            return FormalizeResult(
                status="queued",
                project_id=project_id,
                percent_complete=0,
                message="Formalization is queued, waiting to start",
            )
        elif poll_count == 2:
            return FormalizeResult(
                status="in_progress",
                project_id=project_id,
                percent_complete=50,
                message="Formalization is being computed (50% complete)",
            )
        else:
            # Return final result
            return FormalizeResult(
                status=project["status"],
                lean_code=project["lean_code"],
                project_id=project_id,
                percent_complete=100,
                message=project["message"],
            )


def mock_get_project(project_id: str) -> ProjectResult:
    """Mock implementation of get_project."""
    with _mock_lock:
        if not _mock_known_project(project_id):
            return ProjectResult(
                status="error",
                project_id=project_id,
                message=f"Unknown project ID: {project_id}",
            )

        raw_status, status, percent_complete, output_summary = _mock_project_status(project_id)

    return ProjectResult(
        status=status,
        project_id=project_id,
        raw_status=raw_status,
        percent_complete=percent_complete,
        created_at=_mock_timestamp(),
        last_updated_at=_mock_timestamp(),
        input_prompt="Mock Aristotle project",
        output_summary=output_summary if percent_complete == 100 else None,
        message=f"Project status: {status}",
    )


def mock_cancel_project(project_id: str) -> ProjectResult:
    """Mock implementation of cancel_project."""
    with _mock_lock:
        if project_id in _mock_projects:
            _mock_projects[project_id]["status"] = "canceled"
            _mock_projects[project_id]["message"] = "Project was canceled"
            _mock_projects[project_id]["poll_count"] = 3
        elif project_id in _mock_file_projects:
            _mock_file_projects[project_id]["status"] = "canceled"
            _mock_file_projects[project_id]["message"] = "Project was canceled"
            _mock_file_projects[project_id]["poll_count"] = 3
        elif project_id in _mock_formalize_projects:
            _mock_formalize_projects[project_id]["status"] = "canceled"
            _mock_formalize_projects[project_id]["message"] = "Project was canceled"
            _mock_formalize_projects[project_id]["poll_count"] = 3
        else:
            return ProjectResult(
                status="error",
                project_id=project_id,
                message=f"Unknown project ID: {project_id}",
            )

    return ProjectResult(
        status="canceled",
        project_id=project_id,
        raw_status="CANCELED",
        percent_complete=100,
        created_at=_mock_timestamp(),
        last_updated_at=_mock_timestamp(),
        input_prompt="Mock Aristotle project",
        message="Project canceled.",
    )


def mock_get_solution(
    project_id: str,
    output_path: str | None = None,
    overwrite: bool = False,
) -> ProjectFileResult:
    """Mock implementation of get_solution."""
    with _mock_lock:
        if not _mock_known_project(project_id):
            return ProjectFileResult(
                status="error",
                project_id=project_id,
                message=f"Unknown project ID: {project_id}",
            )

        raw_status, status, percent_complete, _summary = _mock_project_status(project_id)
        content = _mock_solution_content(project_id)

    if raw_status not in ("COMPLETE", "COMPLETE_WITH_ERRORS", "OUT_OF_BUDGET") or content is None:
        return ProjectFileResult(
            status=status,
            project_id=project_id,
            raw_status=raw_status,
            percent_complete=percent_complete,
            message="Project does not have a downloadable solution archive.",
        )

    resolved_path, error = _resolve_mock_output_path(
        project_id,
        output_path,
        "_aristotle.tar.gz",
        overwrite,
    )
    if error or resolved_path is None:
        return ProjectFileResult(status="error", project_id=project_id, message=error or "")

    _write_mock_archive(resolved_path, "solution.lean", content)
    return ProjectFileResult(
        status="saved",
        project_id=project_id,
        output_path=resolved_path,
        raw_status=raw_status,
        percent_complete=percent_complete,
        message="Solution archive downloaded.",
    )


def mock_get_solution_if_complete(
    project_id: str,
    output_path: str | None = None,
    overwrite: bool = False,
) -> ProjectFileResult:
    """Mock implementation of get_solution_if_complete."""
    with _mock_lock:
        if not _mock_known_project(project_id):
            return ProjectFileResult(
                status="error",
                project_id=project_id,
                message=f"Unknown project ID: {project_id}",
            )

        raw_status, status, percent_complete, _summary = _mock_project_status(project_id)

    if raw_status not in ("COMPLETE", "COMPLETE_WITH_ERRORS", "OUT_OF_BUDGET"):
        return ProjectFileResult(
            status=status,
            project_id=project_id,
            raw_status=raw_status,
            percent_complete=percent_complete,
            message="Project is not complete; no solution archive was downloaded.",
        )

    return mock_get_solution(project_id, output_path=output_path, overwrite=overwrite)


def mock_get_input(
    project_id: str,
    output_path: str | None = None,
    overwrite: bool = False,
) -> ProjectFileResult:
    """Mock implementation of get_input."""
    with _mock_lock:
        if not _mock_known_project(project_id):
            return ProjectFileResult(
                status="error",
                project_id=project_id,
                message=f"Unknown project ID: {project_id}",
            )

        raw_status, _status, percent_complete, _summary = _mock_project_status(project_id)

    resolved_path, error = _resolve_mock_output_path(
        project_id,
        output_path,
        "_input.tar.gz",
        overwrite,
    )
    if error or resolved_path is None:
        return ProjectFileResult(status="error", project_id=project_id, message=error or "")

    _write_mock_archive(resolved_path, "input.txt", f"Mock input for project {project_id}\n")
    return ProjectFileResult(
        status="saved",
        project_id=project_id,
        output_path=resolved_path,
        raw_status=raw_status,
        percent_complete=percent_complete,
        message="Input archive downloaded.",
    )
