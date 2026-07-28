"""Native-shaped in-memory Project operations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import assert_never

from aristotlelib import AgentQuestionsSetting, EventStatus, EventType, ProjectStatus, TaskStatus

from aristotle_mcp.mock_downloads import download_project_files as _download_project_files
from aristotle_mcp.mock_files import collect_directory_files
from aristotle_mcp.mock_state import MockEvent, MockProject, MockTask, new_id, now, state
from aristotle_mcp.models import (
    ErrorResult,
    ProjectFilesResult,
    ProjectListResult,
    ProjectResult,
    TaskResult,
)


def _project_result(project: MockProject) -> ProjectResult:
    return ProjectResult(
        project.project_id,
        project.status.name.lower(),
        project.created_at.isoformat(),
        project.last_updated.isoformat(),
        project.description,
        project.has_input,
        project.has_files,
    )


def _task_result(task: MockTask) -> TaskResult:
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


def _error(message: str) -> ErrorResult:
    return ErrorResult("error", "validation", message)


def _created_at(project: MockProject) -> datetime:
    return project.created_at


def _add_task(
    project: MockProject, prompt: str, agent_questions_setting: AgentQuestionsSetting
) -> MockTask:
    timestamp = now()
    task = MockTask(
        project.project_id,
        new_id("task"),
        TaskStatus.QUEUED,
        timestamp,
        timestamp,
        0,
        None,
        prompt,
        None,
    )
    event = MockEvent(
        new_id("event"),
        task.agent_task_id,
        EventType.MESSAGE,
        timestamp,
        prompt,
        None,
        None,
        None,
        EventStatus.COMPLETE,
        None,
    )
    project.task_ids.append(task.agent_task_id)
    project.status = ProjectStatus.RUNNING
    project.last_updated = timestamp
    state.tasks[task.agent_task_id] = task
    state.events[event.event_id] = event
    task.event_ids.append(event.event_id)
    match agent_questions_setting:
        case AgentQuestionsSetting.DISABLED:
            pass
        case AgentQuestionsSetting.TIMEOUT_15_MIN:
            question = MockEvent(
                new_id("event"),
                task.agent_task_id,
                EventType.AGENT_QUESTION,
                timestamp,
                "What additional guidance should I use?",
                None,
                None,
                None,
                EventStatus.SENT,
                None,
            )
            state.events[question.event_id] = question
            task.event_ids.append(question.event_id)
        case unreachable:
            assert_never(unreachable)
    return task


def _files(project_dir: str | None, tar_file_path: str | None) -> dict[str, bytes]:
    if project_dir is not None:
        return collect_directory_files(Path(project_dir))
    if tar_file_path is not None:
        return {Path(tar_file_path).name: Path(tar_file_path).read_bytes()}
    return {}


async def submit_project(
    prompt: str,
    project_dir: str | None = None,
    tar_file_path: str | None = None,
    public_file_path: str | None = None,
    agent_questions_setting: AgentQuestionsSetting = AgentQuestionsSetting.DISABLED,
) -> tuple[ProjectResult, TaskResult | None] | ErrorResult:
    """Create a mock project and initial AgentTask."""
    if not prompt.strip():
        return _error("prompt is required")
    _ = public_file_path
    timestamp = now()
    files = _files(project_dir, tar_file_path)
    project = MockProject(
        new_id("project"),
        timestamp,
        timestamp,
        prompt,
        ProjectStatus.IDLE,
        project_dir is not None or tar_file_path is not None,
        bool(files),
        files,
    )
    with state.lock:
        state.projects[project.project_id] = project
        task = _add_task(project, prompt, agent_questions_setting)
    return _project_result(project), _task_result(task)


async def list_projects(
    pagination_key: str | None = None,
    limit: int = 30,
    status: ProjectStatus | list[ProjectStatus] | None = None,
) -> ProjectListResult | ErrorResult:
    """Return a page of mock projects in native order."""
    if not 1 <= limit <= 100:
        return _error("limit must be between 1 and 100")
    try:
        offset = 0 if pagination_key is None else int(pagination_key)
    except ValueError:
        return _error("pagination_key must be an integer offset")
    statuses = status if isinstance(status, list) else [status] if status is not None else []
    with state.lock:
        projects = sorted(state.projects.values(), key=_created_at, reverse=True)
        if statuses:
            projects = [project for project in projects if project.status in statuses]
        page = projects[offset : offset + limit]
        next_key = str(offset + limit) if offset + limit < len(projects) else None
        return ProjectListResult([_project_result(project) for project in page], next_key)


async def get_project(project_id: str) -> ProjectResult | ErrorResult:
    with state.lock:
        project = state.projects.get(project_id)
        if project is None:
            return _error(f"Unknown project ID: {project_id}")
        return _project_result(project)


async def continue_project(
    project_id: str,
    prompt: str,
    files: list[str] | None = None,
    agent_questions_setting: AgentQuestionsSetting = AgentQuestionsSetting.DISABLED,
) -> TaskResult | ErrorResult:
    """Create an INSTRUCT task, accepting files only while idle."""
    if not prompt.strip():
        return _error("prompt is required")
    with state.lock:
        project = state.projects.get(project_id)
        if project is None:
            return _error(f"Unknown project ID: {project_id}")
        if files and project.status is not ProjectStatus.IDLE:
            return _error("Files can only be uploaded when the project is idle")
        if files:
            for path in files:
                file_path = Path(path)
                if not file_path.is_file():
                    return _error(f"Source path is not a file: {file_path}")
                project.source_files[file_path.name] = file_path.read_bytes()
            project.has_files = True
        return _task_result(_add_task(project, prompt, agent_questions_setting))


async def ask_project(
    project_id: str,
    prompt: str,
    agent_questions_setting: AgentQuestionsSetting = AgentQuestionsSetting.DISABLED,
) -> TaskResult | ErrorResult:
    if not prompt.strip():
        return _error("prompt is required")
    with state.lock:
        project = state.projects.get(project_id)
        return (
            _task_result(_add_task(project, prompt, agent_questions_setting))
            if project is not None
            else _error(f"Unknown project ID: {project_id}")
        )


async def download_project_files(
    project_id: str,
    output_path: str | None = None,
    overwrite: bool = False,
) -> ProjectFilesResult | ErrorResult:
    """Delegate mock archive downloads while retaining the public project surface."""
    return await _download_project_files(project_id, output_path, overwrite)
