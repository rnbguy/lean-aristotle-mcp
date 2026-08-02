from importlib.metadata import version
from typing import Literal

import pytest
from mcp import Client

from aristotle_mcp.mock_state import reset_state
from aristotle_mcp.server import mcp, submit_project_tool

_TOOL_NAMES = frozenset(
    {
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
)


@pytest.mark.asyncio
async def test_server_registers_exact_native_tool_surface() -> None:
    tools = await mcp.list_tools()

    assert {tool.name for tool in tools} == _TOOL_NAMES
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
async def test_server_instructions_describe_runtime_lifecycle() -> None:
    instructions = mcp.instructions or ""

    for fragment in (
        "terminal",
        "timed_out",
        "waiting_for_answer",
        "answer_question",
        "wait again",
        "wait=false",
        "project_id",
        "task_id",
        "new task_id",
        "code",
        "output_path",
        "output_summary",
        "message",
        "download_project_files",
    ):
        assert fragment in instructions


@pytest.mark.asyncio
async def test_server_descriptions_explain_runtime_options() -> None:
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    expected_fragments = {
        "submit_project": ("question", "TIMEOUT_15_MIN"),
        "continue_project": ("INSTRUCT", "files", "new task_id", "question"),
        "ask_project": ("ASK", "no file", "new task_id", "question"),
        "cancel_task": ("specified task", "not the Project", "sibling tasks"),
        "download_project_files": ("code", "output_path", "absent"),
        "formalize": ("prove=false", "prove=true"),
    }

    for tool_name, fragments in expected_fragments.items():
        description = tools[tool_name].description or ""
        for fragment in fragments:
            assert fragment in description


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_server_client_negotiates_in_memory(mode: Literal["auto", "legacy"]) -> None:
    async with Client(mcp, mode=mode) as client:
        tools = await client.list_tools()
        server_info = client.server_info

    assert server_info is not None
    assert server_info.name == "aristotle-mcp"
    assert server_info.version == version("aristotle-mcp")
    assert {tool.name for tool in tools.tools} == _TOOL_NAMES


@pytest.mark.asyncio
async def test_server_submit_returns_native_project_and_task_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "true")
    reset_state()

    result = await submit_project_tool("Prove the supplied theorem")

    assert result["project"]["project_id"].startswith("mock-project-")
    assert result["task"]["task_id"].startswith("mock-task-")
