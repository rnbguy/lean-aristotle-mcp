"""Tests for the native MCP wire models."""

import json
from dataclasses import FrozenInstanceError, fields
from typing import Protocol

import pytest

from aristotle_mcp.models import (
    ErrorResult,
    EventListResult,
    EventResult,
    JsonObject,
    ProjectFilesResult,
    ProjectListResult,
    ProjectResult,
    TaskListResult,
    TaskResult,
    WaitTaskResult,
    WorkflowResult,
)


class ToDict(Protocol):
    def to_dict(self) -> JsonObject:
        ...


def project() -> ProjectResult:
    return ProjectResult(
        project_id="project-1",
        status="running",
        created_at="2026-01-01T00:00:00+00:00",
        last_updated="2026-01-01T00:01:00+00:00",
        description=None,
        has_input=True,
        has_files=False,
    )


def task() -> TaskResult:
    return TaskResult(
        project_id="project-1",
        task_id="task-1",
        status="in_progress",
        created_at="2026-01-01T00:00:00+00:00",
        last_updated_at="2026-01-01T00:01:00+00:00",
        percent_complete=None,
        file_name=None,
        description=None,
        output_summary=None,
    )


def event() -> EventResult:
    return EventResult(
        event_id="event-1",
        task_id="task-1",
        event_type="agent_question",
        created_at="2026-01-01T00:00:00+00:00",
        content="Continue?",
        file_path=None,
        explanation=None,
        suggestions=["yes", "no"],
        status="sent",
        duration_seconds=None,
    )


@pytest.mark.parametrize(
    ("value", "keys"),
    [
        (
            project(),
            {
                "project_id",
                "status",
                "created_at",
                "last_updated",
                "description",
                "has_input",
                "has_files",
            },
        ),
        (ProjectListResult([project()], "next"), {"projects", "next_pagination_key"}),
        (
            task(),
            {
                "task_id",
                "project_id",
                "status",
                "created_at",
                "last_updated_at",
                "percent_complete",
                "file_name",
                "description",
                "output_summary",
            },
        ),
        (TaskListResult([task()], "next"), {"tasks", "next_pagination_key"}),
        (
            event(),
            {
                "event_id",
                "task_id",
                "event_type",
                "created_at",
                "content",
                "file_path",
                "explanation",
                "suggestions",
                "status",
                "duration_seconds",
            },
        ),
        (EventListResult([event()], None), {"events", "next_pagination_key"}),
        (
            WaitTaskResult("waiting_for_answer", task(), event(), "Answer required."),
            {"outcome", "task", "question", "message"},
        ),
        (
            ProjectFilesResult("saved", "project-1", "/tmp/project.tar.gz", "Saved."),
            {"status", "project_id", "output_path", "message"},
        ),
        (
            WorkflowResult("submitted", "project-1", "task-1", None, None, None, "Submitted."),
            {"status", "project_id", "task_id", "code", "output_path", "output_summary", "message"},
        ),
        (
            ErrorResult("error", "validation", "Project ID is required."),
            {"status", "error_type", "message"},
        ),
    ],
)
def test_to_dict_has_stable_complete_key_set(value: ToDict, keys: set[str]) -> None:
    """Every DTO emits all fields, including nullable fields."""
    assert set(value.to_dict()) == keys


def test_nested_models_are_json_serializable() -> None:
    """Nested DTOs are represented by dictionaries and lists."""
    result = WaitTaskResult("waiting_for_answer", task(), event(), "Answer required.").to_dict()

    assert result["task"] == task().to_dict()
    assert result["question"] == event().to_dict()


def test_models_are_frozen_and_slotted() -> None:
    """DTO instances cannot be mutated or receive undeclared attributes."""
    result = project()

    with pytest.raises(FrozenInstanceError):
        attribute = "status"
        value = "idle"
        setattr(result, attribute, value)

    with pytest.raises((AttributeError, TypeError)):
        attribute = "extra"
        value = "value"
        setattr(result, attribute, value)
    assert not hasattr(result, "extra")


def test_all_dtos_are_frozen_slotted_and_json_serializable() -> None:
    """Every DTO has immutable slots and emits JSON-compatible values."""
    values = (
        project(),
        ProjectListResult([project()], None),
        task(),
        TaskListResult([task()], None),
        event(),
        EventListResult([event()], None),
        WaitTaskResult("terminal", task(), None, "Complete."),
        ProjectFilesResult("saved", "project-1", None, "No files."),
        WorkflowResult("submitted", None, None, None, None, None, "Submitted."),
        ErrorResult("error", "validation", "Invalid input."),
    )

    for value in values:
        assert type(value).__slots__
        first_field = fields(value)[0].name
        with pytest.raises(FrozenInstanceError):
            setattr(value, first_field, None)
        json.dumps(value.to_dict())


def test_native_strings_and_identifiers_are_preserved() -> None:
    """DTOs preserve lowercase native strings and explicit task identifiers."""
    task_dict = task().to_dict()
    event_dict = event().to_dict()

    assert task_dict["task_id"] == "task-1"
    assert task_dict["status"] == "in_progress"
    assert event_dict["task_id"] == "task-1"
    assert event_dict["event_type"] == "agent_question"
    assert event_dict["status"] == "sent"


def test_dto_field_order_matches_wire_contract() -> None:
    """Dataclass field order follows the documented wire schemas."""
    assert tuple(field.name for field in fields(ProjectResult)) == (
        "project_id",
        "status",
        "created_at",
        "last_updated",
        "description",
        "has_input",
        "has_files",
    )
    assert tuple(field.name for field in fields(TaskResult)) == (
        "project_id",
        "task_id",
        "status",
        "created_at",
        "last_updated_at",
        "percent_complete",
        "file_name",
        "description",
        "output_summary",
    )
    assert tuple(field.name for field in fields(EventResult)) == (
        "event_id",
        "task_id",
        "event_type",
        "status",
        "created_at",
        "content",
        "file_path",
        "explanation",
        "suggestions",
        "duration_seconds",
    )


def test_legacy_project_progress_fields_are_absent() -> None:
    """Project DTOs do not expose removed status or progress metadata."""
    result = project().to_dict()

    assert "raw_status" not in result
    assert "percent_complete" not in result
    assert "input_prompt" not in result
    assert "output_summary" not in result
