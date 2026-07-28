from datetime import UTC, datetime
from types import SimpleNamespace

import anyio
import pytest
from aristotlelib import AgentQuestionsSetting, EventStatus, EventType, ProjectStatus, TaskStatus

from aristotle_mcp import tasks
from aristotle_mcp.events import answer_question, get_event, list_task_events
from aristotle_mcp.mock_state import MockEvent, reset_state, state
from aristotle_mcp.models import ErrorResult
from aristotle_mcp.projects import ask_project, continue_project, submit_project
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
async def test_timeout_question_setting_supports_public_answer_lifecycle() -> None:
    submission = await submit_project(
        "Prove the theorem",
        agent_questions_setting=AgentQuestionsSetting.TIMEOUT_15_MIN,
    )

    assert not isinstance(submission, ErrorResult)
    _, task = submission
    assert task is not None
    first_wait = await wait_task(task.task_id, timeout_seconds=1, poll_interval_seconds=1)
    listed = await list_task_events(task.task_id)
    assert not isinstance(first_wait, ErrorResult)
    assert first_wait.outcome == "waiting_for_answer"
    assert first_wait.question is not None
    assert not isinstance(listed, ErrorResult)
    assert [event.event_type for event in listed.events] == ["agent_question", "message"]
    assert listed.events[0].status == "sent"
    answered = await answer_question(first_wait.question.event_id, "Use induction")
    fetched = await get_event(first_wait.question.event_id)
    second_wait = await wait_task(task.task_id, timeout_seconds=1, poll_interval_seconds=1)

    assert not isinstance(answered, ErrorResult)
    assert answered.status == "complete"
    assert answered.explanation == "Use induction"
    assert not isinstance(fetched, ErrorResult)
    assert fetched.event_id == first_wait.question.event_id
    assert fetched.status == "complete"
    assert fetched.explanation == "Use induction"
    assert not isinstance(second_wait, ErrorResult)
    assert second_wait.outcome == "timed_out"


@pytest.mark.asyncio
async def test_terminal_wait_precedes_unanswered_question() -> None:
    submission = await submit_project(
        "Prove the theorem",
        agent_questions_setting=AgentQuestionsSetting.TIMEOUT_15_MIN,
    )

    assert not isinstance(submission, ErrorResult)
    project, task = submission
    assert task is not None
    state.tasks[task.task_id].status = TaskStatus.COMPLETE

    waited = await wait_task(task.task_id, timeout_seconds=1, poll_interval_seconds=1)

    assert not isinstance(waited, ErrorResult)
    assert waited.outcome == "terminal"
    assert waited.question is None
    assert waited.task.status == "complete"
    assert project.project_id == waited.task.project_id
    assert state.projects[project.project_id].status is ProjectStatus.IDLE


@pytest.mark.asyncio
async def test_terminal_wait_keeps_project_running_with_queued_sibling() -> None:
    submission = await submit_project("Initial task")

    assert not isinstance(submission, ErrorResult)
    project, task = submission
    assert task is not None
    continued = await continue_project(project.project_id, "Follow-up task")
    assert not isinstance(continued, ErrorResult)
    assert continued.status == "queued"
    state.tasks[task.task_id].status = TaskStatus.COMPLETE

    waited = await wait_task(task.task_id, timeout_seconds=1, poll_interval_seconds=1)

    assert not isinstance(waited, ErrorResult)
    assert waited.outcome == "terminal"
    assert state.projects[project.project_id].status is ProjectStatus.RUNNING


@pytest.mark.asyncio
async def test_cancel_keeps_project_running_with_queued_sibling() -> None:
    submission = await submit_project("Initial task")

    assert not isinstance(submission, ErrorResult)
    project, task = submission
    assert task is not None
    sibling = await continue_project(project.project_id, "Follow-up task")
    assert not isinstance(sibling, ErrorResult)
    canceled = await cancel_task(task.task_id)

    assert not isinstance(canceled, ErrorResult)
    assert canceled.status == "canceled"
    assert sibling.status == "queued"
    assert state.projects[project.project_id].status is ProjectStatus.RUNNING


@pytest.mark.asyncio
async def test_disabled_question_setting_creates_only_message_event() -> None:
    submission = await submit_project(
        "Prove the theorem",
        agent_questions_setting=AgentQuestionsSetting.DISABLED,
    )

    assert not isinstance(submission, ErrorResult)
    _, task = submission
    assert task is not None
    listed = await list_task_events(task.task_id)
    waited = await wait_task(task.task_id, timeout_seconds=1, poll_interval_seconds=1)

    assert not isinstance(listed, ErrorResult)
    assert [event.event_type for event in listed.events] == ["message"]
    assert not isinstance(waited, ErrorResult)
    assert waited.outcome == "timed_out"


@pytest.mark.asyncio
async def test_follow_ups_forward_timeout_question_setting() -> None:
    submission = await submit_project("Initial task")

    assert not isinstance(submission, ErrorResult)
    project, _ = submission
    continued = await continue_project(
        project.project_id,
        "Continue",
        agent_questions_setting=AgentQuestionsSetting.TIMEOUT_15_MIN,
    )
    asked = await ask_project(
        project.project_id,
        "Explain",
        agent_questions_setting=AgentQuestionsSetting.TIMEOUT_15_MIN,
    )

    for task in (continued, asked):
        assert not isinstance(task, ErrorResult)
        listed = await list_task_events(task.task_id)
        waited = await wait_task(task.task_id, timeout_seconds=1, poll_interval_seconds=1)
        assert not isinstance(listed, ErrorResult)
        assert [event.event_type for event in listed.events] == ["agent_question", "message"]
        assert not isinstance(waited, ErrorResult)
        assert waited.outcome == "waiting_for_answer"


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
