"""Proof and formalization workflows composed from native operations."""

from __future__ import annotations

import os
import tarfile
import tempfile
from typing import Final

from aristotlelib import AristotleAPIError, Project
from aristotlelib.local_file_utils import LeanProjectError

from aristotle_mcp.config import is_mock_mode
from aristotle_mcp.errors import error_result
from aristotle_mcp.files import (
    _canonicalize_path,
    _copy_lean_from_solution_archive,
    _lake_root,
    _read_lean_from_solution_archive,
    _remove_reserved_path,
    _reserve_output_path,
    _stage_context_files,
)
from aristotle_mcp.models import ErrorResult, TaskResult, WaitTaskResult, WorkflowResult
from aristotle_mcp.projects import submit_project
from aristotle_mcp.tasks import wait_task

_MAX_CODE_SIZE: Final = 1_000_000
_MAX_DESCRIPTION_SIZE: Final = 100_000
_MAX_FILE_SIZE: Final = 10_000_000
_OUTPUT_STATUSES: Final = frozenset(
    {"complete", "complete_with_errors", "out_of_budget"}
)


def _submitted(project_id: str, task: TaskResult) -> WorkflowResult:
    return WorkflowResult(
        task.status,
        project_id,
        task.task_id,
        None,
        None,
        task.output_summary,
        "Project submitted.",
    )


def _after_wait(wait_result: WaitTaskResult) -> WorkflowResult:
    task = wait_result.task
    return WorkflowResult(
        task.status,
        task.project_id,
        task.task_id,
        None,
        None,
        task.output_summary,
        wait_result.message,
    )


async def _download_code(project_id: str, preferred_filename: str | None = None) -> str | None:
    project = await Project.from_id(project_id)
    await project.refresh()
    if not project.has_files:
        return None
    with tempfile.TemporaryDirectory() as directory:
        archive_path = os.path.join(directory, "result.tar.gz")
        downloaded = await project.get_files(archive_path)
        return _read_lean_from_solution_archive(str(downloaded), preferred_filename)


async def _copy_code(
    project_id: str,
    output_path: str,
    preferred_filename: str | None,
) -> str | None:
    project = await Project.from_id(project_id)
    await project.refresh()
    if not project.has_files:
        return None
    with tempfile.TemporaryDirectory() as directory:
        archive_path = os.path.join(directory, "result.tar.gz")
        downloaded = await project.get_files(archive_path)
        copied = _copy_lean_from_solution_archive(
            str(downloaded),
            output_path,
            preferred_filename,
        )
        return output_path if copied else None


async def _submit_and_wait(
    directory: str,
    prompt: str,
    wait: bool,
    output_path: str | None = None,
    preferred_filename: str | None = None,
) -> WorkflowResult | ErrorResult:
    reserved_output: str | None = None
    try:
        if output_path is not None:
            reserved_output = _reserve_output_path(output_path)
        submission = await submit_project(prompt, project_dir=directory)
        if isinstance(submission, ErrorResult):
            return submission
        project, task = submission
        if task is None:
            return ErrorResult("error", "api", "Submitted project has no task")
        if not wait:
            return _submitted(project.project_id, task)
        waited = await wait_task(task.task_id)
        if isinstance(waited, ErrorResult):
            return waited
        if waited.outcome != "terminal":
            return _after_wait(waited)
        if waited.task.status not in _OUTPUT_STATUSES:
            return _after_wait(waited)
        if reserved_output is not None:
            copied = await _copy_code(project.project_id, reserved_output, preferred_filename)
            if copied is not None:
                reserved_output = None
            return WorkflowResult(
                waited.task.status,
                project.project_id,
                waited.task.task_id,
                None,
                copied,
                waited.task.output_summary,
                "Workflow completed."
                if copied is not None
                else "Project has no downloadable Lean file.",
            )
        code = await _download_code(project.project_id, preferred_filename)
        return WorkflowResult(
            waited.task.status,
            project.project_id,
            waited.task.task_id,
            code,
            None,
            waited.task.output_summary,
            "Workflow completed." if code is not None else "Project has no downloadable Lean file.",
        )
    except (AristotleAPIError, LeanProjectError, OSError, tarfile.TarError, ValueError) as error:
        return error_result(error)
    finally:
        if reserved_output is not None:
            _remove_reserved_path(reserved_output, True)


async def prove(
    code: str,
    context_files: list[str] | None = None,
    hint: str | None = None,
    wait: bool = True,
) -> WorkflowResult | ErrorResult:
    """Submit a self-contained Lean proof request."""
    try:
        code_size = len(code.encode("utf-8"))
    except UnicodeEncodeError:
        return ErrorResult("error", "validation", "Code must be UTF-8 encodable.")
    if code_size > _MAX_CODE_SIZE:
        return ErrorResult(
            "error",
            "validation",
            f"Code exceeds maximum size of {_MAX_CODE_SIZE} bytes.",
        )
    if is_mock_mode():
        from aristotle_mcp.mock_workflows import prove as mock_prove

        return await mock_prove(code, context_files, hint, wait)
    if not code.strip():
        return ErrorResult("error", "validation", "code is required")
    try:
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, "proof.lean"), "w", encoding="utf-8") as file:
                if hint is not None:
                    file.write(f"-- Hint: {hint}\n")
                file.write(code)
            _stage_context_files(directory, context_files or [], {"proof.lean"})
            return await _submit_and_wait(
                directory,
                "Please prove all sorry statements.",
                wait,
                preferred_filename="proof.lean",
            )
    except (OSError, ValueError) as error:
        return error_result(error)


async def prove_file(
    file_path: str,
    output_path: str | None = None,
    wait: bool = True,
) -> WorkflowResult | ErrorResult:
    """Submit the containing Lean project and optionally save its solved file."""
    canonical = _canonicalize_path(file_path)
    if not os.path.isfile(canonical):
        return ErrorResult("error", "validation", f"File not found: {file_path}")
    try:
        file_size = os.path.getsize(canonical)
    except OSError as error:
        return error_result(error)
    if file_size > _MAX_FILE_SIZE:
        return ErrorResult(
            "error",
            "validation",
            f"File exceeds maximum size of {_MAX_FILE_SIZE} bytes.",
        )
    if is_mock_mode():
        from aristotle_mcp.mock_workflows import prove_file as mock_prove_file

        return await mock_prove_file(file_path, output_path, wait)
    try:
        with open(canonical, encoding="utf-8") as source:
            source.read()
    except UnicodeDecodeError:
        return ErrorResult("error", "validation", "File must be valid UTF-8.")
    except OSError as error:
        return error_result(error)
    final_output = output_path or f"{os.path.splitext(canonical)[0]}_aristotle.lean"
    lake_root = _lake_root(canonical)
    source_path = os.path.relpath(canonical, lake_root).replace(os.sep, "/")
    return await _submit_and_wait(
        lake_root,
        f"Please prove all sorry statements in {source_path}.",
        wait,
        _canonicalize_path(final_output) if wait else None,
        source_path,
    )


async def formalize(
    description: str,
    prove: bool = False,
    context_file: str | None = None,
    wait: bool = True,
) -> WorkflowResult | ErrorResult:
    """Submit a natural-language formalization request."""
    try:
        description_size = len(description.encode("utf-8"))
    except UnicodeEncodeError:
        return ErrorResult(
            "error", "validation", "Description must be UTF-8 encodable."
        )
    if description_size > _MAX_DESCRIPTION_SIZE:
        return ErrorResult(
            "error",
            "validation",
            f"Description exceeds maximum size of {_MAX_DESCRIPTION_SIZE} bytes.",
        )
    if is_mock_mode():
        from aristotle_mcp.mock_workflows import formalize as mock_formalize

        return await mock_formalize(description, prove, context_file, wait)
    if not description.strip():
        return ErrorResult("error", "validation", "description is required")
    try:
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, "description.txt"), "w", encoding="utf-8") as file:
                file.write(description)
            contexts = [context_file] if context_file is not None else []
            _stage_context_files(directory, contexts, {"description.txt"})
            suffix = " and prove it" if prove else ""
            prompt = (
                f"Formalize the provided description{suffix} and save the Lean result "
                "as formalize.lean."
            )
            return await _submit_and_wait(
                directory, prompt, wait, preferred_filename="formalize.lean"
            )
    except (OSError, ValueError) as error:
        return error_result(error)
