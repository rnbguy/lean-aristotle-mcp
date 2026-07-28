"""Mutable in-memory state for native mock operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from aristotlelib import EventStatus, EventType, ProjectStatus, TaskStatus


@dataclass
class MockEvent:
    event_id: str
    agent_task_id: str
    event_type: EventType
    created_at: datetime
    content: str
    file_path: str | None
    explanation: str | None
    suggestions: list[str] | None
    status: EventStatus
    duration_seconds: float | None


@dataclass
class MockTask:
    project_id: str
    agent_task_id: str
    status: TaskStatus
    created_at: datetime
    last_updated_at: datetime
    percent_complete: int | None
    file_name: str | None
    description: str | None
    output_summary: str | None
    event_ids: list[str] = field(default_factory=list)


@dataclass
class MockProject:
    project_id: str
    created_at: datetime
    last_updated: datetime
    description: str | None
    status: ProjectStatus
    has_input: bool
    has_files: bool
    source_files: dict[str, bytes] = field(default_factory=dict)
    task_ids: list[str] = field(default_factory=list)


@dataclass
class MockState:
    """A mutable, locked store used to isolate mock service state."""

    projects: dict[str, MockProject] = field(default_factory=dict)
    tasks: dict[str, MockTask] = field(default_factory=dict)
    events: dict[str, MockEvent] = field(default_factory=dict)
    lock: RLock = field(default_factory=RLock)

    def clear(self) -> None:
        with self.lock:
            self.projects.clear()
            self.tasks.clear()
            self.events.clear()


state = MockState()


def reset_state() -> None:
    state.clear()


def now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"mock-{prefix}-{uuid4()}"
