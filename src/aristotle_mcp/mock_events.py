"""Native-shaped in-memory Event operations."""

from __future__ import annotations

from aristotlelib import EventStatus, EventType

from aristotle_mcp.mock_state import MockEvent, now, state
from aristotle_mcp.models import ErrorResult, EventListResult, EventResult


def _event_result(event: MockEvent) -> EventResult:
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


def _error(message: str) -> ErrorResult:
    return ErrorResult("error", "validation", message)


async def list_task_events(
    task_id: str,
    pagination_key: str | None = None,
    limit: int = 50,
    newest_first: bool = True,
) -> EventListResult | ErrorResult:
    if not 1 <= limit <= 100:
        return _error("limit must be between 1 and 100")
    try:
        offset = 0 if pagination_key is None else int(pagination_key)
    except ValueError:
        return _error("pagination_key must be an integer offset")
    with state.lock:
        task = state.tasks.get(task_id)
        if task is None:
            return _error(f"Unknown task ID: {task_id}")
        event_ids = list(reversed(task.event_ids)) if newest_first else task.event_ids
        page = event_ids[offset : offset + limit]
        next_key = str(offset + limit) if offset + limit < len(event_ids) else None
        events = [_event_result(state.events[event_id]) for event_id in page]
        return EventListResult(events, next_key)


async def get_event(event_id: str) -> EventResult | ErrorResult:
    with state.lock:
        event = state.events.get(event_id)
        if event is None:
            return _error(f"Unknown event ID: {event_id}")
        return _event_result(event)


async def answer_question(event_id: str, answer: str) -> EventResult | ErrorResult:
    if not answer.strip():
        return _error("answer is required")
    with state.lock:
        event = state.events.get(event_id)
        if event is None:
            return _error(f"Unknown event ID: {event_id}")
        if event.event_type is not EventType.AGENT_QUESTION:
            return _error("Can only answer AGENT_QUESTION events")
        if event.explanation is not None:
            return _error("This question has already been answered")
        if event.status is not EventStatus.SENT:
            return _error("This question timed out. The agent did what it thought was best.")
        event.explanation = answer
        event.status = EventStatus.COMPLETE
        event.duration_seconds = (now() - event.created_at).total_seconds()
        return _event_result(event)
