"""Deterministic archive downloads for native mock projects."""

from __future__ import annotations

import gzip
import os
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

from aristotle_mcp.files import _best_effort_remove, _remove_reserved_path, _reserve_download_path
from aristotle_mcp.mock_state import MockProject, state
from aristotle_mcp.models import ErrorResult, ProjectFilesResult


def _error(message: str) -> ErrorResult:
    return ErrorResult("error", "validation", message)


def _archive(project: MockProject) -> bytes:
    output = BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as compressed, tarfile.open(
        fileobj=compressed,
        mode="w",
    ) as archive:
        for name in sorted(project.source_files):
            data = project.source_files[name]
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0
            archive.addfile(info, BytesIO(data))
    return output.getvalue()


async def download_project_files(
    project_id: str,
    output_path: Path | str | None = None,
    overwrite: bool = False,
) -> ProjectFilesResult | ErrorResult:
    """Write a deterministic project archive without unsafe overwrites."""
    with state.lock:
        project = state.projects.get(project_id)
        if project is None:
            return _error(f"Unknown project ID: {project_id}")
        if not project.has_files and not project.has_input:
            return ErrorResult("error", "api", "Project has no files or input to download")
        archive = _archive(project)
    try:
        destination, reserved = _reserve_download_path(
            project_id,
            str(output_path) if output_path is not None else None,
            ".tar.gz",
            overwrite,
        )
    except FileExistsError:
        return ErrorResult("error", "filesystem", f"Output file already exists: {output_path}")
    temporary: Path | None = None
    try:
        fd, temporary_name = tempfile.mkstemp(
            dir=Path(destination).parent,
            prefix=f".{Path(destination).name}.",
        )
        temporary = Path(temporary_name)
        with os.fdopen(fd, "wb") as file:
            file.write(archive)
        os.replace(temporary, destination)
        temporary = None
    except OSError:
        _remove_reserved_path(destination, reserved)
        return ErrorResult("error", "filesystem", "Could not write project files")
    finally:
        if temporary is not None:
            _best_effort_remove(temporary)
    return ProjectFilesResult(
        "complete",
        project_id,
        str(Path(destination).resolve()),
        "Project files downloaded",
    )
