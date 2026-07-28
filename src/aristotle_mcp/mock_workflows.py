"""Native-shaped mock proof and formalization workflows."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Final

from aristotle_mcp.errors import error_result
from aristotle_mcp.files import (
    _best_effort_remove,
    _canonicalize_path,
    _lake_root,
    _reserve_output_path,
    _stage_context_files,
)
from aristotle_mcp.mock_projects import submit_project
from aristotle_mcp.mock_tasks import wait_task
from aristotle_mcp.models import ErrorResult, WorkflowResult

_OUTPUT_STATUSES: Final = frozenset({"complete", "complete_with_errors", "out_of_budget"})


async def _submit(
    directory: str,
    prompt: str,
    wait: bool,
    code: str | None,
    output_path: str | None,
) -> WorkflowResult | ErrorResult:
    reserved: str | None = None
    if output_path is not None:
        try:
            reserved = _reserve_output_path(output_path)
        except FileExistsError as error:
            return ErrorResult("error", "filesystem", str(error))
    try:
        submission = await submit_project(prompt, project_dir=directory)
        if isinstance(submission, ErrorResult):
            return submission
        project, task = submission
        if task is None:
            return ErrorResult("error", "api", "Submitted project has no task")
        if not wait:
            return WorkflowResult(
                task.status,
                project.project_id,
                task.task_id,
                None,
                None,
                task.output_summary,
                "Project submitted.",
            )
        waited = await wait_task(task.task_id)
        if isinstance(waited, ErrorResult):
            return waited
        if waited.outcome != "terminal" or waited.task.status not in _OUTPUT_STATUSES:
            return WorkflowResult(
                waited.task.status,
                project.project_id,
                waited.task.task_id,
                None,
                None,
                waited.task.output_summary,
                waited.message,
            )
        if reserved is not None:
            try:
                Path(reserved).write_text(code or "", encoding="utf-8")
            except OSError as error:
                return ErrorResult("error", "filesystem", str(error))
            completed_output = reserved
            reserved = None
            return WorkflowResult(
                waited.task.status,
                project.project_id,
                task.task_id,
                None,
                completed_output,
                waited.task.output_summary,
                "Workflow completed.",
            )
        return WorkflowResult(
            waited.task.status,
            project.project_id,
            task.task_id,
            code,
            None,
            waited.task.output_summary,
            "Workflow completed.",
        )
    finally:
        if reserved is not None:
            _best_effort_remove(reserved)


async def prove(
    code: str,
    context_files: list[str] | None = None,
    hint: str | None = None,
    wait: bool = True,
) -> WorkflowResult | ErrorResult:
    if not code.strip():
        return ErrorResult("error", "validation", "code is required")
    try:
        directory = tempfile.mkdtemp()
        try:
            path = Path(directory) / "proof.lean"
            text = f"-- Hint: {hint}\n{code}" if hint is not None else code
            path.write_text(text, encoding="utf-8")
            _stage_context_files(directory, context_files or [], {"proof.lean"})
            return await _submit(directory, "Please prove all sorry statements.", wait, code, None)
        finally:
            _best_effort_remove(directory, recursive=True)
    except (OSError, ValueError) as error:
        return ErrorResult("error", "validation", str(error))


async def prove_file(
    file_path: str,
    output_path: str | None = None,
    wait: bool = True,
) -> WorkflowResult | ErrorResult:
    canonical = _canonicalize_path(file_path)
    if not os.path.isfile(canonical):
        return ErrorResult("error", "validation", f"File not found: {file_path}")
    try:
        code = Path(canonical).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ErrorResult("error", "validation", "File must be valid UTF-8.")
    except OSError as error:
        return error_result(error)
    final_output = output_path or f"{os.path.splitext(canonical)[0]}_aristotle.lean"
    lake_root = _lake_root(canonical)
    source_path = os.path.relpath(canonical, lake_root).replace(os.sep, "/")
    prompt = f"Please prove all sorry statements in {source_path}."
    return await _submit(
        lake_root,
        prompt,
        wait,
        code,
        _canonicalize_path(final_output) if wait else None,
    )


async def formalize(
    description: str,
    prove: bool = False,
    context_file: str | None = None,
    wait: bool = True,
) -> WorkflowResult | ErrorResult:
    if not description.strip():
        return ErrorResult("error", "validation", "description is required")
    try:
        directory = tempfile.mkdtemp()
        try:
            path = Path(directory) / "description.txt"
            path.write_text(description, encoding="utf-8")
            contexts = [context_file] if context_file is not None else []
            _stage_context_files(directory, contexts, {"description.txt"})
            proof = "by trivial" if prove else "by sorry"
            code = f"theorem formalized : True := {proof}\n"
            suffix = " and prove it" if prove else ""
            prompt = (
                f"Formalize the provided description{suffix} and save the Lean result "
                "as formalize.lean."
            )
            return await _submit(directory, prompt, wait, code, None)
        finally:
            _best_effort_remove(directory, recursive=True)
    except (OSError, ValueError) as error:
        return ErrorResult("error", "validation", str(error))
