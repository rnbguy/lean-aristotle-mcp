"""Result models for the Aristotle MCP server."""

from __future__ import annotations

from dataclasses import dataclass

# Type for JSON-serializable result dictionaries
ResultValue = str | int | None
ResultDict = dict[str, ResultValue]


@dataclass
class ProveResult:
    """Result from a prove operation."""

    status: str  # proved | counterexample | failed | error | submitted | in_progress | queued
    code: str | None = None
    counterexample: str | None = None
    project_id: str | None = None
    percent_complete: int | None = None
    message: str = ""

    def to_dict(self) -> ResultDict:
        """Convert to dictionary for JSON serialization."""
        result: ResultDict = {"status": self.status, "message": self.message}
        if self.code is not None:
            result["code"] = self.code
        if self.counterexample is not None:
            result["counterexample"] = self.counterexample
        if self.project_id is not None:
            result["project_id"] = self.project_id
        if self.percent_complete is not None:
            result["percent_complete"] = self.percent_complete
        return result


@dataclass
class ProveFileResult:
    """Result from a prove_file operation."""

    status: str  # proved | partial | failed | error | submitted | in_progress | queued
    output_path: str | None = None
    project_id: str | None = None
    percent_complete: int | None = None
    message: str = ""

    def to_dict(self) -> ResultDict:
        """Convert to dictionary for JSON serialization."""
        result: ResultDict = {
            "status": self.status,
            "message": self.message,
        }
        if self.output_path is not None:
            result["output_path"] = self.output_path
        if self.project_id is not None:
            result["project_id"] = self.project_id
        if self.percent_complete is not None:
            result["percent_complete"] = self.percent_complete
        return result


@dataclass
class FormalizeResult:
    """Result from a formalize operation."""

    status: str  # formalized | proved | failed | error | submitted | in_progress | queued
    lean_code: str | None = None
    project_id: str | None = None
    percent_complete: int | None = None
    message: str = ""

    def to_dict(self) -> ResultDict:
        """Convert to dictionary for JSON serialization."""
        result: ResultDict = {"status": self.status, "message": self.message}
        if self.lean_code is not None:
            result["lean_code"] = self.lean_code
        if self.project_id is not None:
            result["project_id"] = self.project_id
        if self.percent_complete is not None:
            result["percent_complete"] = self.percent_complete
        return result


@dataclass
class ProjectResult:
    """Result from a project metadata operation."""

    status: str  # not_started | queued | in_progress | complete | failed | canceled | error
    project_id: str
    raw_status: str | None = None
    percent_complete: int | None = None
    created_at: str | None = None
    last_updated_at: str | None = None
    input_prompt: str | None = None
    file_name: str | None = None
    description: str | None = None
    output_summary: str | None = None
    message: str = ""

    def to_dict(self) -> ResultDict:
        """Convert to dictionary for JSON serialization."""
        result: ResultDict = {
            "status": self.status,
            "project_id": self.project_id,
            "message": self.message,
        }
        if self.raw_status is not None:
            result["raw_status"] = self.raw_status
        if self.percent_complete is not None:
            result["percent_complete"] = self.percent_complete
        if self.created_at is not None:
            result["created_at"] = self.created_at
        if self.last_updated_at is not None:
            result["last_updated_at"] = self.last_updated_at
        if self.input_prompt is not None:
            result["input_prompt"] = self.input_prompt
        if self.file_name is not None:
            result["file_name"] = self.file_name
        if self.description is not None:
            result["description"] = self.description
        if self.output_summary is not None:
            result["output_summary"] = self.output_summary
        return result


@dataclass
class ProjectFileResult:
    """Result from downloading a project artifact."""

    status: str  # saved | not_ready | failed | canceled | error
    project_id: str
    output_path: str | None = None
    raw_status: str | None = None
    percent_complete: int | None = None
    message: str = ""

    def to_dict(self) -> ResultDict:
        """Convert to dictionary for JSON serialization."""
        result: ResultDict = {
            "status": self.status,
            "project_id": self.project_id,
            "message": self.message,
        }
        if self.output_path is not None:
            result["output_path"] = self.output_path
        if self.raw_status is not None:
            result["raw_status"] = self.raw_status
        if self.percent_complete is not None:
            result["percent_complete"] = self.percent_complete
        return result
