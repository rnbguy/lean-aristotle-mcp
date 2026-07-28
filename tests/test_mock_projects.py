import tarfile
from pathlib import Path

import pytest
from aristotlelib import ProjectStatus

from aristotle_mcp import mock_downloads, mock_projects
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
async def test_mock_submission_rejects_malformed_tar_before_state_mutation(tmp_path) -> None:
    archive = tmp_path / "project.tar.gz"
    archive.write_bytes(b"not a tar archive")

    result = await submit_project("prove", tar_file_path=str(archive))

    assert isinstance(result, ErrorResult)
    assert result.error_type == "validation"
    assert state.projects == {}
    assert state.tasks == {}
    assert state.events == {}


@pytest.mark.asyncio
async def test_mock_submission_rejects_missing_tar_before_state_mutation(tmp_path) -> None:
    result = await submit_project("prove", tar_file_path=str(tmp_path / "missing.tar.gz"))

    assert isinstance(result, ErrorResult)
    assert result.error_type == "filesystem"
    assert state.projects == {}
    assert state.tasks == {}
    assert state.events == {}


@pytest.mark.asyncio
async def test_mock_submission_translates_collection_oserror_before_state_mutation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def collect_directory_files(root: Path) -> dict[str, bytes]:
        _ = root
        raise OSError("collection failed")

    monkeypatch.setattr(mock_projects, "collect_directory_files", collect_directory_files)

    result = await submit_project("prove", project_dir=str(tmp_path))

    assert isinstance(result, ErrorResult)
    assert result.error_type == "filesystem"
    assert state.projects == {}
    assert state.tasks == {}
    assert state.events == {}


@pytest.mark.asyncio
async def test_mock_submission_rejects_both_source_forms_before_state_mutation(tmp_path) -> None:
    archive = tmp_path / "project.tar"
    with tarfile.open(archive, "w"):
        pass

    result = await submit_project(
        "prove",
        project_dir=str(tmp_path),
        tar_file_path=str(archive),
    )

    assert isinstance(result, ErrorResult)
    assert result.error_type == "validation"
    assert state.projects == {}
    assert state.tasks == {}
    assert state.events == {}


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
async def test_mock_continue_rejects_mixed_files_without_mutating_state(tmp_path) -> None:
    submission = await submit_project("initial")
    valid_file = tmp_path / "Context.lean"
    valid_file.write_text("theorem context : True := by trivial\n")
    missing_file = tmp_path / "Missing.lean"

    assert not isinstance(submission, ErrorResult)
    project, task = submission
    assert task is not None
    canceled = await cancel_task(task.task_id)
    source_files = state.projects[project.project_id].source_files.copy()
    has_files = state.projects[project.project_id].has_files
    task_ids = state.projects[project.project_id].task_ids.copy()
    tasks = state.tasks.copy()
    events = state.events.copy()

    result = await continue_project(
        project.project_id,
        "continue",
        [str(valid_file), str(missing_file)],
    )

    assert not isinstance(canceled, ErrorResult)
    assert isinstance(result, ErrorResult)
    assert state.projects[project.project_id].source_files == source_files
    assert state.projects[project.project_id].has_files == has_files
    assert state.projects[project.project_id].task_ids == task_ids
    assert state.tasks == tasks
    assert state.events == events


@pytest.mark.asyncio
async def test_mock_continue_translates_read_oserror_without_mutating_state(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    submission = await submit_project("initial")
    first_file = tmp_path / "First.lean"
    second_file = tmp_path / "Second.lean"
    first_file.write_text("theorem first : True := by trivial\n")
    second_file.write_text("theorem second : True := by trivial\n")

    assert not isinstance(submission, ErrorResult)
    project, task = submission
    assert task is not None
    canceled = await cancel_task(task.task_id)
    project_state = state.projects[project.project_id]
    source_files = project_state.source_files.copy()
    has_files = project_state.has_files
    status = project_state.status
    last_updated = project_state.last_updated
    task_ids = project_state.task_ids.copy()
    tasks = state.tasks.copy()
    events = state.events.copy()
    original_read_bytes = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        if path == second_file:
            raise OSError("read failed")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    result = await continue_project(
        project.project_id,
        "continue",
        [str(first_file), str(second_file)],
    )

    assert not isinstance(canceled, ErrorResult)
    assert isinstance(result, ErrorResult)
    assert result.error_type == "filesystem"
    assert project_state.source_files == source_files
    assert project_state.has_files == has_files
    assert project_state.status == status
    assert project_state.last_updated == last_updated
    assert project_state.task_ids == task_ids
    assert state.tasks == tasks
    assert state.events == events


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


@pytest.mark.asyncio
async def test_mock_download_returns_primary_error_when_temporary_cleanup_raises(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "Main.lean").write_text("theorem main : True := by trivial\n")
    submission = await submit_project("first", str(project_dir))
    output = tmp_path / "project.tar.gz"

    def fail_replace(_source: str, _destination: str) -> None:
        raise OSError("interrupted")

    def fail_unlink(_path: str) -> None:
        raise OSError("cleanup failed")

    assert not isinstance(submission, ErrorResult)
    project, _ = submission
    monkeypatch.setattr(mock_downloads.os, "replace", fail_replace)
    monkeypatch.setattr(mock_downloads.os, "unlink", fail_unlink)
    result = await mock_downloads.download_project_files(project.project_id, str(output))

    assert result == ErrorResult("error", "filesystem", "Could not write project files")


@pytest.mark.asyncio
async def test_mock_download_translates_reservation_permission_error(tmp_path, monkeypatch) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "Main.lean").write_text("theorem main : True := by trivial\n")
    submission = await submit_project("first", str(project_dir))
    output = tmp_path / "project.tar.gz"

    def fail_reservation(*_args, **_kwargs) -> tuple[str, bool]:
        raise PermissionError("reservation denied")

    assert not isinstance(submission, ErrorResult)
    project, _ = submission
    monkeypatch.setattr(mock_downloads, "_reserve_download_path", fail_reservation)
    result = await mock_downloads.download_project_files(project.project_id, str(output))

    assert result == ErrorResult("error", "filesystem", "reservation denied")
    assert not output.exists()


@pytest.mark.asyncio
async def test_mock_download_rolls_back_unexpected_replace_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "Main.lean").write_text("theorem main : True := by trivial\n")
    submission = await submit_project("first", str(project_dir))
    output = tmp_path / "project.tar.gz"

    def fail_replace(_source: str, _destination: str) -> None:
        raise RuntimeError("replace failed")

    assert not isinstance(submission, ErrorResult)
    project, _ = submission
    monkeypatch.setattr(mock_downloads.os, "replace", fail_replace)

    with pytest.raises(RuntimeError, match="replace failed"):
        await mock_downloads.download_project_files(project.project_id, str(output))

    assert not output.exists()
    assert not list(tmp_path.glob(".project.tar.gz.*"))
