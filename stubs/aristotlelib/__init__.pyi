"""Type stubs for aristotlelib - Harmonic's Aristotle theorem prover SDK.

IMPORTANT: These stubs were audited against aristotlelib version 1.0.1.
"""

from datetime import datetime
from enum import Enum
from pathlib import Path

class ProjectStatus(Enum):
    """Status of a proof project."""

    UNKNOWN = "UNKNOWN"
    NOT_STARTED = "NOT_STARTED"
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    COMPLETE_WITH_ERRORS = "COMPLETE_WITH_ERRORS"
    OUT_OF_BUDGET = "OUT_OF_BUDGET"
    FAILED = "FAILED"
    CANCELED = "CANCELED"

class Project:
    """A proof project in the Aristotle system.

    This is a Pydantic model with the following fields.
    """

    project_id: str
    status: ProjectStatus
    created_at: datetime
    last_updated_at: datetime
    percent_complete: int | None
    input_prompt: str | None
    file_name: str | None
    description: str | None
    output_summary: str | None

    @classmethod
    async def create(
        cls,
        prompt: str,
        tar_file_path: Path | str | None = None,
        public_file_path: str | None = None,
    ) -> Project:
        """Create a new proof project."""
        ...

    @classmethod
    async def create_from_directory(
        cls,
        prompt: str,
        project_dir: Path | str,
    ) -> Project:
        """Create project from a directory."""
        ...

    @classmethod
    async def from_id(cls, project_id: str) -> Project:
        """Load an existing project by ID."""
        ...

    @classmethod
    async def list_projects(
        cls,
        pagination_key: str | None = None,
        limit: int = 30,
        status: ProjectStatus | list[ProjectStatus] | None = None,
    ) -> tuple[list[Project], str | None]:
        """List projects. Returns (projects, next_pagination_key)."""
        ...

    async def refresh(self) -> None:
        """Refresh project status from the API."""
        ...

    async def cancel(self) -> None:
        """Cancel a queued or in-progress project."""
        ...

    async def get_solution(
        self,
        destination: Path | str | None = None,
    ) -> Path:
        """Download solution tar.gz to destination."""
        ...

    async def get_solution_if_complete(
        self,
        destination: Path | str | None = None,
    ) -> str | None:
        """Download solution if project reached terminal state."""
        ...

    async def get_input(
        self,
        destination: Path | str | None = None,
    ) -> Path:
        """Download original input tar.gz."""
        ...

    async def wait_for_completion(
        self,
        destination: Path | str | None = None,
        polling_interval_seconds: int = 30,
    ) -> str | None:
        """Wait for the proof to complete. Returns solution path."""
        ...

    def print_compact(self) -> None:
        """Print single-line progress bar."""
        ...

    def __str__(self) -> str:
        """Human-readable string representation."""
        ...

class AristotleAPIError(Exception):
    """Exception raised for API-related errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
    ) -> None:
        ...

class AristotleRequestClient:
    """Async HTTP client for Aristotle API."""

    async def get(
        self,
        endpoint: str,
        params: dict[str, object] | None = None,
    ) -> object:
        ...

    async def post(
        self,
        endpoint: str,
        params: dict[str, object] | None = None,
        data: dict[str, object] | None = None,
        files: list[object] | None = None,
    ) -> object:
        ...

def get_api_key() -> str:
    """Retrieve API key from env var."""
    ...

def set_api_key(api_key: str) -> str:
    """Set module-level API key."""
    ...
