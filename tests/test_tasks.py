from datetime import UTC, datetime
from types import SimpleNamespace

import anyio
import pytest
from aristotlelib import EventStatus, EventType, TaskStatus

from aristotle_mcp import tasks
from aristotle_mcp.mock_state import MockEvent, reset_state, state
from aristotle_mcp.models import ErrorResult
from aristotle_mcp.projects import submit_project
from aristotle_mcp.tasks import cancel_task, get_task, list_project_tasks, wait_task


@pytest.fixture(autouse=True)
def mock_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "true")
    reset_state()


@pytest.mark.asyncio
async def test_task_lifecycle_uses_native_task_id() -> None:
    submission = await submit_project("Prove the theorem")

    assert not isinstance(submission, ErrorResult)
    project, task = submission
    assert task is not None
    listed = await list_project_tasks(project.project_id)
    waited = await wait_task(task.task_id, timeout_seconds=1, poll_interval_seconds=1)
    canceled = await cancel_task(task.task_id)
    fetched = await get_task(task.task_id)

    assert not isinstance(listed, ErrorResult)
    assert listed.tasks[0].task_id == task.task_id
    assert not isinstance(waited, ErrorResult)
    assert waited.outcome == "timed_out"
    assert not isinstance(canceled, ErrorResult)
    assert canceled.status == "canceled"
    assert not isinstance(fetched, ErrorResult)
    assert fetched.task_id == task.task_id


@pytest.mark.asyncio
async def test_wait_rejects_nonfinite_deadline() -> None:
    result = await wait_task("missing", timeout_seconds=float("nan"))

    assert isinstance(result, ErrorResult)
    assert "finite" in result.message


@pytest.mark.asyncio
async def test_mock_wait_reports_pending_question_and_timeout() -> None:
    submission = await submit_project("Prove the theorem")
    assert not isinstance(submission, ErrorResult)
    _, task = submission
    assert task is not None
    state.events["question"] = MockEvent(
        "question", task.task_id, EventType.AGENT_QUESTION, state.tasks[task.task_id].created_at,
        "Need a lemma", None, None, None, EventStatus.SENT, None,
    )
    state.tasks[task.task_id].event_ids.append("question")

    question = await wait_task(task.task_id, timeout_seconds=1, poll_interval_seconds=1)
    state.events["question"].status = EventStatus.COMPLETE
    state.tasks[task.task_id].status = TaskStatus.QUEUED
    timed_out = await wait_task(task.task_id, timeout_seconds=1, poll_interval_seconds=1)

    assert not isinstance(question, ErrorResult)
    assert question.outcome == "waiting_for_answer"
    assert not isinstance(timed_out, ErrorResult)
    assert timed_out.outcome == "timed_out"


@pytest.mark.asyncio
async def test_wait_cancels_slow_refresh_at_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    task = SimpleNamespace(
        project_id="project",
        agent_task_id="task",
        status=TaskStatus.QUEUED,
        created_at=timestamp,
        last_updated_at=timestamp,
        percent_complete=0,
        file_name=None,
        description=None,
        output_summary=None,
    )

    async def refresh() -> None:
        await anyio.sleep(10)

    async def from_id(task_id: str) -> SimpleNamespace:
        assert task_id == "task"
        return task

    task.refresh = refresh
    monkeypatch.setattr(tasks.AgentTask, "from_id", from_id)
    result = await tasks.wait_task("task", timeout_seconds=0.01, poll_interval_seconds=1)

    assert not isinstance(result, ErrorResult)
    assert result.outcome == "timed_out"


@pytest.mark.asyncio
async def test_wait_returns_error_when_task_lookup_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")

    async def from_id(task_id: str) -> SimpleNamespace:
        assert task_id == "task"
        await anyio.sleep(10)
        return SimpleNamespace()

    monkeypatch.setattr(tasks.AgentTask, "from_id", from_id)
    result = await tasks.wait_task("task", timeout_seconds=0.01, poll_interval_seconds=1)

    assert isinstance(result, ErrorResult)
    assert result.error_type == "api"
    assert result.message == "Task lookup timed out before a TaskResult was available."
