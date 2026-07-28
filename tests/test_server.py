import pytest

from aristotle_mcp.mock_state import reset_state
from aristotle_mcp.server import mcp, submit_project_tool


@pytest.mark.asyncio
async def test_server_registers_exact_native_tool_surface() -> None:
    tools = await mcp.list_tools()

    assert {tool.name for tool in tools} == {
        "submit_project",
        "list_projects",
        "get_project",
        "continue_project",
        "ask_project",
        "list_project_tasks",
        "get_task",
        "wait_task",
        "cancel_task",
        "list_task_events",
        "get_event",
        "answer_question",
        "download_project_files",
        "prove",
        "prove_file",
        "formalize",
    }
    schemas = {tool.name: tool.input_schema for tool in tools}
    assert all(tool.description for tool in tools)
    assert set(schemas["submit_project"]["properties"]) == {
        "prompt",
        "project_dir",
        "tar_file_path",
        "public_file_path",
        "agent_questions_setting",
    }
    assert set(schemas["wait_task"]["properties"]) == {
        "task_id",
        "timeout_seconds",
        "poll_interval_seconds",
    }
    assert set(schemas["prove_file"]["properties"]) == {"file_path", "output_path", "wait"}
    assert set(schemas["formalize"]["properties"]) == {
        "description", "prove", "context_file", "wait"
    }


@pytest.mark.asyncio
async def test_server_describes_mathlib_tactic_requirement() -> None:
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    assert "Mathlib" in (mcp.instructions or "")
    assert "import Mathlib.Tactic" in (mcp.instructions or "")
    assert "Mathlib" in (tools["prove"].description or "")
    assert "import Mathlib.Tactic" in (tools["prove"].description or "")
    assert "import Mathlib.Tactic" in (tools["prove_file"].description or "")
    assert "import Mathlib.Tactic" in (tools["formalize"].description or "")


@pytest.mark.asyncio
async def test_server_submit_returns_native_project_and_task_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "true")
    reset_state()

    result = await submit_project_tool("Prove the supplied theorem")

    assert result["project"]["project_id"].startswith("mock-project-")
    assert result["task"]["task_id"].startswith("mock-task-")
