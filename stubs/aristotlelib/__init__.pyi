"""Type stubs for aristotlelib 2.1.0."""

from collections.abc import AsyncIterator
from datetime import datetime
from enum import Enum, IntEnum
from pathlib import Path
from typing import ClassVar, Self

import httpx
from pydantic.fields import FieldInfo

__all__: list[str] = [
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


class _AristotleObject:
    endpoint_prefix: ClassVar[str]
    model_fields: ClassVar[dict[str, FieldInfo]]

    @property
    def object_id(self) -> str: ...

    def _update_from_response(
        self,
        response_data: dict[str, str | int | float | bool | None],
    ) -> None: ...

    async def refresh(self) -> None: ...

    @classmethod
    async def from_id(cls: type[Self], object_id: str) -> Self: ...


class ProjectStatus(IntEnum):
    UNKNOWN = 0
    RUNNING = 1
    IDLE = 2


class FollowUpMode(IntEnum):
    ASK = 1
    INSTRUCT = 2


class AgentQuestionsSetting(IntEnum):
    DISABLED = 1
    TIMEOUT_15_MIN = 2


class TaskStatus(Enum):
    UNKNOWN = "UNKNOWN"
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    COMPLETE_WITH_ERRORS = "COMPLETE_WITH_ERRORS"
    OUT_OF_BUDGET = "OUT_OF_BUDGET"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class EventType(IntEnum):
    UNKNOWN = 0
    MESSAGE = 1
    BUILDING = 2
    THINKING = 3
    EDITING_FILE = 4
    SEARCHING_LOCAL = 5
    RUNNING_COMMAND = 6
    PROVING = 7
    READING_FILES = 8
    REVIEWING = 9
    FINISHED = 10
    ERROR = 11
    READING_LEAN = 12
    SEARCHING_EXTERNAL = 13
    RUNNING_LEAN = 14
    QUESTION = 15
    SUMMARY = 16
    AGENT_QUESTION = 17


class EventStatus(IntEnum):
    UNKNOWN = 0
    COMPLETE = 1
    SENT = 2


class Project(_AristotleObject):
    project_id: str
    created_at: datetime
    last_updated: datetime
    description: str | None
    status: ProjectStatus
    has_input: bool
    has_files: bool

    def __str__(self) -> str: ...

    @classmethod
    async def create(
        cls,
        prompt: str,
        tar_file_path: Path | str | None = None,
        public_file_path: str | None = None,
        agent_questions_setting: AgentQuestionsSetting = AgentQuestionsSetting.DISABLED,
    ) -> Project:
        ...

    @classmethod
    async def create_from_directory(
        cls,
        prompt: str,
        project_dir: Path | str,
        agent_questions_setting: AgentQuestionsSetting = AgentQuestionsSetting.DISABLED,
    ) -> Project:
        ...

    @classmethod
    async def list_projects(
        cls,
        pagination_key: str | None = None,
        limit: int = 30,
        status: ProjectStatus | list[ProjectStatus] | None = None,
    ) -> tuple[list[Project], str | None]:
        ...

    async def ask(
        self,
        prompt: str,
        mode: FollowUpMode = FollowUpMode.INSTRUCT,
        files: list[Path | str] | None = None,
        agent_questions_setting: AgentQuestionsSetting = AgentQuestionsSetting.DISABLED,
    ) -> AgentTask:
        ...

    async def get_files(self, destination: Path | str | None = None) -> Path:
        ...

    async def get_tasks(
        self,
        pagination_key: str | None = None,
        limit: int = 10,
        newest_first: bool = True,
    ) -> tuple[list[AgentTask], str | None]:
        ...


class AgentTask(_AristotleObject):
    project_id: str
    agent_task_id: str
    status: TaskStatus
    created_at: datetime
    last_updated_at: datetime
    percent_complete: int | None
    file_name: str | None
    description: str | None
    output_summary: str | None

    def __str__(self) -> str: ...

    async def get_events(
        self,
        pagination_key: str | None = None,
        limit: int = 50,
        newest_first: bool = True,
    ) -> tuple[list[Event], str | None]:
        ...

    async def cancel(self) -> None:
        ...

    async def show(self, num_events: int = 0, pagination_key: str | None = None) -> str | None:
        ...

    async def wait_for_completion(self, num_events: int = 3) -> None: ...


class Event(_AristotleObject):
    event_id: str
    agent_task_id: str
    event_type: EventType
    created_at: datetime
    content: str
    file_path: str | None
    explanation: str | None
    suggestions: list[str] | None = None
    status: EventStatus
    duration_seconds: float | None = None

    def __str__(self) -> str: ...

    async def answer(self, answer: str) -> None: ...


class AristotleAPIError(Exception):
    status_code: int | None

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
    ) -> None:
        ...

class AristotleRequestClient:
    def __init__(self) -> None: ...

    async def __aenter__(self) -> AristotleRequestClient: ...

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None: ...

    async def get(
        self,
        endpoint: str,
        params: dict[str, object] | None = None,
    ) -> httpx.Response:
        ...

    async def post(
        self,
        endpoint: str,
        params: dict[str, object] | None = None,
        data: dict[str, object] | None = None,
        files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
        json: dict[str, object] | None = None,
    ) -> httpx.Response:
        ...

    async def put(
        self,
        endpoint: str,
        data: dict[str, object] | None = None,
    ) -> httpx.Response:
        ...

    async def delete(self, endpoint: str) -> httpx.Response:
        ...

    async def stream_sse(
        self,
        endpoint: str,
        max_retries: int = 3,
    ) -> AsyncIterator[dict[str, object]]:
        ...

    async def close(self) -> None:
        ...


def set_api_key(api_key: str) -> str:
    ...
