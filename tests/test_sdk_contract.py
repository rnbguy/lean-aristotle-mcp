"""Runtime contract tests for aristotlelib 2.1.0."""

import inspect
import tomllib
from pathlib import Path

import aristotlelib
import pydantic
from aristotlelib import (
    AgentQuestionsSetting,
    AgentTask,
    AristotleAPIError,
    AristotleRequestClient,
    Event,
    EventStatus,
    EventType,
    FollowUpMode,
    Project,
    ProjectStatus,
    TaskStatus,
)


def test_public_exports() -> None:
    expected = [
        "set_api_key",
        "AgentTask",
        "TaskStatus",
        "Project",
        "ProjectStatus",
        "FollowUpMode",
        "AgentQuestionsSetting",
        "Event",
        "EventType",
        "EventStatus",
        "AristotleRequestClient",
        "AristotleAPIError",
    ]
    assert aristotlelib.__all__ == expected
    assert all(hasattr(aristotlelib, name) for name in expected)


def test_project_dependencies_are_current() -> None:
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert project["project"]["dependencies"] == [
        "mcp>=1.28.1,<2",
        "python-dotenv>=1.2.2",
        "aristotlelib>=2.1.0",
        "anyio>=4.14.2",
        "pathspec>=1.1.1",
    ]
    assert project["project"]["optional-dependencies"]["dev"] == [
        "build>=1.5.0",
        "mypy>=2.3.0",
        "ruff>=0.16.0",
        "pytest>=9.1.1",
        "pytest-asyncio>=1.4.0",
        "pytest-timeout>=2.4.0",
    ]
    assert project["build-system"]["requires"] == ["hatchling>=1.31.0"]


def test_enum_members() -> None:
    assert [(member.name, member.value) for member in ProjectStatus] == [
        ("UNKNOWN", 0),
        ("RUNNING", 1),
        ("IDLE", 2),
    ]
    assert [(member.name, member.value) for member in FollowUpMode] == [("ASK", 1), ("INSTRUCT", 2)]
    assert [(member.name, member.value) for member in AgentQuestionsSetting] == [
        ("DISABLED", 1),
        ("TIMEOUT_15_MIN", 2),
    ]
    assert [member.name for member in TaskStatus] == [
        "UNKNOWN",
        "QUEUED",
        "IN_PROGRESS",
        "COMPLETE",
        "COMPLETE_WITH_ERRORS",
        "OUT_OF_BUDGET",
        "FAILED",
        "CANCELED",
    ]
    assert [member.name for member in EventType] == [
        "UNKNOWN",
        "MESSAGE",
        "BUILDING",
        "THINKING",
        "EDITING_FILE",
        "SEARCHING_LOCAL",
        "RUNNING_COMMAND",
        "PROVING",
        "READING_FILES",
        "REVIEWING",
        "FINISHED",
        "ERROR",
        "READING_LEAN",
        "SEARCHING_EXTERNAL",
        "RUNNING_LEAN",
        "QUESTION",
        "SUMMARY",
        "AGENT_QUESTION",
    ]
    assert [(member.name, member.value) for member in EventStatus] == [
        ("UNKNOWN", 0),
        ("COMPLETE", 1),
        ("SENT", 2),
    ]


def test_model_fields() -> None:
    assert issubclass(Project, pydantic.BaseModel)
    assert issubclass(AgentTask, pydantic.BaseModel)
    assert issubclass(Event, pydantic.BaseModel)
    assert isinstance(Project.model_fields, dict)
    assert isinstance(AgentTask.model_fields, dict)
    assert isinstance(Event.model_fields, dict)
    assert set(Project.model_fields) == {
        "project_id",
        "created_at",
        "last_updated",
        "description",
        "status",
        "has_input",
        "has_files",
    }
    assert set(AgentTask.model_fields) == {
        "project_id",
        "agent_task_id",
        "status",
        "created_at",
        "last_updated_at",
        "percent_complete",
        "file_name",
        "description",
        "output_summary",
    }
    assert set(Event.model_fields) == {
        "event_id",
        "agent_task_id",
        "event_type",
        "created_at",
        "content",
        "file_path",
        "explanation",
        "suggestions",
        "status",
        "duration_seconds",
    }


def test_method_signatures() -> None:
    assert tuple(inspect.signature(Project.create).parameters) == (
        "prompt",
        "tar_file_path",
        "public_file_path",
        "agent_questions_setting",
    )
    assert tuple(inspect.signature(Project.create_from_directory).parameters) == (
        "prompt",
        "project_dir",
        "agent_questions_setting",
    )
    assert tuple(inspect.signature(Project.list_projects).parameters) == (
        "pagination_key",
        "limit",
        "status",
    )
    assert tuple(inspect.signature(Project.ask).parameters) == (
        "self",
        "prompt",
        "mode",
        "files",
        "agent_questions_setting",
    )
    assert tuple(inspect.signature(Project.get_files).parameters) == ("self", "destination")
    assert tuple(inspect.signature(Project.get_tasks).parameters) == (
        "self",
        "pagination_key",
        "limit",
        "newest_first",
    )
    assert tuple(inspect.signature(AgentTask.get_events).parameters) == (
        "self",
        "pagination_key",
        "limit",
        "newest_first",
    )
    assert tuple(inspect.signature(AgentTask.cancel).parameters) == ("self",)
    assert tuple(inspect.signature(AgentTask.show).parameters) == (
        "self",
        "num_events",
        "pagination_key",
    )
    assert tuple(inspect.signature(AgentTask.wait_for_completion).parameters) == (
        "self",
        "num_events",
    )
    assert tuple(inspect.signature(Event.answer).parameters) == ("self", "answer")
    assert tuple(inspect.signature(AristotleRequestClient.get).parameters) == (
        "self",
        "endpoint",
        "params",
    )
    assert tuple(inspect.signature(AristotleRequestClient.post).parameters) == (
        "self",
        "endpoint",
        "params",
        "data",
        "files",
        "json",
    )
    assert tuple(inspect.signature(AristotleRequestClient.put).parameters) == (
        "self",
        "endpoint",
        "data",
    )
    assert tuple(inspect.signature(AristotleRequestClient.delete).parameters) == (
        "self",
        "endpoint",
    )
    assert tuple(inspect.signature(AristotleRequestClient.stream_sse).parameters) == (
        "self",
        "endpoint",
        "max_retries",
    )
    assert tuple(inspect.signature(AristotleRequestClient.close).parameters) == ("self",)
    assert tuple(inspect.signature(AristotleAPIError).parameters) == ("message", "status_code")
    assert tuple(inspect.signature(aristotlelib.set_api_key).parameters) == ("api_key",)
