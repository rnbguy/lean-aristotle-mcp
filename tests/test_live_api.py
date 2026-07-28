"""Opt-in live checks for the native aristotlelib 2.1 surface."""

import os

import anyio
import pytest
from aristotlelib import AgentQuestionsSetting, Project, TaskStatus

pytestmark = pytest.mark.skipif(
    os.environ.get("ARISTOTLE_LIVE_TESTS") != "true",
    reason="set ARISTOTLE_LIVE_TESTS=true to run paid live Aristotle checks",
)


@pytest.mark.asyncio
async def test_live_read_surface() -> None:
    projects, next_key = await Project.list_projects(limit=1)

    assert len(projects) <= 1
    assert next_key is None or isinstance(next_key, str)


@pytest.mark.asyncio
async def test_live_project_task_lifecycle_is_bounded() -> None:
    project = await Project.create(
        "Reply with a concise status.",
        agent_questions_setting=AgentQuestionsSetting.DISABLED,
    )
    tasks, _ = await project.get_tasks(limit=1)

    assert tasks
    task = tasks[0]
    with anyio.move_on_after(30):
        await task.refresh()
    terminal = {
        TaskStatus.COMPLETE,
        TaskStatus.COMPLETE_WITH_ERRORS,
        TaskStatus.OUT_OF_BUDGET,
        TaskStatus.FAILED,
        TaskStatus.CANCELED,
    }
    if task.status not in terminal:
        await task.cancel()


@pytest.mark.asyncio
async def test_live_follow_up_lifecycle_is_bounded() -> None:
    project = await Project.create("Acknowledge this request.")
    task = await project.ask("Give a one-line follow-up.")

    with anyio.move_on_after(30):
        await task.refresh()
    terminal = {
        TaskStatus.COMPLETE,
        TaskStatus.COMPLETE_WITH_ERRORS,
        TaskStatus.OUT_OF_BUDGET,
        TaskStatus.FAILED,
        TaskStatus.CANCELED,
    }
    if task.status not in terminal:
        await task.cancel()
