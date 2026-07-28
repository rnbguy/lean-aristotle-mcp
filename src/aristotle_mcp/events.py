"""Native Event operations for Aristotle MCP."""

from __future__ import annotations

from aristotlelib import AgentTask, AristotleAPIError, Event

from aristotle_mcp.config import is_mock_mode
from aristotle_mcp.errors import error_result
from aristotle_mcp.models import ErrorResult, EventListResult, EventResult


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


async def list_task_events(
    task_id: str,
    pagination_key: str | None = None,
    limit: int = 50,
    newest_first: bool = True,
) -> EventListResult | ErrorResult:
    if is_mock_mode():
        from aristotle_mcp.mock_events import list_task_events as list_mock_task_events

        return await list_mock_task_events(task_id, pagination_key, limit, newest_first)
    try:
        task = await AgentTask.from_id(task_id)
        events, next_key = await task.get_events(pagination_key, limit, newest_first)
        return EventListResult([_event_result(event) for event in events], next_key)
    except (AristotleAPIError, OSError, ValueError) as error:
        return error_result(error)


async def get_event(event_id: str) -> EventResult | ErrorResult:
    if is_mock_mode():
        from aristotle_mcp.mock_events import get_event as get_mock_event

        return await get_mock_event(event_id)
    try:
        event = await Event.from_id(event_id)
        await event.refresh()
        return _event_result(event)
    except (AristotleAPIError, OSError, ValueError) as error:
        return error_result(error)


async def answer_question(event_id: str, answer: str) -> EventResult | ErrorResult:
    if is_mock_mode():
        from aristotle_mcp.mock_events import answer_question as answer_mock_question

        return await answer_mock_question(event_id, answer)
    if not answer.strip():
        return ErrorResult("error", "validation", "answer is required")
    try:
        event = await Event.from_id(event_id)
        await event.answer(answer)
        return _event_result(event)
    except (AristotleAPIError, OSError, ValueError) as error:
        return error_result(error)
