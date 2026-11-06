"""
Fast, .gitignore-aware repository indexer and file contents cache.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Set
import pathspec

# Standard directories and patterns to ignore across all repos
DEFAULT_IGNORES = [
    ".git",
    ".git/**",
    "node_modules",
    "node_modules/**",
    ".venv",
    ".venv/**",
    "venv",
    "venv/**",
    "env",
    "env/**",
    "target",
    "target/**",
    "dist",
    "dist/**",
    "build",
    "build/**",
    "__pycache__",
    "__pycache__/**",
    ".pytest_cache",
    ".pytest_cache/**",
    ".next",
    ".next/**",
    ".turbo",
    ".turbo/**",
    ".idea",
    ".idea/**",
    ".vscode",
    ".vscode/**",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.egg-info",
    "*.egg-info/**",
    ".DS_Store",
]


class RepoIndexer:
    """
    Indexed repository file tree with in-memory caching and .gitignore respect.
    """

    def __init__(self, root_dir: str | Path):
        self.root = Path(root_dir).resolve()
        self._files: List[str] = []
        self._content_cache: Dict[str, str] = {}
        self._spec: pathspec.PathSpec = self._build_pathspec()
        self._index_files()

    def _build_pathspec(self) -> pathspec.PathSpec:
        patterns = list(DEFAULT_IGNORES)
        gitignore_path = self.root / ".gitignore"
        if gitignore_path.is_file():
            try:
                with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as f:
                    patterns.extend(f.readlines())
            except OSError:
                pass
        return pathspec.PathSpec.from_lines("gitignore", patterns)

    def _index_files(self) -> None:
        self._files = []
        root_str = str(self.root)
        for dirpath, dirnames, filenames in os.walk(root_str):
            rel_dir = os.path.relpath(dirpath, root_str)
            if rel_dir == ".":
                rel_dir_clean = ""
            else:
                rel_dir_clean = rel_dir.replace("\\", "/") + "/"

            # Filter dirnames in-place to avoid descending into ignored dirs
            filtered_dirs = []
            for d in dirnames:
                candidate = (rel_dir_clean + d + "/") if rel_dir_clean else (d + "/")
                if not self._spec.match_file(candidate) and not self._spec.match_file(d):
                    filtered_dirs.append(d)
            dirnames[:] = filtered_dirs

            for f in filenames:
                rel_path = (rel_dir_clean + f) if rel_dir_clean else f
                if not self._spec.match_file(rel_path):
                    self._files.append(rel_path)

    @property
    def files(self) -> List[str]:
        return self._files

    def has_file(self, rel_path: str) -> bool:
        normalized = rel_path.replace("\\", "/").lstrip("/")
        return normalized in self._files

    def read_text(self, rel_path: str) -> Optional[str]:
        normalized = rel_path.replace("\\", "/").lstrip("/")
        if normalized not in self._files:
            return None

        if normalized in self._content_cache:
            return self._content_cache[normalized]

        file_path = self.root / normalized
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            self._content_cache[normalized] = content
            return content
        except OSError:
            return None

    def find_files(self, glob_pattern: str) -> List[str]:
        import fnmatch
        return [f for f in self._files if fnmatch.fnmatch(f, glob_pattern) or fnmatch.fnmatch(os.path.basename(f), glob_pattern)]

    def find_by_name(self, filename: str) -> List[str]:
        return [f for f in self._files if os.path.basename(f) == filename]
