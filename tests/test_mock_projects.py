import tarfile
from pathlib import Path

import pytest
from aristotlelib import ProjectStatus

from aristotle_mcp import mock_downloads
from aristotle_mcp.mock_state import reset_state, state
from aristotle_mcp.models import ErrorResult
from aristotle_mcp.projects import (
    ask_project,
    continue_project,
    download_project_files,
    list_projects,
    submit_project,
)
from aristotle_mcp.tasks import cancel_task


@pytest.fixture(autouse=True)
def mock_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "true")
    reset_state()


@pytest.mark.asyncio
async def test_project_submission_pagination_follow_up_and_download(tmp_path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "Main.lean").write_text("theorem main : True := by trivial\n")
    (project_dir / ".env").write_text("not archived")
    first = await submit_project("first", str(project_dir))
    second = await submit_project("second")

    assert not isinstance(first, ErrorResult)
    assert not isinstance(second, ErrorResult)
    first_project, first_task = first
    page = await list_projects(limit=1, status=ProjectStatus.RUNNING)
    state.projects[first_project.project_id].status = ProjectStatus.IDLE
    continued = await continue_project(first_project.project_id, "continue")
    asked = await ask_project(first_project.project_id, "question")
    output = tmp_path / "project.tar.gz"
    downloaded = await download_project_files(first_project.project_id, str(output))

    assert first_task is not None
    assert not isinstance(page, ErrorResult)
    assert page.next_pagination_key is not None
    assert not isinstance(continued, ErrorResult)
    assert not isinstance(asked, ErrorResult)
    assert continued.task_id != asked.task_id
    assert not isinstance(downloaded, ErrorResult)
    with tarfile.open(output, "r:gz") as archive:
        assert archive.getnames() == ["Main.lean"]


@pytest.mark.asyncio
async def test_cancelled_mock_task_allows_file_follow_up(tmp_path) -> None:
    submission = await submit_project("initial")
    follow_up_file = tmp_path / "Context.lean"
    follow_up_file.write_text("theorem context : True := by trivial\n")

    assert not isinstance(submission, ErrorResult)
    project, task = submission
    assert task is not None
    canceled = await cancel_task(task.task_id)
    continued = await continue_project(project.project_id, "continue", [str(follow_up_file)])

    assert not isinstance(canceled, ErrorResult)
    assert canceled.status == "canceled"
    assert not isinstance(continued, ErrorResult)
    source_files = state.projects[project.project_id].source_files
    assert source_files[follow_up_file.name] == follow_up_file.read_bytes()


@pytest.mark.asyncio
@pytest.mark.parametrize("overwrite", [False, True])
async def test_mock_download_replaces_destination_from_sibling_temporary_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch, overwrite: bool
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "Main.lean").write_text("theorem main : True := by trivial\n")
    submission = await submit_project("first", str(project_dir))
    output = tmp_path / "project.tar.gz"
    if overwrite:
        output.write_bytes(b"keep")
    replacements: list[tuple[str, str]] = []
    original_replace = mock_downloads.os.replace

    def replace(source: str, destination: str) -> None:
        replacements.append((source, destination))
        original_replace(source, destination)

    assert not isinstance(submission, ErrorResult)
    project, _ = submission
    monkeypatch.setattr(mock_downloads.os, "replace", replace)
    result = await mock_downloads.download_project_files(project.project_id, str(output), overwrite)

    assert not isinstance(result, ErrorResult)
    assert len(replacements) == 1
    temporary, destination = replacements[0]
    assert Path(temporary).parent == output.parent
    assert temporary != destination
    assert destination == str(output)
    assert output.stat().st_size > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("overwrite", [False, True])
async def test_mock_download_cleans_interrupted_temporary_write(
    tmp_path, monkeypatch: pytest.MonkeyPatch, overwrite: bool
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "Main.lean").write_text("theorem main : True := by trivial\n")
    submission = await submit_project("first", str(project_dir))
    output = tmp_path / "project.tar.gz"
    if overwrite:
        output.write_bytes(b"keep")

    def replace(source: str, destination: str) -> None:
        _ = source, destination
        raise OSError("interrupted")

    assert not isinstance(submission, ErrorResult)
    project, _ = submission
    monkeypatch.setattr(mock_downloads.os, "replace", replace)
    result = await mock_downloads.download_project_files(project.project_id, str(output), overwrite)

    assert isinstance(result, ErrorResult)
    assert not list(tmp_path.glob(".project.tar.gz.*"))
    if overwrite:
        assert output.read_bytes() == b"keep"
    else:
        assert not output.exists()
