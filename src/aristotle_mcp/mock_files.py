"""Typed local project-file filtering matching Aristotle 2.1 behavior."""

from __future__ import annotations

import os
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Final

import pathspec
from pathspec.pattern import Pattern

_STANDARD_PACKAGES: Final = frozenset(
    {
        "Cli",
        "LeanSearchClient",
        "Qq",
        "aesop",
        "batteries",
        "importGraph",
        "mathlib",
        "plausible",
        "proofwidgets",
    }
)
_IGNORED_BASENAMES: Final = (
    ".DS_Store",
    "._*",
    "*.swp",
    "*.swo",
    "*.swn",
    "*~",
    "#*#",
    ".#*",
    ".env",
    ".env.*",
    "*.setup.json",
    "*.olean",
    "*.olean.lock",
    "*.olean.trace",
    "*.olean.hash",
    "*.olean.private",
    "*.olean.private.hash",
    "*.olean.server",
    "*.olean.server.hash",
    "*.ilean",
    "*.ilean.trace",
    "*.ilean.hash",
    "*.trace",
    "*.ir",
    "*.ir.hash",
    "*.o",
    "*.so",
    "*.so.hash",
)


def _load_gitignore(root: Path) -> pathspec.PathSpec[Pattern] | None:
    path = root / ".gitignore"
    if not path.is_file():
        return None
    try:
        lines = path.read_text().splitlines()
        lines.extend(("!.lake", "!.lake/**", "!**/.lake", "!**/.lake/**"))
        return pathspec.PathSpec.from_lines("gitwildmatch", lines)
    except OSError:
        return None


def _is_gitignored(relative: Path, patterns: pathspec.PathSpec[Pattern] | None) -> bool:
    if ".lake" in relative.parts:
        return False
    return patterns.match_file(str(relative)) if patterns is not None else False


def _pruned_dirnames(dirnames: list[str], relative: Path) -> list[str]:
    skip = {".git"}
    parts = relative.parts
    if ".lake" in parts:
        lake_index = parts.index(".lake")
        remaining = parts[lake_index + 1 :]
        if remaining == ("packages",):
            skip.update(_STANDARD_PACKAGES)
        elif remaining == ("build",):
            skip.update({"ir", "bin"})
    return [dirname for dirname in dirnames if dirname not in skip]


def collect_directory_files(root: Path) -> dict[str, bytes]:
    """Collect files using Aristotle's built-in and project ignore rules."""
    files: dict[str, bytes] = {}
    patterns = _load_gitignore(root)
    for directory, dirnames, filenames in os.walk(root):
        relative_directory = Path(directory).relative_to(root)
        dirnames[:] = _pruned_dirnames(dirnames, relative_directory)
        for filename in filenames:
            path = Path(directory) / filename
            relative = path.relative_to(root)
            if any(fnmatchcase(relative.name, pattern) for pattern in _IGNORED_BASENAMES):
                continue
            if _is_gitignored(relative, patterns):
                continue
            files[str(relative)] = path.read_bytes()
    return files
