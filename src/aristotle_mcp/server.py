"""MCP registration for native aristotlelib 2.1 operations."""

from __future__ import annotations

import sys

from aristotlelib import AgentQuestionsSetting, ProjectStatus
from mcp.server import MCPServer

from aristotle_mcp.config import configure_sdk, has_api_key, is_mock_mode
from aristotle_mcp.events import answer_question, get_event, list_task_events
from aristotle_mcp.models import ErrorResult, JsonObject
from aristotle_mcp.projects import (
    ask_project,
    continue_project,
    download_project_files,
    get_project,
    list_projects,
    submit_project,
)
from aristotle_mcp.tasks import cancel_task, get_task, list_project_tasks, wait_task
from aristotle_mcp.workflows import formalize, prove, prove_file

mcp: MCPServer[None] = MCPServer(
    name="aristotle-mcp",
    instructions=(
        "Native aristotlelib 2.1 Project, AgentTask, and Event operations for Lean 4. "
        "Use wait_task for bounded polling and answer_question for pending agent questions. "
        "The project must depend on Mathlib; generated-proof files need `import Mathlib.Tactic`."
    ),
)


@mcp.tool(name="submit_project", structured_output=False)
async def submit_project_tool(
    prompt: str,
    project_dir: str | None = None,
    tar_file_path: str | None = None,
    public_file_path: str | None = None,
    agent_questions_setting: AgentQuestionsSetting = AgentQuestionsSetting.DISABLED,
) -> JsonObject:
    """Create a Project from one directory or tar archive and return project/task IDs."""
    result = await submit_project(
        prompt,
        project_dir,
        tar_file_path,
        public_file_path,
        agent_questions_setting,
    )
    if isinstance(result, ErrorResult):
        return result.to_dict()
    project, task = result
    return {"project": project.to_dict(), "task": task.to_dict() if task is not None else None}


@mcp.tool(name="list_projects", structured_output=False)
async def list_projects_tool(
    pagination_key: str | None = None,
    limit: int = 30,
    status: ProjectStatus | list[ProjectStatus] | None = None,
) -> JsonObject:
    """List Projects newest first; status uses native RUNNING or IDLE enums."""
    return (await list_projects(pagination_key, limit, status)).to_dict()


@mcp.tool(name="get_project", structured_output=False)
async def get_project_tool(project_id: str) -> JsonObject:
    """Refresh and return one Project by its project_id."""
    return (await get_project(project_id)).to_dict()


@mcp.tool(name="continue_project", structured_output=False)
async def continue_project_tool(
    project_id: str,
    prompt: str,
    files: list[str] | None = None,
    agent_questions_setting: AgentQuestionsSetting = AgentQuestionsSetting.DISABLED,
) -> JsonObject:
    """Send an INSTRUCT follow-up to an idle Project; optional files are uploaded with the task."""
    return (await continue_project(project_id, prompt, files, agent_questions_setting)).to_dict()


@mcp.tool(name="ask_project", structured_output=False)
async def ask_project_tool(
    project_id: str,
    prompt: str,
    agent_questions_setting: AgentQuestionsSetting = AgentQuestionsSetting.DISABLED,
) -> JsonObject:
    """Send an ASK follow-up that creates an AgentTask and may later require an answer."""
    return (await ask_project(project_id, prompt, agent_questions_setting)).to_dict()


@mcp.tool(name="list_project_tasks", structured_output=False)
async def list_project_tasks_tool(
    project_id: str,
    pagination_key: str | None = None,
    limit: int = 10,
    newest_first: bool = True,
) -> JsonObject:
    """List a Project's AgentTasks; newest_first controls native task ordering."""
    return (await list_project_tasks(project_id, pagination_key, limit, newest_first)).to_dict()


@mcp.tool(name="get_task", structured_output=False)
async def get_task_tool(task_id: str) -> JsonObject:
    """Refresh and return one AgentTask by task_id."""
    return (await get_task(task_id)).to_dict()


@mcp.tool(name="wait_task", structured_output=False)
async def wait_task_tool(
    task_id: str,
    timeout_seconds: float = 300.0,
    poll_interval_seconds: float = 5.0,
) -> JsonObject:
    """Boundedly poll: outcome is terminal, timed_out, or waiting_for_answer; bounds are seconds."""
    return (await wait_task(task_id, timeout_seconds, poll_interval_seconds)).to_dict()


@mcp.tool(name="cancel_task", structured_output=False)
async def cancel_task_tool(task_id: str) -> JsonObject:
    """Cancel a nonterminal AgentTask and return its updated native status."""
    return (await cancel_task(task_id)).to_dict()


@mcp.tool(name="list_task_events", structured_output=False)
async def list_task_events_tool(
    task_id: str,
    pagination_key: str | None = None,
    limit: int = 50,
    newest_first: bool = True,
) -> JsonObject:
    """List task Events; AGENT_QUESTION events with SENT status require answer_question."""
    return (await list_task_events(task_id, pagination_key, limit, newest_first)).to_dict()


@mcp.tool(name="get_event", structured_output=False)
async def get_event_tool(event_id: str) -> JsonObject:
    """Return one Event by event_id, including event type, status, and question metadata."""
    return (await get_event(event_id)).to_dict()


@mcp.tool(name="answer_question", structured_output=False)
async def answer_question_tool(event_id: str, answer: str) -> JsonObject:
    """Answer a pending SENT AGENT_QUESTION event; answered or expired questions are rejected."""
    return (await answer_question(event_id, answer)).to_dict()


@mcp.tool(name="download_project_files", structured_output=False)
async def download_project_files_tool(
    project_id: str,
    output_path: str | None = None,
    overwrite: bool = False,
) -> JsonObject:
    """Atomically download a Project archive; overwrite defaults false."""
    return (await download_project_files(project_id, output_path, overwrite)).to_dict()


@mcp.tool(name="prove", structured_output=False)
async def prove_tool(
    code: str,
    context_files: list[str] | None = None,
    hint: str | None = None,
    wait: bool = True,
) -> JsonObject:
    """Prove inline Lean in a Mathlib project; generated files need
    `import Mathlib.Tactic`."""
    return (await prove(code, context_files, hint, wait)).to_dict()


@mcp.tool(name="prove_file", structured_output=False)
async def prove_file_tool(
    file_path: str,
    output_path: str | None = None,
    wait: bool = True,
) -> JsonObject:
    """Prove a Lean file in a Mathlib project; generated files need
    `import Mathlib.Tactic`."""
    return (await prove_file(file_path, output_path, wait)).to_dict()


@mcp.tool(name="formalize", structured_output=False)
async def formalize_tool(
    description: str,
    prove: bool = False,
    context_file: str | None = None,
    wait: bool = True,
) -> JsonObject:
    """Formalize prose in a Mathlib project; generated files need
    `import Mathlib.Tactic`."""
    return (await formalize(description, prove, context_file, wait)).to_dict()


@mcp.resource("aristotle://status")
async def get_status() -> str:
    mock_mode = is_mock_mode()
    api_key_configured = has_api_key()
    ready = mock_mode or api_key_configured
    return (
        f'{{"mock_mode": {str(mock_mode).lower()}, '
        f'"api_key_configured": {str(api_key_configured).lower()}, '
        f'"ready": {str(ready).lower()}}}'
    )


def main() -> None:
    """Configure the SDK and run the stdio MCP server."""
    configure_sdk()
    print("Aristotle MCP server starting", file=sys.stderr)
    mcp.run(transport="stdio")
