"""Test the Aristotle MCP tools in mock mode."""

import os
import sys
import tarfile
import types
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest

# Force mock mode for these tests
os.environ["ARISTOTLE_MOCK"] = "true"

from aristotle_mcp.tools import (
    cancel_project,
    check_formalize,
    check_proof,
    check_prove_file,
    formalize,
    get_input,
    get_project,
    get_solution,
    get_solution_if_complete,
    is_mock_mode,
    prove,
    prove_file,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
LEAN_PROJECT_DIR = Path(__file__).parent / "lean_project"


@pytest.fixture
def example_lean_file() -> Path:
    return FIXTURES_DIR / "example.lean"


@pytest.fixture
def lean_project_file() -> Path:
    return LEAN_PROJECT_DIR / "TestProject" / "Arithmetic.lean"


class _FakeStatus:
    """Small status object matching aristotlelib enum behavior used by tools."""

    def __init__(self, name: str) -> None:
        self.name = name


def _write_solution_archive(path: str | Path, files: dict[str, str]) -> None:
    """Write an Aristotle-style solution archive for fake API tests."""
    with tarfile.open(path, "w:gz") as archive:
        for filename, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name=filename)
            info.size = len(data)
            archive.addfile(info, BytesIO(data))


def _install_fake_aristotlelib(monkeypatch: pytest.MonkeyPatch, files: dict[str, str]) -> None:
    """Install a fake aristotlelib module that returns a completed archive project."""

    class FakeProject:
        project_id = "fake-project"
        status = _FakeStatus("COMPLETE")
        percent_complete = 100
        created_at = datetime.now(UTC)
        last_updated_at = datetime.now(UTC)
        input_prompt = None
        file_name = None
        description = None
        output_summary = None

        @classmethod
        async def from_id(cls, project_id: str) -> "FakeProject":
            project = cls()
            project.project_id = project_id
            return project

        async def refresh(self) -> None:
            return None

        async def get_solution(self, destination: str | Path | None = None) -> Path:
            assert destination is not None
            destination_path = Path(destination)
            _write_solution_archive(destination_path, files)
            return destination_path

    fake_module = types.ModuleType("aristotlelib")
    fake_module.__dict__["Project"] = FakeProject
    monkeypatch.setitem(sys.modules, "aristotlelib", fake_module)
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    monkeypatch.setenv("ARISTOTLE_API_KEY", "fake-key")


def test_mock_mode_enabled() -> None:
    """Verify mock mode is active."""
    assert is_mock_mode()


async def test_prove_simple() -> None:
    """Test proving a simple theorem."""
    code = "theorem one_plus_one : 1 + 1 = 2 := by sorry"
    result = await prove(code)

    assert result.status == "proved"
    assert result.code is not None
    assert result.message


async def test_prove_with_hint() -> None:
    """Test proving with a hint."""
    code = "theorem add_comm (a b : Nat) : a + b = b + a := by sorry"
    result = await prove(code, hint="Use induction on a")

    assert result.status == "proved"
    assert result.code is not None


async def test_prove_counterexample() -> None:
    """Test that false theorems return counterexamples."""
    code = "theorem false_theorem : 1 = 2 := by sorry"
    result = await prove(code)

    assert result.status == "counterexample"
    assert result.counterexample is not None


async def test_prove_rejects_context_file_named_proof(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Context files cannot overwrite the generated proof input."""
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    monkeypatch.setenv("ARISTOTLE_API_KEY", "fake-key")
    context_file = tmp_path / "proof.lean"
    context_file.write_text("theorem context : True := by trivial\n")

    result = await prove(
        "theorem submitted : True := by sorry",
        context_files=[str(context_file)],
    )

    assert result.status == "error"
    assert "overwrite" in result.message.lower()


async def test_prove_rejects_duplicate_context_basenames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Context files with duplicate basenames cannot overwrite each other."""
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    monkeypatch.setenv("ARISTOTLE_API_KEY", "fake-key")
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first_context = first_dir / "Context.lean"
    second_context = second_dir / "Context.lean"
    first_context.write_text("theorem first : True := by trivial\n")
    second_context.write_text("theorem second : True := by trivial\n")

    result = await prove(
        "theorem submitted : True := by sorry",
        context_files=[str(first_context), str(second_context)],
    )

    assert result.status == "error"
    assert "overwrite" in result.message.lower()


async def test_prove_async_flow() -> None:
    """Test async submission and polling."""
    code = "theorem async_test : 1 + 1 = 2 := by sorry"

    # Submit without waiting
    result = await prove(code, wait=False)
    assert result.status == "submitted"
    assert result.project_id is not None

    project_id = result.project_id

    # First poll - should be queued or in_progress
    result = await check_proof(project_id)
    assert result.status in ("queued", "in_progress", "proved")
    assert result.project_id == project_id

    # Keep polling until complete (mock progresses each call)
    for _ in range(5):
        result = await check_proof(project_id)
        if result.status == "proved":
            break

    assert result.status == "proved"
    assert result.code is not None


async def test_check_proof_percent_complete() -> None:
    """Test that check_proof returns percent_complete."""
    code = "theorem pct_test : 1 + 1 = 2 := by sorry"

    # Submit
    result = await prove(code, wait=False)
    project_id = result.project_id
    assert project_id is not None

    # First poll - queued, 0%
    result = await check_proof(project_id)
    assert result.status == "queued"
    assert result.percent_complete == 0

    # Second poll - in_progress, 50%
    result = await check_proof(project_id)
    assert result.status == "in_progress"
    assert result.percent_complete == 50

    # Third poll - proved, 100%
    result = await check_proof(project_id)
    assert result.status == "proved"
    assert result.percent_complete == 100


async def test_check_proof_extracts_solution_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real async proof polling extracts Lean code from the result archive."""
    solved_code = "theorem async_archive : True := by trivial\n"
    _install_fake_aristotlelib(monkeypatch, {"proof.lean": solved_code})

    result = await check_proof("fake-proof-project")

    assert result.status == "proved"
    assert result.code == solved_code
    assert result.percent_complete == 100


async def test_prove_file(example_lean_file: Path) -> None:
    """Test proving all sorries in a file."""
    result = await prove_file(str(example_lean_file))

    assert result.status == "proved"
    assert result.message


async def test_prove_file_async(example_lean_file: Path) -> None:
    """Test async file proving with polling and saving."""
    # Submit without waiting
    result = await prove_file(str(example_lean_file), wait=False)
    assert result.status == "submitted"
    assert result.project_id is not None

    project_id = result.project_id

    # First poll - queued (save=True to test file writing)
    result = await check_prove_file(project_id, save=True)
    assert result.status == "queued"
    assert result.percent_complete == 0

    # Second poll - in_progress
    result = await check_prove_file(project_id, save=True)
    assert result.status == "in_progress"
    assert result.percent_complete == 50

    # Third poll - complete with output_path
    result = await check_prove_file(project_id, save=True)
    assert result.status == "proved"
    assert result.percent_complete == 100
    assert result.output_path is not None


async def test_prove_file_not_found() -> None:
    """Test error handling for missing files."""
    result = await prove_file("/nonexistent/file.lean")

    assert result.status == "error"
    assert "not found" in result.message.lower()


async def test_prove_file_output_exists(example_lean_file: Path, tmp_path: Path) -> None:
    """Test error when output file already exists."""
    # Use tmp_path to avoid touching any real files
    test_output_path = tmp_path / "existing_output.lean"
    test_output_path.write_text("-- existing file for test")

    result = await prove_file(str(example_lean_file), output_path=str(test_output_path))

    assert result.status == "error"
    assert "already exists" in result.message.lower()
    # tmp_path is automatically cleaned up by pytest


async def test_prove_lean_project(lean_project_file: Path, tmp_path: Path) -> None:
    """Test proving a file from the lean_project test fixture."""
    # Use tmp_path for output to avoid touching any real files
    test_output_path = tmp_path / "Arithmetic_solved.lean"

    result = await prove_file(str(lean_project_file), output_path=str(test_output_path))

    assert result.status == "proved"
    assert result.output_path is not None
    # tmp_path is automatically cleaned up by pytest


async def test_formalize() -> None:
    """Test formalizing natural language."""
    result = await formalize("The sum of two even numbers is even")

    assert result.status == "formalized"
    assert result.lean_code is not None
    assert "theorem" in result.lean_code.lower() or "def" in result.lean_code.lower()


async def test_formalize_and_prove() -> None:
    """Test formalizing and proving."""
    result = await formalize("1 + 1 = 2", prove=True)

    assert result.status == "proved"
    assert result.lean_code is not None


async def test_formalize_with_context(example_lean_file: Path) -> None:
    """Test formalizing with a context file."""
    result = await formalize(
        "Prove something using the definitions",
        context_file=str(example_lean_file),
    )

    assert result.status == "formalized"
    assert result.lean_code is not None
    assert "example" in result.lean_code.lower()  # Should reference the context file
    assert "context" in result.message.lower()


async def test_formalize_rejects_context_file_named_description(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Formalize context cannot overwrite the generated description input."""
    monkeypatch.setenv("ARISTOTLE_MOCK", "false")
    monkeypatch.setenv("ARISTOTLE_API_KEY", "fake-key")
    context_file = tmp_path / "description.txt"
    context_file.write_text("context")

    result = await formalize("A natural-language theorem", context_file=str(context_file))

    assert result.status == "error"
    assert "overwrite" in result.message.lower()


async def test_formalize_async() -> None:
    """Test async formalization with polling."""
    from aristotle_mcp.tools import check_formalize

    # Submit without waiting
    result = await formalize("The sum of two even numbers is even", wait=False)
    assert result.status == "submitted"
    assert result.project_id is not None

    project_id = result.project_id

    # First poll - queued
    result = await check_formalize(project_id)
    assert result.status == "queued"
    assert result.percent_complete == 0

    # Second poll - in_progress
    result = await check_formalize(project_id)
    assert result.status == "in_progress"
    assert result.percent_complete == 50

    # Third poll - complete
    result = await check_formalize(project_id)
    assert result.status == "formalized"
    assert result.percent_complete == 100
    assert result.lean_code is not None


async def test_check_formalize_extracts_solution_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real async formalization polling extracts Lean code from the result archive."""
    lean_code = "theorem formalized_archive : True := by trivial\n"
    _install_fake_aristotlelib(monkeypatch, {"solution.lean": lean_code})

    result = await check_formalize("fake-formalize-project")

    assert result.status == "formalized"
    assert result.lean_code == lean_code
    assert result.percent_complete == 100


async def test_formalize_async_with_prove() -> None:
    """Test async formalization with prove=True."""
    from aristotle_mcp.tools import check_formalize

    # Submit with prove=True
    result = await formalize("addition is commutative", prove=True, wait=False)
    assert result.status == "submitted"
    assert result.project_id is not None

    project_id = result.project_id

    # Poll until complete
    for _ in range(5):
        result = await check_formalize(project_id)
        if result.status == "proved":
            break

    assert result.status == "proved"
    assert result.lean_code is not None


async def test_check_formalize_unknown_project() -> None:
    """Test check_formalize with unknown project ID."""
    from aristotle_mcp.tools import check_formalize

    result = await check_formalize("nonexistent-project-id")
    assert result.status == "error"
    assert "unknown" in result.message.lower()


async def test_check_prove_file_default_no_save(example_lean_file: Path) -> None:
    """Test check_prove_file defaults to save=False (status only)."""
    # Submit without waiting
    result = await prove_file(str(example_lean_file), wait=False)
    assert result.status == "submitted"
    assert result.project_id is not None

    project_id = result.project_id

    # Poll until complete (using default save=False)
    for _ in range(5):
        result = await check_prove_file(project_id)
        if result.status == "proved":
            break

    # Should be complete but without output_path since save=False is default
    assert result.status == "proved"
    assert result.output_path is None
    assert "save=True" in result.message

    # Now call with save=True to actually write
    result = await check_prove_file(project_id, save=True)
    assert result.status == "proved"
    assert result.output_path is not None


async def test_check_prove_file_in_progress(example_lean_file: Path) -> None:
    """Test polling during in_progress status."""
    # Submit without waiting
    result = await prove_file(str(example_lean_file), wait=False)
    project_id = result.project_id
    assert project_id is not None

    # First poll - queued
    result = await check_prove_file(project_id)
    assert result.status == "queued"
    assert result.percent_complete == 0

    # Second poll - in_progress
    result = await check_prove_file(project_id)
    assert result.status == "in_progress"
    assert result.percent_complete == 50


async def test_check_prove_file_override_output_path(
    example_lean_file: Path, tmp_path: Path
) -> None:
    """Test that output_path can be overridden when saving."""
    # Submit without waiting (default output would be example_aristotle.lean)
    result = await prove_file(str(example_lean_file), wait=False)
    project_id = result.project_id
    assert project_id is not None

    # Poll until complete
    for _ in range(5):
        result = await check_prove_file(project_id)
        if result.status == "proved":
            break

    # Now save with a different output path
    custom_output = str(tmp_path / "custom_output.lean")
    result = await check_prove_file(project_id, output_path=custom_output, save=True)

    assert result.status == "proved"
    assert result.output_path == custom_output


async def test_check_prove_file_save_extracts_solution_archive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Async file polling saves the Lean member, not the raw archive."""
    solved_code = "theorem file_archive : True := by trivial\n"
    _install_fake_aristotlelib(monkeypatch, {"input.lean": solved_code})
    output_path = tmp_path / "solved.lean"

    result = await check_prove_file(
        "fake-file-project",
        output_path=str(output_path),
        save=True,
    )

    assert result.status == "proved"
    assert result.output_path == str(output_path)
    assert output_path.read_text() == solved_code
    assert not tarfile.is_tarfile(output_path)


async def test_check_prove_file_save_prefers_matching_basename(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Async file polling saves the matching Lean file from multi-file archives."""
    expected_code = "theorem target_archive : True := by trivial\n"
    other_code = "theorem context_archive : True := by trivial\n"
    _install_fake_aristotlelib(
        monkeypatch,
        {
            "Context.lean": other_code,
            "src/Target.lean": expected_code,
        },
    )
    from aristotle_mcp import tools

    output_path = tmp_path / "solved.lean"
    tools._async_job_metadata["fake-file-project"] = {
        "file_path": str(tmp_path / "Target.lean"),
        "output_path": str(output_path),
        "timestamp": 0,
    }

    result = await check_prove_file("fake-file-project", save=True)

    assert result.status == "proved"
    assert result.output_path == str(output_path)
    assert output_path.read_text() == expected_code


async def test_check_prove_file_save_requires_output_path(example_lean_file: Path) -> None:
    """Test that save=True requires output_path when metadata is cleared."""
    # This tests the edge case where metadata is gone and no output_path is provided.
    # In mock mode, the stored output_path is used, but we can test the real API
    # behavior by passing output_path=None explicitly after metadata would be cleared.

    # For mock mode, we just verify the workflow makes sense:
    # Submit, poll to complete, then save requires knowing where to save
    result = await prove_file(str(example_lean_file), wait=False)
    project_id = result.project_id
    assert project_id is not None

    # Poll until complete (status only)
    for _ in range(5):
        result = await check_prove_file(project_id)
        if result.status == "proved":
            break

    assert result.status == "proved"
    # Message should indicate save=True is needed
    assert "save=True" in result.message


async def test_get_project_from_known_async_job() -> None:
    """Test retrieving metadata for a known project."""
    submit_result = await prove("theorem project_meta : True := by sorry", wait=False)
    assert submit_result.project_id is not None

    result = await get_project(submit_result.project_id)

    assert result.status == "queued"
    assert result.raw_status == "QUEUED"
    assert result.project_id == submit_result.project_id
    assert result.percent_complete == 0


async def test_cancel_project() -> None:
    """Test canceling a known project."""
    submit_result = await prove("theorem cancel_me : True := by sorry", wait=False)
    assert submit_result.project_id is not None

    result = await cancel_project(submit_result.project_id)

    assert result.status == "canceled"
    assert result.raw_status == "CANCELED"
    assert result.project_id == submit_result.project_id


async def test_cancel_project_unknown() -> None:
    """Test cancel_project with an unknown project ID."""
    result = await cancel_project("missing-project")

    assert result.status == "error"
    assert "unknown" in result.message.lower()


async def test_get_solution_if_complete_not_ready() -> None:
    """Test get_solution_if_complete avoids writing for in-progress projects."""
    submit_result = await prove("theorem not_ready : True := by sorry", wait=False)
    assert submit_result.project_id is not None

    result = await get_solution_if_complete(submit_result.project_id)

    assert result.status == "queued"
    assert result.output_path is None
    assert "not complete" in result.message.lower()


async def test_get_solution_downloads_archive(tmp_path: Path) -> None:
    """Test downloading a completed mock solution archive."""
    prove_result = await prove("theorem solution_archive : True := by sorry")
    assert prove_result.project_id is not None
    output_path = tmp_path / "solution.tar.gz"

    result = await get_solution(prove_result.project_id, output_path=str(output_path))

    assert result.status == "saved"
    assert result.output_path == str(output_path)
    assert output_path.exists()
    with tarfile.open(output_path, "r:gz") as archive:
        assert "solution.lean" in archive.getnames()


async def test_get_solution_refuses_overwrite(tmp_path: Path) -> None:
    """Test solution downloads do not overwrite existing files by default."""
    prove_result = await prove("theorem no_overwrite : True := by sorry")
    assert prove_result.project_id is not None
    output_path = tmp_path / "solution.tar.gz"
    output_path.write_text("existing")

    result = await get_solution(prove_result.project_id, output_path=str(output_path))

    assert result.status == "error"
    assert "already exists" in result.message.lower()


async def test_get_input_downloads_archive(tmp_path: Path) -> None:
    """Test downloading a mock input archive."""
    prove_result = await prove("theorem input_archive : True := by sorry")
    assert prove_result.project_id is not None
    output_path = tmp_path / "input.tar.gz"

    result = await get_input(prove_result.project_id, output_path=str(output_path))

    assert result.status == "saved"
    assert result.output_path == str(output_path)
    assert output_path.exists()
    with tarfile.open(output_path, "r:gz") as archive:
        assert "input.txt" in archive.getnames()
