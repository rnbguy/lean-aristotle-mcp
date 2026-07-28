import io
import tarfile

import pytest

from aristotle_mcp import mock_tasks, mock_workflows, workflows
from aristotle_mcp.mock_state import reset_state, state
from aristotle_mcp.models import ErrorResult, EventResult, WaitTaskResult


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "true")


@pytest.mark.asyncio
async def test_prove_and_formalize_return_both_native_ids_when_not_waiting() -> None:
    proof = await workflows.prove("theorem demo : True := by sorry", wait=False)
    formalization = await workflows.formalize("True is provable.", wait=False)

    assert not isinstance(proof, ErrorResult)
    assert proof.project_id is not None and proof.task_id is not None
    assert not isinstance(formalization, ErrorResult)
    assert formalization.project_id is not None and formalization.task_id is not None


@pytest.mark.asyncio
async def test_prove_file_preserves_existing_output_and_context_collisions(tmp_path) -> None:
    source = tmp_path / "proof.lean"
    source.write_text("theorem demo : True := by sorry")
    output = tmp_path / "output.lean"
    output.write_text("keep")
    collision = tmp_path / "proof.lean"

    existing = await workflows.prove_file(str(source), str(output))
    collided = await workflows.prove("theorem demo : True := by sorry", [str(collision)])

    assert isinstance(existing, ErrorResult)
    assert output.read_text() == "keep"
    assert isinstance(collided, ErrorResult)
    assert collided.error_type == "validation"


@pytest.mark.asyncio
async def test_prove_file_submits_nearest_lake_ancestor(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    project = tmp_path / "project"
    nested = project / "src" / "nested"
    nested.mkdir(parents=True)
    (project / "lakefile.toml").write_text("name = \"fixture\"\n")
    source = nested / "Target.lean"
    source.write_text("theorem target : True := by sorry\n")
    submitted: list[str] = []

    async def submit(prompt: str, project_dir: str | None = None):
        _ = prompt
        submitted.append(project_dir or "")
        return ErrorResult("error", "api", "stop")

    monkeypatch.setattr(workflows, "submit_project", submit)
    result = await workflows.prove_file(str(source), wait=False)

    assert isinstance(result, ErrorResult)
    assert submitted == [str(project)]


@pytest.mark.asyncio
async def test_mock_prove_file_reserves_output_before_submission(tmp_path) -> None:
    reset_state()
    source = tmp_path / "proof.lean"
    source.write_text("theorem demo : True := by sorry")
    output = tmp_path / "output.lean"
    output.write_text("keep")

    result = await workflows.prove_file(str(source), str(output))

    assert isinstance(result, ErrorResult)
    assert state.projects == {}


@pytest.mark.asyncio
async def test_mock_prove_file_does_not_write_output_after_timeout(tmp_path) -> None:
    reset_state()
    source = tmp_path / "proof.lean"
    source.write_text("theorem demo : True := by sorry")
    output = tmp_path / "output.lean"

    result = await workflows.prove_file(str(source), str(output))

    assert not isinstance(result, ErrorResult)
    assert result.status == "queued"
    assert result.code is None
    assert result.output_path is None
    assert result.message == "Task did not reach a terminal state before the timeout."
    assert not output.exists()


@pytest.mark.asyncio
async def test_mock_submit_does_not_write_output_while_waiting_for_answer(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_state()
    output = tmp_path / "output.lean"

    async def wait_for_answer(task_id: str) -> WaitTaskResult:
        task = await mock_tasks.get_task(task_id)
        assert not isinstance(task, ErrorResult)
        question = EventResult(
            "event",
            task_id,
            "agent_question",
            "sent",
            task.created_at,
            "Need a lemma",
            None,
            None,
            None,
            None,
        )
        return WaitTaskResult(
            "waiting_for_answer", task, question, "Task is waiting for an answer."
        )

    monkeypatch.setattr(mock_workflows, "wait_task", wait_for_answer)
    result = await mock_workflows._submit(str(tmp_path), "prompt", True, "code", str(output))

    assert not isinstance(result, ErrorResult)
    assert result.code is None
    assert result.output_path is None
    assert result.message == "Task is waiting for an answer."
    assert not output.exists()


@pytest.mark.asyncio
async def test_mock_prove_file_submits_nearest_lake_ancestor(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    nested = project / "src" / "nested"
    nested.mkdir(parents=True)
    (project / "lakefile.toml").write_text('name = "fixture"\n')
    source = nested / "Target.lean"
    source.write_text("theorem target : True := by sorry\n")
    submitted: list[str] = []

    async def submit(prompt: str, project_dir: str | None = None) -> ErrorResult:
        _ = prompt
        submitted.append(project_dir or "")
        return ErrorResult("error", "api", "stop")

    monkeypatch.setattr(mock_workflows, "submit_project", submit)
    result = await mock_workflows.prove_file(str(source), wait=False)

    assert isinstance(result, ErrorResult)
    assert submitted == [str(project)]


@pytest.mark.asyncio
async def test_mock_formalize_requests_formalize_filename(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    async def submit(prompt: str, project_dir: str | None = None) -> ErrorResult:
        _ = project_dir
        prompts.append(prompt)
        return ErrorResult("error", "api", "stop")

    monkeypatch.setattr(mock_workflows, "submit_project", submit)
    result = await mock_workflows.formalize("True is provable.", prove=True, wait=False)

    assert isinstance(result, ErrorResult)
    assert len(prompts) == 1
    assert "formalize.lean" in prompts[0]


@pytest.mark.asyncio
async def test_real_prove_file_preflight_conflict_does_not_submit(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    source = tmp_path / "proof.lean"
    source.write_text("theorem demo : True := by sorry")
    output = tmp_path / "output.lean"
    output.write_text("keep")
    submitted: list[str] = []

    async def submit(prompt: str, project_dir: str | None = None):
        _ = prompt, project_dir
        submitted.append("called")
        return ErrorResult("error", "api", "unexpected")

    monkeypatch.setattr(workflows, "submit_project", submit)
    result = await workflows.prove_file(str(source), str(output))

    assert isinstance(result, ErrorResult)
    assert submitted == []
    assert output.read_text() == "keep"


@pytest.mark.asyncio
async def test_archive_extraction_rejects_unsafe_member(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as result:
        info = tarfile.TarInfo("../escape.lean")
        info.size = 1
        result.addfile(info, io.BytesIO(b"x"))

    with pytest.raises(ValueError):
        workflows._read_lean_from_solution_archive(str(archive))
