"""Wire models for the Aristotle MCP server."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias

JsonValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | Sequence["JsonValue"]
    | Mapping[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]

@dataclass(frozen=True, slots=True)
class ProjectResult:
    """A project returned by Aristotle."""

    project_id: str
    status: str
    created_at: str
    last_updated: str
    description: str | None
    has_input: bool
    has_files: bool

    def to_dict(self) -> JsonObject:
        """Return the complete JSON representation."""
        return {
            "project_id": self.project_id,
            "status": self.status,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "description": self.description,
            "has_input": self.has_input,
            "has_files": self.has_files,
        }


@dataclass(frozen=True, slots=True)
class ProjectListResult:
    """A page of projects."""

    projects: list[ProjectResult]
    next_pagination_key: str | None

    def to_dict(self) -> JsonObject:
        """Return the complete JSON representation."""
        return {
            "projects": [project.to_dict() for project in self.projects],
            "next_pagination_key": self.next_pagination_key,
        }


@dataclass(frozen=True, slots=True)
class TaskResult:
    """An agent task returned by Aristotle."""

    project_id: str
    task_id: str
    status: str
    created_at: str
    last_updated_at: str
    percent_complete: int | None
    file_name: str | None
    description: str | None
    output_summary: str | None

    def to_dict(self) -> JsonObject:
        """Return the complete JSON representation."""
        return {
            "project_id": self.project_id,
            "task_id": self.task_id,
            "status": self.status,
            "created_at": self.created_at,
            "last_updated_at": self.last_updated_at,
            "percent_complete": self.percent_complete,
            "file_name": self.file_name,
            "description": self.description,
            "output_summary": self.output_summary,
        }


@dataclass(frozen=True, slots=True)
class TaskListResult:
    """A page of tasks."""

    tasks: list[TaskResult]
    next_pagination_key: str | None

    def to_dict(self) -> JsonObject:
        """Return the complete JSON representation."""
        return {
            "tasks": [task.to_dict() for task in self.tasks],
            "next_pagination_key": self.next_pagination_key,
        }


@dataclass(frozen=True, slots=True)
class EventResult:
    """An event emitted for an agent task."""

    event_id: str
    task_id: str
    event_type: str
    status: str
    created_at: str
    content: str
    file_path: str | None
    explanation: str | None
    suggestions: list[str] | None
    duration_seconds: float | None

    def to_dict(self) -> JsonObject:
        """Return the complete JSON representation."""
        return {
            "event_id": self.event_id,
            "task_id": self.task_id,
            "event_type": self.event_type,
            "status": self.status,
            "created_at": self.created_at,
            "content": self.content,
            "file_path": self.file_path,
            "explanation": self.explanation,
            "suggestions": self.suggestions,
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True, slots=True)
class EventListResult:
    """A page of task events."""

    events: list[EventResult]
    next_pagination_key: str | None

    def to_dict(self) -> JsonObject:
        """Return the complete JSON representation."""
        return {
            "events": [event.to_dict() for event in self.events],
            "next_pagination_key": self.next_pagination_key,
        }


@dataclass(frozen=True, slots=True)
class WaitTaskResult:
    """The outcome of bounded task waiting."""

    outcome: Literal["terminal", "timed_out", "waiting_for_answer"]
    task: TaskResult
    question: EventResult | None
    message: str

    def to_dict(self) -> JsonObject:
        """Return the complete JSON representation."""
        return {
            "outcome": self.outcome,
            "task": self.task.to_dict(),
            "question": self.question.to_dict() if self.question is not None else None,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class ProjectFilesResult:
    """A downloaded project files archive."""

    status: str
    project_id: str
    output_path: str | None
    message: str

    def to_dict(self) -> JsonObject:
        """Return the complete JSON representation."""
        return {
            "status": self.status,
            "project_id": self.project_id,
            "output_path": self.output_path,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    """Result returned by a proof or formalization workflow."""

    status: str
    project_id: str | None
    task_id: str | None
    code: str | None
    output_path: str | None
    output_summary: str | None
    message: str

    def to_dict(self) -> JsonObject:
        """Return the complete JSON representation."""
        return {
            "status": self.status,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "code": self.code,
            "output_path": self.output_path,
            "output_summary": self.output_summary,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class ErrorResult:
    """A structured MCP error."""

    status: Literal["error"]
    error_type: Literal["validation", "api", "filesystem", "archive"]
    message: str

    def to_dict(self) -> JsonObject:
        """Return the complete JSON representation."""
        return {
            "status": self.status,
            "error_type": self.error_type,
            "message": self.message,
        }
