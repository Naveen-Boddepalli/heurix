"""
Fast, .gitignore-aware repository indexer and file contents cache.
"""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set
import pathspec

LANG_EXTENSIONS: Dict[str, Set[str]] = {
    "python": {".py", ".pyi", ".pyx"},
    "node": {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"},
    "rust": {".rs"},
    "go": {".go"},
    "cpp": {".cpp", ".cxx", ".cc", ".c", ".hpp", ".hxx", ".hh", ".h"},
}

ROOT_MANIFESTS: Dict[str, Set[str]] = {
    "python": {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "Pipfile",
        ".python-version",
        "uv.lock",
        "poetry.lock",
    },
    "node": {
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "bun.lockb",
        "bun.lock",
        "tsconfig.json",
    },
    "rust": {"Cargo.toml", "Cargo.lock", "rust-toolchain.toml"},
    "go": {"go.mod", "go.sum"},
    "cpp": {"CMakeLists.txt", "meson.build", "conanfile.txt", "conanfile.py", "vcpkg.json"},
}

MANIFEST_WEIGHT = 10

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

    def get_language_metrics(self) -> Dict[str, Dict[str, int | bool]]:
        """
        Compute source file volume and root-level manifest metrics per ecosystem.
        Counts only non-ignored files indexed by RepoIndexer.
        """
        ext_counts: Dict[str, int] = defaultdict(int)
        root_files: Set[str] = set()

        for rel_path in self._files:
            if "/" not in rel_path and "\\" not in rel_path:
                root_files.add(rel_path)
            _, ext = os.path.splitext(rel_path)
            if ext:
                ext_counts[ext.lower()] += 1

        metrics: Dict[str, Dict[str, int | bool]] = {}
        for lang, exts in LANG_EXTENSIONS.items():
            file_count = sum(ext_counts[e] for e in exts)
            has_root = any(m in root_files for m in ROOT_MANIFESTS[lang])
            # Only treat generic root Makefile as C/C++ manifest when C/C++ sources exist
            if lang == "cpp" and not has_root and "Makefile" in root_files and file_count > 0:
                has_root = True
            score = file_count + (MANIFEST_WEIGHT if has_root else 0)
            metrics[lang] = {
                "file_count": file_count,
                "has_root_manifest": has_root,
                "score": score,
            }

        return metrics

    def compute_language_scores(self) -> Dict[str, int]:
        """
        Compute weighted ecosystem scores combining source file counts and
        10-point root manifest bonuses.
        """
        metrics = self.get_language_metrics()
        return {lang: int(data["score"]) for lang, data in metrics.items()}
