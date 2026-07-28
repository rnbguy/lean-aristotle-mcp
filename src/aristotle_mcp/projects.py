"""Native Project operations for the Aristotle MCP surface."""

from __future__ import annotations

import os
import tarfile
import tempfile
from pathlib import Path

from aristotlelib import (
    AgentQuestionsSetting,
    AgentTask,
    AristotleAPIError,
    FollowUpMode,
    Project,
    ProjectStatus,
)
from aristotlelib.local_file_utils import LeanProjectError

from aristotle_mcp.config import is_mock_mode
from aristotle_mcp.errors import error_result
from aristotle_mcp.files import _remove_reserved_path, _reserve_download_path
from aristotle_mcp.models import (
    ErrorResult,
    ProjectFilesResult,
    ProjectListResult,
    ProjectResult,
    TaskResult,
)


def _project_result(project: Project) -> ProjectResult:
    return ProjectResult(
        project.project_id,
        project.status.name.lower(),
        project.created_at.isoformat(),
        project.last_updated.isoformat(),
        project.description,
        project.has_input,
        project.has_files,
    )


def _task_result(task: AgentTask) -> TaskResult:
    return TaskResult(
        task.project_id,
        task.agent_task_id,
        task.status.value.lower(),
        task.created_at.isoformat(),
        task.last_updated_at.isoformat(),
        task.percent_complete,
        task.file_name,
        task.description,
        task.output_summary,
    )


def _validate_source(project_dir: str | None, tar_file_path: str | None) -> None:
    if project_dir is not None and tar_file_path is not None:
        raise ValueError("Provide either project_dir or tar_file_path, not both")
    if project_dir is not None and not os.path.isdir(project_dir):
        raise ValueError("project_dir must be an existing directory")
    if tar_file_path is not None and not tarfile.is_tarfile(tar_file_path):
        raise ValueError("tar_file_path must be a valid tar archive")


async def submit_project(
    prompt: str,
    project_dir: str | None = None,
    tar_file_path: str | None = None,
    public_file_path: str | None = None,
    agent_questions_setting: AgentQuestionsSetting = AgentQuestionsSetting.DISABLED,
) -> tuple[ProjectResult, TaskResult | None] | ErrorResult:
    """Submit a Project and return its initial AgentTask when available."""
    try:
        _validate_source(project_dir, tar_file_path)
        if is_mock_mode():
            from aristotle_mcp.mock_projects import submit_project as submit

            return await submit(
                prompt,
                project_dir,
                tar_file_path,
                public_file_path,
                agent_questions_setting,
            )
        project = (
            await Project.create_from_directory(prompt, project_dir, agent_questions_setting)
            if project_dir is not None
            else await Project.create(
                prompt,
                tar_file_path,
                public_file_path,
                agent_questions_setting,
            )
        )
        tasks, _ = await project.get_tasks(limit=1, newest_first=True)
        return _project_result(project), _task_result(tasks[0]) if tasks else None
    except (AristotleAPIError, LeanProjectError, OSError, tarfile.TarError, ValueError) as error:
        return error_result(error)


async def list_projects(
    pagination_key: str | None = None,
    limit: int = 30,
    status: ProjectStatus | list[ProjectStatus] | None = None,
) -> ProjectListResult | ErrorResult:
    """List Projects in native newest-first order."""
    if is_mock_mode():
        from aristotle_mcp.mock_projects import list_projects as list_mock_projects

        return await list_mock_projects(pagination_key, limit, status)
    try:
        projects, next_key = await Project.list_projects(pagination_key, limit, status)
        return ProjectListResult([_project_result(project) for project in projects], next_key)
    except (AristotleAPIError, OSError, ValueError) as error:
        return error_result(error)


async def get_project(project_id: str) -> ProjectResult | ErrorResult:
    if is_mock_mode():
        from aristotle_mcp.mock_projects import get_project as get_mock_project

        return await get_mock_project(project_id)
    try:
        project = await Project.from_id(project_id)
        await project.refresh()
        return _project_result(project)
    except (AristotleAPIError, OSError, ValueError) as error:
        return error_result(error)


async def continue_project(
    project_id: str,
    prompt: str,
    files: list[str] | None = None,
    agent_questions_setting: AgentQuestionsSetting = AgentQuestionsSetting.DISABLED,
) -> TaskResult | ErrorResult:
    try:
        if is_mock_mode():
            from aristotle_mcp.mock_projects import continue_project as continue_mock_project

            return await continue_mock_project(project_id, prompt, files, agent_questions_setting)
        project = await Project.from_id(project_id)
        uploaded_files: list[Path | str] = []
        if files is not None:
            uploaded_files.extend(files)
        task = await project.ask(
            prompt,
            FollowUpMode.INSTRUCT,
            uploaded_files or None,
            agent_questions_setting,
        )
        return _task_result(task)
    except (AristotleAPIError, OSError, ValueError) as error:
        return error_result(error)


async def ask_project(
    project_id: str,
    prompt: str,
    agent_questions_setting: AgentQuestionsSetting = AgentQuestionsSetting.DISABLED,
) -> TaskResult | ErrorResult:
    if is_mock_mode():
        from aristotle_mcp.mock_projects import ask_project as ask_mock_project

        return await ask_mock_project(project_id, prompt, agent_questions_setting)
    try:
        project = await Project.from_id(project_id)
        task = await project.ask(prompt, FollowUpMode.ASK, None, agent_questions_setting)
        return _task_result(task)
    except (AristotleAPIError, OSError, ValueError) as error:
        return error_result(error)


async def download_project_files(
    project_id: str,
    output_path: str | None = None,
    overwrite: bool = False,
) -> ProjectFilesResult | ErrorResult:
    """Atomically save native Project files without accidental overwrites."""
    if is_mock_mode():
        from aristotle_mcp.mock_projects import (
            download_project_files as download_mock_project_files,
        )

        return await download_mock_project_files(project_id, output_path, overwrite)
    reserved = False
    committed = False
    temporary_path: str | None = None
    destination = ""
    try:
        destination, reserved = _reserve_download_path(
            project_id,
            output_path,
            ".tar.gz",
            overwrite,
        )
        project = await Project.from_id(project_id)
        descriptor, temporary_path = tempfile.mkstemp(
            dir=os.path.dirname(destination) or ".",
            prefix=f".{os.path.basename(destination)}.",
        )
        os.close(descriptor)
        await project.get_files(temporary_path)
        os.replace(temporary_path, destination)
        temporary_path = None
        committed = True
        return ProjectFilesResult("complete", project_id, destination, "Project files downloaded")
    except (AristotleAPIError, OSError, tarfile.TarError, ValueError) as error:
        return error_result(error)
    finally:
        if temporary_path is not None and os.path.exists(temporary_path):
            os.unlink(temporary_path)
        _remove_reserved_path(destination, reserved and not committed)
