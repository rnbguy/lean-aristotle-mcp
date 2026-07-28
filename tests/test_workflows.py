import io
import os
import tarfile

import pytest

from aristotle_mcp import mock_tasks, mock_workflows, workflows
from aristotle_mcp.files import _copy_lean_from_solution_archive
from aristotle_mcp.mock_state import reset_state, state
from aristotle_mcp.models import (
    ErrorResult,
    EventResult,
    ProjectResult,
    TaskResult,
    WaitTaskResult,
)


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
async def test_prove_accepts_exact_utf8_byte_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    submitted_sizes: list[int] = []

    async def submit(_prompt: str, project_dir: str | None = None) -> ErrorResult:
        assert project_dir is not None
        submitted_sizes.append(os.path.getsize(os.path.join(project_dir, "proof.lean")))
        return ErrorResult("error", "api", "stop")

    monkeypatch.setattr(workflows, "submit_project", submit)
    await workflows.prove("\u00e9" * (workflows._MAX_CODE_SIZE // 2), wait=False)

    assert submitted_sizes == [workflows._MAX_CODE_SIZE]


@pytest.mark.asyncio
async def test_prove_rejects_one_utf8_byte_over_limit_without_state_mutation() -> None:
    reset_state()
    code = "\u00e9" * (workflows._MAX_CODE_SIZE // 2) + "a"

    result = await workflows.prove(code, wait=False)

    assert result == ErrorResult(
        "error",
        "validation",
        "Code exceeds maximum size of 1000000 bytes.",
    )
    assert state.projects == {}


@pytest.mark.asyncio
async def test_prove_rejects_non_utf8_encodable_code_without_state_mutation() -> None:
    reset_state()

    result = await workflows.prove("theorem demo : True := by sorry\ud800", wait=False)

    assert result == ErrorResult(
        "error",
        "validation",
        "Code must be UTF-8 encodable.",
    )
    assert "\ud800" not in result.message
    assert state.projects == {}


@pytest.mark.asyncio
async def test_formalize_accepts_exact_utf8_byte_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    submitted_sizes: list[int] = []

    async def submit(_prompt: str, project_dir: str | None = None) -> ErrorResult:
        assert project_dir is not None
        submitted_sizes.append(os.path.getsize(os.path.join(project_dir, "description.txt")))
        return ErrorResult("error", "api", "stop")

    monkeypatch.setattr(workflows, "submit_project", submit)
    await workflows.formalize(
        "\u00e9" * (workflows._MAX_DESCRIPTION_SIZE // 2), wait=False
    )

    assert submitted_sizes == [workflows._MAX_DESCRIPTION_SIZE]


@pytest.mark.asyncio
async def test_formalize_rejects_one_utf8_byte_over_limit_without_state_mutation() -> None:
    reset_state()
    description = "\u00e9" * (workflows._MAX_DESCRIPTION_SIZE // 2) + "a"

    result = await workflows.formalize(description, wait=False)

    assert result == ErrorResult(
        "error",
        "validation",
        "Description exceeds maximum size of 100000 bytes.",
    )
    assert state.projects == {}


@pytest.mark.asyncio
async def test_formalize_rejects_non_utf8_encodable_description_without_state_mutation() -> None:
    reset_state()

    result = await workflows.formalize("True is provable.\ud800", wait=False)

    assert result == ErrorResult(
        "error",
        "validation",
        "Description must be UTF-8 encodable.",
    )
    assert "\ud800" not in result.message
    assert state.projects == {}


@pytest.mark.asyncio
async def test_prove_file_accepts_exact_byte_limit(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    source = tmp_path / "proof.lean"
    with source.open("wb") as file:
        file.truncate(workflows._MAX_FILE_SIZE)

    async def submit(_prompt: str, project_dir: str | None = None) -> ErrorResult:
        return ErrorResult("error", "api", project_dir or "")

    monkeypatch.setattr(workflows, "submit_project", submit)
    result = await workflows.prove_file(str(source), wait=False)

    assert result == ErrorResult("error", "api", str(tmp_path))


@pytest.mark.asyncio
async def test_prove_file_rejects_one_byte_over_limit_before_output_reservation(
    tmp_path,
) -> None:
    reset_state()
    source = tmp_path / "proof.lean"
    with source.open("wb") as file:
        file.truncate(workflows._MAX_FILE_SIZE + 1)
    output = tmp_path / "output.lean"

    result = await workflows.prove_file(str(source), str(output))

    assert result == ErrorResult(
        "error",
        "validation",
        "File exceeds maximum size of 10000000 bytes.",
    )
    assert state.projects == {}
    assert not output.exists()


@pytest.mark.asyncio
async def test_production_prove_file_translates_getsize_oserror_without_submission(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    reset_state()
    source = tmp_path / "proof.lean"
    source.write_text("theorem demo : True := by sorry")
    output = tmp_path / "output.lean"

    def fail_getsize(_path: str) -> int:
        raise OSError("stat failed")

    async def fail_submit(*_args, **_kwargs):
        pytest.fail("source stat failures must not submit")

    monkeypatch.setattr(workflows.os.path, "getsize", fail_getsize)
    monkeypatch.setattr(workflows, "_submit_and_wait", fail_submit)

    result = await workflows.prove_file(str(source), str(output))

    assert result == ErrorResult("error", "filesystem", "stat failed")
    assert state.projects == {}
    assert not output.exists()


@pytest.mark.asyncio
async def test_production_prove_file_rejects_invalid_utf8_without_submission(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    reset_state()
    source = tmp_path / "proof.lean"
    source.write_bytes(b"\xff")
    output = tmp_path / "output.lean"

    async def fail_submit(*_args, **_kwargs):
        pytest.fail("invalid UTF-8 source must not submit")

    monkeypatch.setattr(workflows, "_submit_and_wait", fail_submit)

    result = await workflows.prove_file(str(source), str(output))

    assert result == ErrorResult("error", "validation", "File must be valid UTF-8.")
    assert state.projects == {}
    assert not output.exists()


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
async def test_prove_file_preserves_lake_relative_source_identity(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    project = tmp_path / "project"
    nested = project / "src" / "nested"
    nested.mkdir(parents=True)
    (project / "lakefile.toml").write_text('name = "fixture"\n')
    source = nested / "Target.lean"
    source.write_text("theorem target : True := by sorry\n")
    submitted: list[tuple[str, str, bool, str | None, str | None]] = []

    async def submit_and_wait(
        directory: str,
        prompt: str,
        wait: bool,
        output_path: str | None = None,
        preferred_filename: str | None = None,
    ) -> ErrorResult:
        submitted.append((directory, prompt, wait, output_path, preferred_filename))
        return ErrorResult("error", "api", "stop")

    monkeypatch.setattr(workflows, "_submit_and_wait", submit_and_wait)
    result = await workflows.prove_file(str(source), wait=False)

    assert result == ErrorResult("error", "api", "stop")
    assert submitted == [
        (
            str(project),
            "Please prove all sorry statements in src/nested/Target.lean.",
            False,
            None,
            "src/nested/Target.lean",
        )
    ]


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
async def test_mock_prove_file_translates_read_oserror_without_state_mutation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_state()
    source = tmp_path / "proof.lean"
    source.write_text("theorem demo : True := by sorry")
    output = tmp_path / "output.lean"

    def fail_read_text(_self, **_kwargs) -> str:
        raise OSError("read failed")

    monkeypatch.setattr(mock_workflows.Path, "read_text", fail_read_text)

    result = await mock_workflows.prove_file(str(source), str(output))

    assert result == ErrorResult("error", "filesystem", "read failed")
    assert state.projects == {}
    assert not output.exists()


@pytest.mark.asyncio
async def test_mock_prove_file_rejects_invalid_utf8_without_state_mutation(tmp_path) -> None:
    reset_state()
    source = tmp_path / "proof.lean"
    source.write_bytes(b"\xff")
    output = tmp_path / "output.lean"

    result = await mock_workflows.prove_file(str(source), str(output))

    assert result == ErrorResult("error", "validation", "File must be valid UTF-8.")
    assert state.projects == {}
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
@pytest.mark.parametrize("status", ["failed", "canceled"])
async def test_production_submit_does_not_write_failed_or_canceled_output(
    tmp_path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    output = tmp_path / "output.lean"
    project = ProjectResult("project", "running", "now", "now", None, True, True)
    submitted_task = TaskResult("project", "task", "queued", "now", "now", None, None, None, None)
    terminal_task = TaskResult("project", "task", status, "now", "now", None, None, None, None)

    async def submit(_prompt: str, project_dir: str | None = None):
        _ = project_dir
        return project, submitted_task

    async def wait(_task_id: str) -> WaitTaskResult:
        return WaitTaskResult("terminal", terminal_task, None, "Task reached a terminal status.")

    async def copy_code(
        _project_id: str, _output_path: str, _preferred_filename: str | None
    ) -> str | None:
        pytest.fail("failed and canceled tasks must not download artifacts")

    monkeypatch.setattr(workflows, "submit_project", submit)
    monkeypatch.setattr(workflows, "wait_task", wait)
    monkeypatch.setattr(workflows, "_copy_code", copy_code)
    result = await workflows._submit_and_wait(str(tmp_path), "prompt", True, str(output))

    assert not isinstance(result, ErrorResult)
    assert result.status == status
    assert result.code is None
    assert result.output_path is None
    assert result.message == "Task reached a terminal status."
    assert not output.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "canceled"])
async def test_mock_submit_does_not_write_failed_or_canceled_output(
    tmp_path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    output = tmp_path / "output.lean"
    project = ProjectResult("project", "running", "now", "now", None, True, True)
    submitted_task = TaskResult("project", "task", "queued", "now", "now", None, None, None, None)
    terminal_task = TaskResult("project", "task", status, "now", "now", None, None, None, None)

    async def submit(_prompt: str, project_dir: str | None = None):
        _ = project_dir
        return project, submitted_task

    async def wait(_task_id: str) -> WaitTaskResult:
        return WaitTaskResult("terminal", terminal_task, None, "Task reached a terminal status.")

    monkeypatch.setattr(mock_workflows, "submit_project", submit)
    monkeypatch.setattr(mock_workflows, "wait_task", wait)
    result = await mock_workflows._submit(str(tmp_path), "prompt", True, "code", str(output))

    assert not isinstance(result, ErrorResult)
    assert result.status == status
    assert result.code is None
    assert result.output_path is None
    assert result.message == "Task reached a terminal status."
    assert not output.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["complete", "complete_with_errors", "out_of_budget"])
async def test_production_submit_preserves_zero_byte_successful_output(
    tmp_path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    output = tmp_path / "output.lean"
    project = ProjectResult("project", "running", "now", "now", None, True, True)
    task = TaskResult("project", "task", status, "now", "now", None, None, None, None)

    async def submit(_prompt: str, project_dir: str | None = None):
        _ = project_dir
        return project, task

    async def wait(_task_id: str) -> WaitTaskResult:
        return WaitTaskResult("terminal", task, None, "Task reached a terminal status.")

    async def copy_code(
        _project_id: str, _output_path: str, _preferred_filename: str | None
    ) -> str | None:
        return str(output)

    monkeypatch.setattr(workflows, "submit_project", submit)
    monkeypatch.setattr(workflows, "wait_task", wait)
    monkeypatch.setattr(workflows, "_copy_code", copy_code)
    result = await workflows._submit_and_wait(str(tmp_path), "prompt", True, str(output))

    assert not isinstance(result, ErrorResult)
    assert result.status == status
    assert result.output_path == str(output)
    assert output.exists()
    assert output.stat().st_size == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["complete", "complete_with_errors", "out_of_budget"])
async def test_mock_submit_preserves_zero_byte_successful_output(
    tmp_path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    output = tmp_path / "output.lean"
    project = ProjectResult("project", "running", "now", "now", None, True, True)
    task = TaskResult("project", "task", status, "now", "now", None, None, None, None)

    async def submit(_prompt: str, project_dir: str | None = None):
        _ = project_dir
        return project, task

    async def wait(_task_id: str) -> WaitTaskResult:
        return WaitTaskResult("terminal", task, None, "Task reached a terminal status.")

    monkeypatch.setattr(mock_workflows, "submit_project", submit)
    monkeypatch.setattr(mock_workflows, "wait_task", wait)
    result = await mock_workflows._submit(str(tmp_path), "prompt", True, "", str(output))

    assert not isinstance(result, ErrorResult)
    assert result.status == status
    assert result.output_path == str(output)
    assert output.exists()
    assert output.stat().st_size == 0


@pytest.mark.asyncio
async def test_production_submit_cleans_reservation_after_unexpected_copy_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    output = tmp_path / "output.lean"
    project = ProjectResult("project", "running", "now", "now", None, True, True)
    task = TaskResult("project", "task", "complete", "now", "now", None, None, None, None)

    async def submit(_prompt: str, project_dir: str | None = None):
        _ = project_dir
        return project, task

    async def wait(_task_id: str) -> WaitTaskResult:
        return WaitTaskResult("terminal", task, None, "Task reached a terminal status.")

    async def copy_code(
        _project_id: str, _output_path: str, _preferred_filename: str | None
    ) -> str | None:
        raise RuntimeError("copy failed")

    monkeypatch.setattr(workflows, "submit_project", submit)
    monkeypatch.setattr(workflows, "wait_task", wait)
    monkeypatch.setattr(workflows, "_copy_code", copy_code)

    with pytest.raises(RuntimeError, match="copy failed"):
        await workflows._submit_and_wait(str(tmp_path), "prompt", True, str(output))

    assert not output.exists()


@pytest.mark.asyncio
async def test_production_submit_cleans_reservation_after_unexpected_wait_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    output = tmp_path / "output.lean"
    project = ProjectResult("project", "running", "now", "now", None, True, True)
    task = TaskResult("project", "task", "queued", "now", "now", None, None, None, None)

    async def submit(_prompt: str, project_dir: str | None = None):
        _ = project_dir
        return project, task

    async def wait(_task_id: str) -> WaitTaskResult:
        raise RuntimeError("wait failed")

    monkeypatch.setattr(workflows, "submit_project", submit)
    monkeypatch.setattr(workflows, "wait_task", wait)

    with pytest.raises(RuntimeError, match="wait failed"):
        await workflows._submit_and_wait(str(tmp_path), "prompt", True, str(output))

    assert not output.exists()


@pytest.mark.asyncio
async def test_mock_submit_cleans_reservation_after_unexpected_wait_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output.lean"
    project = ProjectResult("project", "running", "now", "now", None, True, True)
    task = TaskResult("project", "task", "queued", "now", "now", None, None, None, None)

    async def submit(_prompt: str, project_dir: str | None = None):
        _ = project_dir
        return project, task

    async def wait(_task_id: str) -> WaitTaskResult:
        raise RuntimeError("wait failed")

    monkeypatch.setattr(mock_workflows, "submit_project", submit)
    monkeypatch.setattr(mock_workflows, "wait_task", wait)

    with pytest.raises(RuntimeError, match="wait failed"):
        await mock_workflows._submit(str(tmp_path), "prompt", True, "code", str(output))

    assert not output.exists()


@pytest.mark.asyncio
async def test_mock_submit_cleans_partial_output_after_write_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output.lean"
    project = ProjectResult("project", "running", "now", "now", None, True, True)
    task = TaskResult("project", "task", "queued", "now", "now", None, None, None, None)

    async def submit(_prompt: str, project_dir: str | None = None):
        _ = project_dir
        return project, task

    async def wait(_task_id: str) -> WaitTaskResult:
        terminal_task = TaskResult(
            "project", "task", "complete", "now", "now", None, None, None, None
        )
        return WaitTaskResult("terminal", terminal_task, None, "Task reached a terminal status.")

    def partial_write(self, _data: str, **_kwargs: str | None) -> int:
        self.write_bytes(b"partial")
        raise OSError("write failed")

    monkeypatch.setattr(mock_workflows, "submit_project", submit)
    monkeypatch.setattr(mock_workflows, "wait_task", wait)
    monkeypatch.setattr("pathlib.Path.write_text", partial_write)

    result = await mock_workflows._submit(str(tmp_path), "prompt", True, "code", str(output))

    assert result == ErrorResult("error", "filesystem", "write failed")
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
    prompts: list[str] = []

    async def submit(prompt: str, project_dir: str | None = None) -> ErrorResult:
        prompts.append(prompt)
        submitted.append(project_dir or "")
        return ErrorResult("error", "api", "stop")

    monkeypatch.setattr(mock_workflows, "submit_project", submit)
    result = await mock_workflows.prove_file(str(source), wait=False)

    assert isinstance(result, ErrorResult)
    assert submitted == [str(project)]
    assert prompts == ["Please prove all sorry statements in src/nested/Target.lean."]


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


@pytest.mark.asyncio
async def test_production_workflow_classifies_unsafe_solution_archive_as_archive(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    source = tmp_path / "proof.lean"
    source.write_text("theorem demo : True := by sorry")
    output = tmp_path / "output.lean"
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as result:
        info = tarfile.TarInfo("../escape.lean")
        info.size = 1
        result.addfile(info, io.BytesIO(b"x"))

    async def submit(_prompt: str, project_dir: str | None = None):
        _ = project_dir
        return ProjectResult("project", "running", "now", "now", None, True, True), TaskResult(
            "project", "task", "complete", "now", "now", None, None, None, None
        )

    async def wait(_task_id: str) -> WaitTaskResult:
        task = TaskResult("project", "task", "complete", "now", "now", None, None, None, None)
        return WaitTaskResult("terminal", task, None, "Task reached a terminal status.")

    async def copy_code(
        _project_id: str, output_path: str, _preferred_filename: str | None
    ) -> str | None:
        _copy_lean_from_solution_archive(str(archive), output_path)
        return output_path

    monkeypatch.setattr(workflows, "submit_project", submit)
    monkeypatch.setattr(workflows, "wait_task", wait)
    monkeypatch.setattr(workflows, "_copy_code", copy_code)

    result = await workflows.prove_file(str(source), str(output))

    assert result == ErrorResult(
        "error", "archive", "Unsafe path in solution archive: ../escape.lean"
    )
