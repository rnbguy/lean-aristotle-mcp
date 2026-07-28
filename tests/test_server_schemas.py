from __future__ import annotations

import pytest

from aristotle_mcp.models import JsonObject
from aristotle_mcp.server import mcp


def _nullable_string(title: str) -> JsonObject:
    return {
        "anyOf": [{"type": "string"}, {"type": "null"}],
        "default": None,
        "title": title,
    }


def _agent_questions_setting() -> JsonObject:
    return {"$ref": "#/$defs/AgentQuestionsSetting", "default": 1}


@pytest.mark.asyncio
async def test_server_input_schemas_match_public_contract() -> None:
    expected: dict[str, JsonObject] = {
        "submit_project": {
            "$defs": {
                "AgentQuestionsSetting": {
                    "enum": [1, 2],
                    "title": "AgentQuestionsSetting",
                    "type": "integer",
                }
            },
            "properties": {
                "agent_questions_setting": _agent_questions_setting(),
                "project_dir": _nullable_string("Project Dir"),
                "prompt": {"title": "Prompt", "type": "string"},
                "public_file_path": _nullable_string("Public File Path"),
                "tar_file_path": _nullable_string("Tar File Path"),
            },
            "required": ["prompt"],
            "title": "submit_project_toolArguments",
            "type": "object",
        },
        "list_projects": {
            "$defs": {
                "ProjectStatus": {"enum": [0, 1, 2], "title": "ProjectStatus", "type": "integer"}
            },
            "properties": {
                "limit": {"default": 30, "title": "Limit", "type": "integer"},
                "pagination_key": _nullable_string("Pagination Key"),
                "status": {
                    "anyOf": [
                        {"$ref": "#/$defs/ProjectStatus"},
                        {"items": {"$ref": "#/$defs/ProjectStatus"}, "type": "array"},
                        {"type": "null"},
                    ],
                    "default": None,
                    "title": "Status",
                },
            },
            "title": "list_projects_toolArguments",
            "type": "object",
        },
        "get_project": {
            "properties": {"project_id": {"title": "Project Id", "type": "string"}},
            "required": ["project_id"],
            "title": "get_project_toolArguments",
            "type": "object",
        },
        "continue_project": {
            "$defs": {
                "AgentQuestionsSetting": {
                    "enum": [1, 2],
                    "title": "AgentQuestionsSetting",
                    "type": "integer",
                }
            },
            "properties": {
                "agent_questions_setting": _agent_questions_setting(),
                "files": {
                    "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                    "default": None,
                    "title": "Files",
                },
                "project_id": {"title": "Project Id", "type": "string"},
                "prompt": {"title": "Prompt", "type": "string"},
            },
            "required": ["project_id", "prompt"],
            "title": "continue_project_toolArguments",
            "type": "object",
        },
        "ask_project": {
            "$defs": {
                "AgentQuestionsSetting": {
                    "enum": [1, 2],
                    "title": "AgentQuestionsSetting",
                    "type": "integer",
                }
            },
            "properties": {
                "agent_questions_setting": _agent_questions_setting(),
                "project_id": {"title": "Project Id", "type": "string"},
                "prompt": {"title": "Prompt", "type": "string"},
            },
            "required": ["project_id", "prompt"],
            "title": "ask_project_toolArguments",
            "type": "object",
        },
        "list_project_tasks": {
            "properties": {
                "limit": {"default": 10, "title": "Limit", "type": "integer"},
                "newest_first": {"default": True, "title": "Newest First", "type": "boolean"},
                "pagination_key": _nullable_string("Pagination Key"),
                "project_id": {"title": "Project Id", "type": "string"},
            },
            "required": ["project_id"],
            "title": "list_project_tasks_toolArguments",
            "type": "object",
        },
        "get_task": {
            "properties": {"task_id": {"title": "Task Id", "type": "string"}},
            "required": ["task_id"],
            "title": "get_task_toolArguments",
            "type": "object",
        },
        "wait_task": {
            "properties": {
                "poll_interval_seconds": {
                    "default": 5.0,
                    "title": "Poll Interval Seconds",
                    "type": "number",
                },
                "task_id": {"title": "Task Id", "type": "string"},
                "timeout_seconds": {"default": 300.0, "title": "Timeout Seconds", "type": "number"},
            },
            "required": ["task_id"],
            "title": "wait_task_toolArguments",
            "type": "object",
        },
        "cancel_task": {
            "properties": {"task_id": {"title": "Task Id", "type": "string"}},
            "required": ["task_id"],
            "title": "cancel_task_toolArguments",
            "type": "object",
        },
        "list_task_events": {
            "properties": {
                "limit": {"default": 50, "title": "Limit", "type": "integer"},
                "newest_first": {"default": True, "title": "Newest First", "type": "boolean"},
                "pagination_key": _nullable_string("Pagination Key"),
                "task_id": {"title": "Task Id", "type": "string"},
            },
            "required": ["task_id"],
            "title": "list_task_events_toolArguments",
            "type": "object",
        },
        "get_event": {
            "properties": {"event_id": {"title": "Event Id", "type": "string"}},
            "required": ["event_id"],
            "title": "get_event_toolArguments",
            "type": "object",
        },
        "answer_question": {
            "properties": {
                "answer": {"title": "Answer", "type": "string"},
                "event_id": {"title": "Event Id", "type": "string"},
            },
            "required": ["event_id", "answer"],
            "title": "answer_question_toolArguments",
            "type": "object",
        },
        "download_project_files": {
            "properties": {
                "output_path": _nullable_string("Output Path"),
                "overwrite": {"default": False, "title": "Overwrite", "type": "boolean"},
                "project_id": {"title": "Project Id", "type": "string"},
            },
            "required": ["project_id"],
            "title": "download_project_files_toolArguments",
            "type": "object",
        },
        "prove": {
            "properties": {
                "code": {"title": "Code", "type": "string"},
                "context_files": {
                    "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                    "default": None,
                    "title": "Context Files",
                },
                "hint": _nullable_string("Hint"),
                "wait": {"default": True, "title": "Wait", "type": "boolean"},
            },
            "required": ["code"],
            "title": "prove_toolArguments",
            "type": "object",
        },
        "prove_file": {
            "properties": {
                "file_path": {"title": "File Path", "type": "string"},
                "output_path": _nullable_string("Output Path"),
                "wait": {"default": True, "title": "Wait", "type": "boolean"},
            },
            "required": ["file_path"],
            "title": "prove_file_toolArguments",
            "type": "object",
        },
        "formalize": {
            "properties": {
                "context_file": _nullable_string("Context File"),
                "description": {"title": "Description", "type": "string"},
                "prove": {"default": False, "title": "Prove", "type": "boolean"},
                "wait": {"default": True, "title": "Wait", "type": "boolean"},
            },
            "required": ["description"],
            "title": "formalize_toolArguments",
            "type": "object",
        },
    }

    tools = await mcp.list_tools()

    assert {tool.name for tool in tools} == set(expected)
    assert {tool.name: tool.input_schema for tool in tools} == expected
    assert all(tool.output_schema is None for tool in tools)
    assert {tool.name: tool.model_dump(by_alias=True)["inputSchema"] for tool in tools} == expected
    assert all(tool.model_dump(by_alias=True)["outputSchema"] is None for tool in tools)
