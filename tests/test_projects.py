from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from aristotlelib import ProjectStatus
from aristotlelib.local_file_utils import LeanProjectError

from aristotle_mcp import projects
from aristotle_mcp.models import ErrorResult


def _project() -> SimpleNamespace:
    return SimpleNamespace(
        project_id="project-1",
        status=ProjectStatus.IDLE,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_updated=datetime(2026, 1, 1, tzinfo=UTC),
        description="test",
        has_input=True,
        has_files=True,
    )


@pytest.mark.asyncio
async def test_get_project_refreshes_native_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    project = _project()
    refreshed: list[bool] = []

    async def refresh() -> None:
        refreshed.append(True)

    async def from_id(project_id: str) -> SimpleNamespace:
        assert project_id == "project-1"
        return project

    project.refresh = refresh
    monkeypatch.setattr(projects.Project, "from_id", from_id)

    result = await projects.get_project("project-1")

    assert not isinstance(result, ErrorResult)
    assert refreshed == [True]
    assert result.status == "idle"


@pytest.mark.asyncio
async def test_download_translates_existing_destination_to_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    output = tmp_path / "project.tar.gz"
    output.write_text("keep")

    result = await projects.download_project_files("project-1", str(output))

    assert isinstance(result, ErrorResult)
    assert result.error_type == "filesystem"
    assert output.read_text() == "keep"


@pytest.mark.asyncio
async def test_download_uses_temporary_file_and_preserves_existing_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    output = tmp_path / "project.tar.gz"
    output.write_bytes(b"keep")
    project = _project()

    async def get_files(destination: str) -> None:
        assert destination != str(output)
        Path(destination).write_bytes(b"partial")
        raise OSError("interrupted")

    async def from_id(project_id: str) -> SimpleNamespace:
        assert project_id == "project-1"
        return project

    project.get_files = get_files
    monkeypatch.setattr(projects.Project, "from_id", from_id)
    result = await projects.download_project_files("project-1", str(output), overwrite=True)

    assert isinstance(result, ErrorResult)
    assert output.read_bytes() == b"keep"
    assert not list(tmp_path.glob(".project.tar.gz.*"))


@pytest.mark.asyncio
async def test_download_uses_temporary_file_before_atomic_create(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    output = tmp_path / "project.tar.gz"
    project = _project()

    async def get_files(destination: str) -> None:
        assert destination != str(output)
        Path(destination).write_bytes(b"complete")

    async def from_id(project_id: str) -> SimpleNamespace:
        assert project_id == "project-1"
        return project

    project.get_files = get_files
    monkeypatch.setattr(projects.Project, "from_id", from_id)
    result = await projects.download_project_files("project-1", str(output))

    assert not isinstance(result, ErrorResult)
    assert output.read_bytes() == b"complete"


@pytest.mark.asyncio
async def test_submit_translates_lean_project_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")

    async def create(*args: str) -> None:
        _ = args
        raise LeanProjectError("invalid Lean project")

    monkeypatch.setattr(projects.Project, "create_from_directory", create)
    result = await projects.submit_project("prove", project_dir=str(tmp_path))

    assert isinstance(result, ErrorResult)
    assert result.error_type == "validation"
