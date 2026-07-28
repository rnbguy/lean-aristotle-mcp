from datetime import UTC, datetime

import pytest
from aristotlelib import EventStatus, EventType, TaskStatus

from aristotle_mcp.events import answer_question, get_event, list_task_events
from aristotle_mcp.mock_state import MockEvent, MockTask, reset_state, state
from aristotle_mcp.models import ErrorResult


@pytest.fixture(autouse=True)
def mock_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "true")
    reset_state()


@pytest.mark.asyncio
async def test_events_are_paginated_and_answered() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    task = MockTask(
        "project-1",
        "task-1",
        TaskStatus.IN_PROGRESS,
        timestamp,
        timestamp,
        0,
        None,
        None,
        None,
    )
    event = MockEvent(
        "event-1",
        task.agent_task_id,
        EventType.AGENT_QUESTION,
        timestamp,
        "Which strategy?",
        None,
        None,
        ["induction"],
        EventStatus.SENT,
        None,
    )
    state.tasks[task.agent_task_id] = task
    state.events[event.event_id] = event
    task.event_ids.append(event.event_id)

    listed = await list_task_events(task.agent_task_id)
    answered = await answer_question(event.event_id, "induction")
    fetched = await get_event(event.event_id)

    assert not isinstance(listed, ErrorResult)
    assert listed.events[0].event_type == "agent_question"
    assert not isinstance(answered, ErrorResult)
    assert answered.status == "complete"
    assert not isinstance(fetched, ErrorResult)
    assert fetched.explanation == "induction"


@pytest.mark.asyncio
async def test_list_task_events_rejects_negative_pagination_offset() -> None:
    task = MockTask(
        "project-1",
        "task-1",
        TaskStatus.IN_PROGRESS,
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
        0,
        None,
        None,
        None,
    )
    state.tasks[task.agent_task_id] = task

    result = await list_task_events(task.agent_task_id, pagination_key="-1")

    assert result == ErrorResult(
        "error", "validation", "pagination_key must be a non-negative integer offset"
    )


@pytest.mark.asyncio
async def test_answer_rejects_missing_or_non_question_events() -> None:
    missing = await answer_question("missing", "yes")

    assert isinstance(missing, ErrorResult)
    assert missing.error_type == "validation"
