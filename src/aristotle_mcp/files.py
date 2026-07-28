from __future__ import annotations

import logging
import os
import shutil
import tarfile
import tempfile

_logger = logging.getLogger(__name__)


def _find_unique_path(path: str, max_attempts: int = 1000) -> str:
    candidates = [path] + [
        f"{os.path.splitext(path)[0]}.{i}{os.path.splitext(path)[1]}"
        for i in range(1, max_attempts + 1)
    ]
    for candidate in candidates:
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError(f"Could not find unique path after {max_attempts} attempts: {path}")


def _safe_project_filename(project_id: str, suffix: str) -> str:
    safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in project_id)
    return f"{safe_id or 'project'}{suffix}"


def _canonicalize_path(path: str) -> str:
    return os.path.realpath(os.path.abspath(path))


def _lake_root(file_path: str) -> str:
    """Return the nearest ancestor that declares a Lean project."""
    current = os.path.dirname(file_path)
    markers = ("lakefile.lean", "lakefile.toml", "lean-toolchain")
    while current != os.path.dirname(current):
        if any(os.path.exists(os.path.join(current, marker)) for marker in markers):
            return current
        current = os.path.dirname(current)
    return os.path.dirname(file_path)


def _reserve_download_path(
    project_id: str,
    output_path: str | None,
    default_suffix: str,
    overwrite: bool,
) -> tuple[str, bool]:
    if output_path is None:
        default_path = _canonicalize_path(_safe_project_filename(project_id, default_suffix))
        os.makedirs(os.path.dirname(default_path) or ".", exist_ok=True)
        return _find_unique_path(default_path), True
    absolute_path = _canonicalize_path(output_path)
    os.makedirs(os.path.dirname(absolute_path) or ".", exist_ok=True)
    if overwrite:
        return absolute_path, False
    fd = os.open(absolute_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    os.close(fd)
    return absolute_path, True


def _remove_reserved_path(path: str, reserved: bool) -> None:
    if not reserved or not os.path.exists(path):
        return
    try:
        if os.path.getsize(path) == 0:
            os.unlink(path)
    except OSError:
        _logger.debug("Could not remove reserved download path: %s", path, exc_info=True)


def _validate_archive_member(member_name: str, extract_dir: str) -> None:
    destination = os.path.realpath(os.path.join(extract_dir, member_name))
    extract_root = os.path.realpath(extract_dir)
    if os.path.commonpath([extract_root, destination]) != extract_root:
        raise ValueError(f"Unsafe path in solution archive: {member_name}")


def _extract_solution_archive(solution_path: str, extract_dir: str) -> None:
    with tarfile.open(solution_path, "r:gz") as tar:
        for member in tar.getmembers():
            _validate_archive_member(member.name, extract_dir)
            if member.issym() or member.islnk():
                raise ValueError(f"Unsafe link in solution archive: {member.name}")
        if hasattr(tarfile, "data_filter"):
            tar.extractall(extract_dir, filter="data")
        else:
            tar.extractall(extract_dir)


def _find_lean_file(extract_dir: str, preferred_filename: str | None = None) -> str | None:
    paths: list[str] = []
    for root, dirs, files in os.walk(extract_dir):
        dirs.sort()
        paths.extend(os.path.join(root, filename) for filename in sorted(files))
    if preferred_filename is not None:
        preferred = [path for path in paths if os.path.basename(path) == preferred_filename]
        if preferred:
            return preferred[0]
        return None
    lean_paths = [path for path in paths if path.endswith(".lean")]
    return lean_paths[0] if lean_paths else None


def _read_lean_from_solution_archive(
    solution_path: str,
    preferred_filename: str | None = None,
) -> str | None:
    extract_dir = tempfile.mkdtemp()
    try:
        _extract_solution_archive(solution_path, extract_dir)
        lean_path = _find_lean_file(extract_dir, preferred_filename)
        if lean_path is None:
            return None
        with open(lean_path) as file:
            return file.read()
    finally:
        shutil.rmtree(extract_dir)


def _copy_lean_from_solution_archive(
    solution_path: str,
    output_path: str,
    preferred_filename: str | None = None,
) -> bool:
    extract_dir = tempfile.mkdtemp()
    temporary_path: str | None = None
    try:
        _extract_solution_archive(solution_path, extract_dir)
        lean_path = _find_lean_file(extract_dir, preferred_filename)
        if lean_path is None:
            return False
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        fd, temporary_path = tempfile.mkstemp(dir=os.path.dirname(output_path) or ".")
        os.close(fd)
        shutil.copy2(lean_path, temporary_path)
        os.replace(temporary_path, output_path)
        temporary_path = None
        return True
    finally:
        if temporary_path is not None:
            os.unlink(temporary_path)
        shutil.rmtree(extract_dir)


def _duplicate_context_basename_error(
    context_files: list[str],
    reserved_filenames: set[str],
) -> str | None:
    seen = set(reserved_filenames)
    for ctx_file in context_files:
        filename = os.path.basename(ctx_file)
        if filename in seen:
            return f"Context file basename would overwrite another input file: {filename}"
        seen.add(filename)
    return None


def _stage_context_files(
    directory: str,
    context_files: list[str],
    reserved_filenames: set[str],
) -> None:
    """Copy non-colliding context files into a temporary project directory."""
    canonicalized = [_canonicalize_path(path) for path in context_files]
    for source in canonicalized:
        if not os.path.isfile(source):
            raise ValueError(f"Context file not found: {source}")
    basename_error = _duplicate_context_basename_error(canonicalized, reserved_filenames)
    if basename_error is not None:
        raise ValueError(basename_error)
    for source in canonicalized:
        shutil.copy2(source, os.path.join(directory, os.path.basename(source)))


def _reserve_output_path(path: str) -> str:
    """Create an output placeholder so a workflow cannot replace an existing file."""
    canonical = _canonicalize_path(path)
    os.makedirs(os.path.dirname(canonical) or ".", exist_ok=True)
    descriptor = os.open(canonical, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    os.close(descriptor)
    return canonical
