"""Native AgentTask operations for Aristotle MCP."""

from __future__ import annotations

import math
import time

import anyio
from aristotlelib import (
    AgentTask,
    AristotleAPIError,
    Event,
    EventStatus,
    EventType,
    Project,
    TaskStatus,
)

from aristotle_mcp.config import is_mock_mode
from aristotle_mcp.errors import error_result
from aristotle_mcp.models import (
    ErrorResult,
    EventResult,
    TaskListResult,
    TaskResult,
    WaitTaskResult,
)

_TERMINAL_STATUSES = frozenset(
    {
        TaskStatus.COMPLETE,
        TaskStatus.COMPLETE_WITH_ERRORS,
        TaskStatus.OUT_OF_BUDGET,
        TaskStatus.FAILED,
        TaskStatus.CANCELED,
    }
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


def _event_result(event: Event) -> EventResult:
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


async def list_project_tasks(
    project_id: str,
    pagination_key: str | None = None,
    limit: int = 10,
    newest_first: bool = True,
) -> TaskListResult | ErrorResult:
    if is_mock_mode():
        from aristotle_mcp.mock_tasks import list_project_tasks as list_mock_project_tasks

        return await list_mock_project_tasks(project_id, pagination_key, limit, newest_first)
    try:
        project = await Project.from_id(project_id)
        tasks, next_key = await project.get_tasks(pagination_key, limit, newest_first)
        return TaskListResult([_task_result(task) for task in tasks], next_key)
    except (AristotleAPIError, OSError, ValueError) as error:
        return error_result(error)


async def get_task(task_id: str) -> TaskResult | ErrorResult:
    if is_mock_mode():
        from aristotle_mcp.mock_tasks import get_task as get_mock_task

        return await get_mock_task(task_id)
    try:
        task = await AgentTask.from_id(task_id)
        await task.refresh()
        return _task_result(task)
    except (AristotleAPIError, OSError, ValueError) as error:
        return error_result(error)


async def _unanswered_question(task: AgentTask, deadline: float) -> tuple[EventResult | None, bool]:
    pagination_key: str | None = None
    newest: Event | None = None
    while time.monotonic() < deadline:
        events: list[Event] = []
        with anyio.move_on_after(deadline - time.monotonic()) as scope:
            events, pagination_key = await task.get_events(pagination_key, 100, True)
        if scope.cancelled_caught:
            return None, True
        if time.monotonic() >= deadline:
            return None, True
        for event in events:
            if (
                event.event_type is EventType.AGENT_QUESTION
                and event.status is EventStatus.SENT
                and event.explanation is None
                and (newest is None or event.created_at > newest.created_at)
            ):
                newest = event
        if pagination_key is None:
            return _event_result(newest) if newest is not None else None, False
    return None, True


def _timed_out(task: TaskResult) -> WaitTaskResult:
    return WaitTaskResult(
        "timed_out",
        task,
        None,
        "Task did not reach a terminal state before the timeout.",
    )


async def wait_task(
    task_id: str,
    timeout_seconds: float = 300.0,
    poll_interval_seconds: float = 5.0,
) -> WaitTaskResult | ErrorResult:
    """Wait with bounded polling, never using the SDK interactive waiter."""
    if is_mock_mode():
        from aristotle_mcp.mock_tasks import wait_task as wait_mock_task

        return await wait_mock_task(task_id, timeout_seconds, poll_interval_seconds)
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        return ErrorResult("error", "validation", "timeout_seconds must be finite and positive")
    if not math.isfinite(poll_interval_seconds) or poll_interval_seconds <= 0:
        return ErrorResult(
            "error",
            "validation",
            "poll_interval_seconds must be finite and positive",
        )
    try:
        deadline = time.monotonic() + timeout_seconds
        task: AgentTask | None = None
        with anyio.move_on_after(deadline - time.monotonic()) as scope:
            task = await AgentTask.from_id(task_id)
        if scope.cancelled_caught:
            return ErrorResult(
                "error", "api", "Task lookup timed out before a TaskResult was available."
            )
        assert task is not None
        while time.monotonic() < deadline:
            with anyio.move_on_after(deadline - time.monotonic()) as scope:
                await task.refresh()
            if scope.cancelled_caught:
                return _timed_out(_task_result(task))
            result = _task_result(task)
            if task.status in _TERMINAL_STATUSES:
                return WaitTaskResult(
                    "terminal",
                    result,
                    None,
                    f"Task reached terminal status: {result.status}.",
                )
            question, expired = await _unanswered_question(task, deadline)
            if expired:
                return _timed_out(result)
            if question is not None:
                return WaitTaskResult(
                    "waiting_for_answer",
                    result,
                    question,
                    "Task is waiting for an answer.",
                )
            remaining = deadline - time.monotonic()
            if remaining > 0:
                await anyio.sleep(min(poll_interval_seconds, remaining))
        return _timed_out(_task_result(task))
    except (AristotleAPIError, OSError, ValueError) as error:
        return error_result(error)


async def cancel_task(task_id: str) -> TaskResult | ErrorResult:
    if is_mock_mode():
        from aristotle_mcp.mock_tasks import cancel_task as cancel_mock_task

        return await cancel_mock_task(task_id)
    try:
        task = await AgentTask.from_id(task_id)
        await task.cancel()
        return _task_result(task)
    except (AristotleAPIError, OSError, ValueError) as error:
        return error_result(error)
