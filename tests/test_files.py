import builtins
import io
import logging
import os
import tarfile

import pytest

from aristotle_mcp import files
from aristotle_mcp.files import (
    _canonicalize_path,
    _copy_lean_from_solution_archive,
    _duplicate_context_basename_error,
    _extract_solution_archive,
    _find_lean_file,
    _find_unique_path,
    _remove_reserved_path,
    _reserve_download_path,
    _reserve_output_path,
)


def make_archive(path, members):
    with tarfile.open(path, "w:gz") as archive:
        for name, content in members:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))


def make_special_archive(path, member):
    with tarfile.open(path, "w:gz") as archive:
        archive.addfile(member)


def force_fallback(monkeypatch):
    def without_data_filter(value, name):
        if value is tarfile and name == "data_filter":
            return False
        return builtins.hasattr(value, name)

    monkeypatch.setattr(files, "hasattr", without_data_filter, raising=False)


def test_paths_and_reservation(tmp_path):
    path = tmp_path / "x.lean"
    path.touch()
    unique = _find_unique_path(str(path))
    assert unique.endswith("x.1.lean")
    assert _canonicalize_path(".") == os.path.realpath(os.getcwd())
    reserved, created = _reserve_download_path("p", str(tmp_path / "out"), ".tar.gz", False)
    assert created and os.path.exists(reserved)
    with pytest.raises(FileExistsError):
        _reserve_download_path("p", str(tmp_path / "out"), ".tar.gz", False)
    assert os.path.getsize(reserved) == 0


def test_find_unique_path_removes_placeholder_when_close_fails(tmp_path, monkeypatch):
    path = tmp_path / "reserved"
    original_close = os.close

    def close_then_fail(descriptor):
        original_close(descriptor)
        raise OSError("close failed")

    monkeypatch.setattr(os, "close", close_then_fail)
    with pytest.raises(OSError, match="close failed"):
        _find_unique_path(str(path))
    assert not path.exists()


def test_reserve_download_path_removes_placeholder_when_close_fails(tmp_path, monkeypatch):
    path = tmp_path / "reserved"
    original_close = os.close

    def close_then_fail(descriptor):
        original_close(descriptor)
        raise OSError("close failed")

    monkeypatch.setattr(os, "close", close_then_fail)
    with pytest.raises(OSError, match="close failed"):
        _reserve_download_path("project", str(path), ".tar.gz", False)
    assert not path.exists()


def test_reserve_output_path_removes_placeholder_when_close_fails(tmp_path, monkeypatch):
    path = tmp_path / "reserved"
    original_close = os.close

    def close_then_fail(descriptor):
        original_close(descriptor)
        raise OSError("close failed")

    monkeypatch.setattr(os, "close", close_then_fail)
    with pytest.raises(OSError, match="close failed"):
        _reserve_output_path(str(path))
    assert not path.exists()


def test_archive_selection_and_atomic_copy(tmp_path):
    archive = tmp_path / "solution.tar.gz"
    make_archive(archive, [("z.lean", b"z"), ("a.lean", b"a")])
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    _extract_solution_archive(str(archive), str(extract_dir))
    assert _find_lean_file(str(extract_dir)) == str(extract_dir / "a.lean")
    assert _find_lean_file(str(extract_dir), "missing.lean") is None
    output = tmp_path / "out.lean"
    output.write_text("old")
    assert _copy_lean_from_solution_archive(str(archive), str(output), "z.lean")
    assert output.read_text() == "z"

    duplicate = tmp_path / "duplicate.tar.gz"
    make_archive(duplicate, [("b/shared.lean", b"b"), ("a/shared.lean", b"a")])
    duplicate_dir = tmp_path / "duplicate-extract"
    duplicate_dir.mkdir()
    _extract_solution_archive(str(duplicate), str(duplicate_dir))
    selected = _find_lean_file(str(duplicate_dir), "shared.lean")
    assert selected is None


def test_read_solution_archive_decodes_lean_as_utf8(tmp_path, monkeypatch):
    archive = tmp_path / "utf8.tar.gz"
    content = "-- caf\u00e9\n".encode("utf-8")
    make_archive(archive, [("solution.lean", content)])
    real_open = open

    def checked_open(path, *args, **kwargs):
        assert kwargs["encoding"] == "utf-8"
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(files, "open", checked_open, raising=False)

    assert files._read_lean_from_solution_archive(str(archive)) == "-- caf\u00e9\n"


def test_read_solution_archive_returns_content_when_cleanup_raises(tmp_path, monkeypatch):
    archive = tmp_path / "solution.tar.gz"
    make_archive(archive, [("solution.lean", b"proof")])

    def fail_rmtree(*_args, **_kwargs):
        raise OSError("cleanup failed")

    monkeypatch.setattr(files.shutil, "rmtree", fail_rmtree)

    assert files._read_lean_from_solution_archive(str(archive)) == "proof"


def test_read_solution_archive_preserves_archive_error_when_cleanup_raises(tmp_path, monkeypatch):
    archive = tmp_path / "invalid.tar.gz"
    archive.write_bytes(b"not a gzip archive")

    def fail_rmtree(*_args, **_kwargs):
        raise OSError("cleanup failed")

    monkeypatch.setattr(files.shutil, "rmtree", fail_rmtree)

    with pytest.raises(tarfile.ReadError):
        files._read_lean_from_solution_archive(str(archive))


def test_archive_selection_matches_exact_directory_preferred_path(tmp_path):
    archive = tmp_path / "duplicate-target.tar.gz"
    make_archive(
        archive,
        [
            ("src/nested/Target.lean", b"source"),
            ("other/Target.lean", b"other"),
        ],
    )
    extract_dir = tmp_path / "duplicate-target-extract"
    extract_dir.mkdir()
    _extract_solution_archive(str(archive), str(extract_dir))

    assert _find_lean_file(
        str(extract_dir), "src/nested/Target.lean"
    ) == str(extract_dir / "src" / "nested" / "Target.lean")
    assert _find_lean_file(
        str(extract_dir), r"src\nested\Target.lean"
    ) == str(extract_dir / "src" / "nested" / "Target.lean")
    assert _find_lean_file(str(extract_dir), "missing/Target.lean") is None
    assert _find_lean_file(str(extract_dir), "Target.lean") is None

    output = tmp_path / "Target.lean"
    assert _copy_lean_from_solution_archive(
        str(archive), str(output), "src/nested/Target.lean"
    )
    assert output.read_text() == "source"


def test_archive_selection_does_not_match_nested_file_for_root_preference(tmp_path):
    archive = tmp_path / "nested-target.tar.gz"
    make_archive(archive, [("nested/Target.lean", b"nested")])
    extract_dir = tmp_path / "nested-target-extract"
    extract_dir.mkdir()
    _extract_solution_archive(str(archive), str(extract_dir))

    assert _find_lean_file(str(extract_dir), "Target.lean") is None


def test_archive_rejects_escape_and_links(tmp_path):
    archive = tmp_path / "unsafe.tar.gz"
    make_archive(archive, [("../escape.lean", b"bad")])
    with pytest.raises(ValueError):
        _extract_solution_archive(str(archive), str(tmp_path / "extract"))

    absolute = tmp_path / "absolute.tar.gz"
    make_archive(absolute, [("/absolute.lean", b"bad")])
    with pytest.raises(ValueError):
        _extract_solution_archive(str(absolute), str(tmp_path / "extract-absolute"))

    symlink = tarfile.TarInfo("link.lean")
    symlink.type = tarfile.SYMTYPE
    symlink.linkname = "target.lean"
    symlink_archive = tmp_path / "symlink.tar.gz"
    make_special_archive(symlink_archive, symlink)
    with pytest.raises(ValueError):
        _extract_solution_archive(str(symlink_archive), str(tmp_path / "extract-link"))

    hardlink = tarfile.TarInfo("hard.lean")
    hardlink.type = tarfile.LNKTYPE
    hardlink.linkname = "target.lean"
    hardlink_archive = tmp_path / "hardlink.tar.gz"
    make_special_archive(hardlink_archive, hardlink)
    with pytest.raises(ValueError):
        _extract_solution_archive(str(hardlink_archive), str(tmp_path / "extract-hardlink"))


@pytest.mark.parametrize("member_type", [tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE])
def test_archive_rejects_special_members_before_fallback_extraction(
    tmp_path, monkeypatch, member_type
):
    archive = tmp_path / "special.tar.gz"
    member = tarfile.TarInfo("special")
    member.type = member_type
    make_special_archive(archive, member)
    force_fallback(monkeypatch)
    monkeypatch.setattr(
        tarfile.TarFile,
        "extractall",
        lambda *_args, **_kwargs: pytest.fail("unsafe special member reached extractall"),
    )

    with pytest.raises(ValueError):
        _extract_solution_archive(str(archive), str(tmp_path / "extract"))


@pytest.mark.filterwarnings("ignore:Python 3.14 will.*:DeprecationWarning")
def test_regular_files_and_directories_extract_on_fallback(tmp_path, monkeypatch):
    archive = tmp_path / "regular.tar.gz"
    with tarfile.open(archive, "w:gz") as result:
        directory = tarfile.TarInfo("directory")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        result.addfile(directory)
        file = tarfile.TarInfo("directory/file.lean")
        file.size = 1
        file.mode = 0o644
        result.addfile(file, io.BytesIO(b"x"))
    force_fallback(monkeypatch)
    extract_dir = tmp_path / "extract"

    _extract_solution_archive(str(archive), str(extract_dir))

    assert (extract_dir / "directory").is_dir()
    assert (extract_dir / "directory" / "file.lean").read_text() == "x"


def test_fallback_normalizes_hostile_member_modes(tmp_path, monkeypatch):
    archive = tmp_path / "mode-zero.tar.gz"
    with tarfile.open(archive, "w:gz") as result:
        directory = tarfile.TarInfo("directory")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0
        result.addfile(directory)
        file = tarfile.TarInfo("directory/file.lean")
        file.size = 1
        file.mode = 0
        result.addfile(file, io.BytesIO(b"x"))
    force_fallback(monkeypatch)
    captured: list[tuple[str, int]] = []

    def capture_extractall(tar, _path):
        captured.extend((member.name, member.mode) for member in tar.getmembers())

    monkeypatch.setattr(tarfile.TarFile, "extractall", capture_extractall)

    _extract_solution_archive(str(archive), str(tmp_path / "extract"))

    assert captured == [("directory", 0o700), ("directory/file.lean", 0o600)]


def test_cleanup_logs_failures(tmp_path, caplog, monkeypatch):
    path = tmp_path / "reserved"
    path.write_text("")
    monkeypatch.setattr(os, "unlink", lambda _: (_ for _ in ()).throw(OSError("no")))
    with caplog.at_level(logging.DEBUG):
        _remove_reserved_path(str(path), True)
    record = next(record for record in caplog.records if record.reason == "best_effort_cleanup")
    assert record.cleanup_path == str(path)
    assert record.recursive is False


def test_reserved_cleanup_logs_getsize_failure(tmp_path, caplog, monkeypatch):
    path = tmp_path / "reserved"
    path.write_text("")

    def fail_getsize(_path):
        raise OSError("size failed")

    monkeypatch.setattr(os.path, "getsize", fail_getsize)
    with caplog.at_level(logging.DEBUG):
        _remove_reserved_path(str(path), True)

    record = next(record for record in caplog.records if record.reason == "best_effort_cleanup")
    assert record.cleanup_path == str(path)
    assert record.recursive is False


def test_best_effort_cleanup_logs_structured_failure(tmp_path, caplog, monkeypatch):
    path = tmp_path / "temporary"
    path.write_text("")

    def fail_unlink(_path):
        raise OSError("cleanup failed")

    monkeypatch.setattr(os, "unlink", fail_unlink)
    with caplog.at_level(logging.DEBUG):
        files._best_effort_remove(str(path))

    record = next(record for record in caplog.records if record.reason == "best_effort_cleanup")
    assert record.cleanup_path == str(path)
    assert record.recursive is False


def test_atomic_copy_preserves_existing_on_failure(tmp_path, monkeypatch):
    archive = tmp_path / "solution.tar.gz"
    make_archive(archive, [("solution.lean", b"new")])
    output = tmp_path / "out.lean"
    output.write_text("old")
    from aristotle_mcp import files
    monkeypatch.setattr(files.shutil, "copy2", lambda *_: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(OSError):
        files._copy_lean_from_solution_archive(str(archive), str(output))
    assert output.read_text() == "old"


def test_atomic_copy_succeeds_when_cleanup_raises(tmp_path, monkeypatch):
    archive = tmp_path / "solution.tar.gz"
    make_archive(archive, [("solution.lean", b"new")])
    output = tmp_path / "out.lean"

    def fail_rmtree(*_args, **_kwargs):
        raise OSError("cleanup failed")

    monkeypatch.setattr(files.shutil, "rmtree", fail_rmtree)

    assert _copy_lean_from_solution_archive(str(archive), str(output))
    assert output.read_text() == "new"


def test_atomic_copy_preserves_primary_error_when_cleanup_raises(tmp_path, monkeypatch):
    archive = tmp_path / "solution.tar.gz"
    make_archive(archive, [("solution.lean", b"new")])
    output = tmp_path / "out.lean"
    output.write_text("old")

    def fail_copy(*_args, **_kwargs):
        raise OSError("copy failed")

    def fail_rmtree(*_args, **_kwargs):
        raise OSError("cleanup failed")

    monkeypatch.setattr(files.shutil, "copy2", fail_copy)
    monkeypatch.setattr(files.shutil, "rmtree", fail_rmtree)

    with pytest.raises(OSError, match="copy failed"):
        _copy_lean_from_solution_archive(str(archive), str(output))
    assert output.read_text() == "old"


def test_atomic_copy_preserves_copy_error_when_temporary_cleanup_raises(tmp_path, monkeypatch):
    archive = tmp_path / "solution.tar.gz"
    make_archive(archive, [("solution.lean", b"new")])
    output = tmp_path / "out.lean"

    def fail_copy(*_args, **_kwargs):
        raise OSError("copy failed")

    original_mkstemp = files.tempfile.mkstemp
    original_unlink = files.os.unlink
    temporary_paths: list[str] = []

    def capture_mkstemp(*args, **kwargs):
        descriptor, temporary_path = original_mkstemp(*args, **kwargs)
        temporary_paths.append(temporary_path)
        return descriptor, temporary_path

    def fail_temporary_unlink(path, *args, **kwargs):
        if str(path) == temporary_paths[0]:
            raise OSError("cleanup failed")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(files.shutil, "copy2", fail_copy)
    monkeypatch.setattr(files.tempfile, "mkstemp", capture_mkstemp)
    monkeypatch.setattr(files.os, "unlink", fail_temporary_unlink)

    with pytest.raises(OSError, match="copy failed"):
        _copy_lean_from_solution_archive(str(archive), str(output))


def test_duplicate_context_names():
    assert _duplicate_context_basename_error(["/a/X.lean"], {"X.lean"})
    assert _duplicate_context_basename_error(["/a/X.lean", "/b/X.lean"], set())
    assert _duplicate_context_basename_error(["/a/X.lean"], set()) is None
