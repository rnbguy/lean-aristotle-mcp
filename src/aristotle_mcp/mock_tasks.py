"""Native-shaped in-memory AgentTask operations."""

from __future__ import annotations

import math

from aristotlelib import EventStatus, EventType, ProjectStatus, TaskStatus

from aristotle_mcp.mock_state import MockEvent, MockTask, now, state
from aristotle_mcp.models import (
    ErrorResult,
    EventResult,
    TaskListResult,
    TaskResult,
    WaitTaskResult,
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


async def list_project_tasks(
    project_id: str,
    pagination_key: str | None = None,
    limit: int = 10,
    newest_first: bool = True,
) -> TaskListResult | ErrorResult:
    if not 1 <= limit <= 100:
        return _error("limit must be between 1 and 100")
    try:
        offset = 0 if pagination_key is None else int(pagination_key)
    except ValueError:
        return _error("pagination_key must be an integer offset")
    with state.lock:
        project = state.projects.get(project_id)
        if project is None:
            return _error(f"Unknown project ID: {project_id}")
        task_ids = list(reversed(project.task_ids)) if newest_first else project.task_ids
        task_ids = task_ids[offset : offset + limit]
        next_key = str(offset + limit) if offset + limit < len(project.task_ids) else None
        tasks = [_task_result(state.tasks[task_id]) for task_id in task_ids]
        return TaskListResult(tasks, next_key)


async def get_task(task_id: str) -> TaskResult | ErrorResult:
    with state.lock:
        task = state.tasks.get(task_id)
        return _task_result(task) if task is not None else _error(f"Unknown task ID: {task_id}")


async def wait_task(
    task_id: str,
    timeout_seconds: float = 300.0,
    poll_interval_seconds: float = 5.0,
) -> WaitTaskResult | ErrorResult:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        return _error("timeout_seconds must be finite and positive")
    if not math.isfinite(poll_interval_seconds) or poll_interval_seconds <= 0:
        return _error("poll_interval_seconds must be finite and positive")
    with state.lock:
        task = state.tasks.get(task_id)
        if task is None:
            return _error(f"Unknown task ID: {task_id}")
        if task.status not in _terminal_statuses():
            question = _unanswered_question(task)
            if question is not None:
                return WaitTaskResult(
                    "waiting_for_answer", _task_result(task), question, "Task is waiting for an answer."
                )
            return WaitTaskResult(
                "timed_out",
                _task_result(task),
                None,
                "Task did not reach a terminal state before the timeout.",
            )
        project = state.projects.get(task.project_id)
        if project is not None:
            project.status = ProjectStatus.IDLE
        return WaitTaskResult(
            "terminal",
            _task_result(task),
            None,
            "Task reached a terminal status.",
        )


def _terminal_statuses() -> frozenset[TaskStatus]:
    return frozenset(
        {
            TaskStatus.COMPLETE,
            TaskStatus.COMPLETE_WITH_ERRORS,
            TaskStatus.OUT_OF_BUDGET,
            TaskStatus.FAILED,
            TaskStatus.CANCELED,
        }
    )


def _unanswered_question(task: MockTask) -> EventResult | None:
    questions = [
        state.events[event_id]
        for event_id in task.event_ids
        if state.events[event_id].event_type is EventType.AGENT_QUESTION
        and state.events[event_id].status is EventStatus.SENT
        and state.events[event_id].explanation is None
    ]
    if not questions:
        return None
    event: MockEvent = questions[-1]
    return EventResult(
        event.event_id,
        event.agent_task_id,
        event.event_type.name.lower(),
        event.status.name.lower(),
        event.created_at.isoformat(),
        event.content,
        event.file_path,
        event.explanation,
        event.suggestions,
        event.duration_seconds,
    )


async def cancel_task(task_id: str) -> TaskResult | ErrorResult:
    with state.lock:
        task = state.tasks.get(task_id)
        if task is None:
            return _error(f"Unknown task ID: {task_id}")
        task.status = TaskStatus.CANCELED
        task.percent_complete = 100
        task.last_updated_at = now()
        project = state.projects.get(task.project_id)
        if project is not None:
            project.status = ProjectStatus.IDLE
        return _task_result(task)
