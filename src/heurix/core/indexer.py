"""
Fast, .gitignore-aware repository indexer and file contents cache.
"""

from __future__ import annotations

import os
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import pathspec

MAX_FILE_SIZE_BYTES = 1_048_576
MAX_CACHE_ENTRIES = 512
MAX_CACHE_BYTES = 32 * 1024 * 1024

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

ALWAYS_IGNORE_DIRS: frozenset[str] = frozenset({".git"})

DEFAULT_IGNORE_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "env",
        "target",
        "dist",
        "build",
        "__pycache__",
        ".pytest_cache",
        ".next",
        ".turbo",
        ".idea",
        ".vscode",
    }
)

DEFAULT_IGNORE_SUFFIXES: Tuple[str, ...] = (".pyc", ".pyo", ".pyd")
DEFAULT_IGNORE_FILES: frozenset[str] = frozenset({".DS_Store"})

# Standard directories and patterns to ignore across all repos (retained for compatibility)
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


def _compile_gitignore(
    gitignore_path: str | Path,
) -> Optional[Tuple[pathspec.GitIgnoreSpec, bool, Set[str]]]:
    """
    Compile a .gitignore file into a GitIgnoreSpec alongside a flag indicating
    whether explicit ! negations are present and any default-ignored directory
    names referenced by ! negation lines.
    """
    try:
        with open(gitignore_path, "r", encoding="utf-8-sig", errors="ignore") as f:
            lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    except OSError:
        return None

    if not lines:
        return None

    spec = pathspec.GitIgnoreSpec.from_lines(lines)
    if not any(getattr(p, "include", None) is not None for p in spec.patterns):
        return None

    has_neg = any(getattr(p, "include", None) is False for p in spec.patterns)
    negated_dirs: Set[str] = set()
    if has_neg:
        for pattern in spec.patterns:
            if getattr(pattern, "include", None) is False:
                raw_pat = getattr(pattern, "pattern", "")
                if isinstance(raw_pat, str):
                    pat = raw_pat.rstrip("\r\n").strip()
                    if pat.startswith("!"):
                        pat = pat[1:]
                    for seg in pat.strip("/").split("/"):
                        if seg in DEFAULT_IGNORE_DIRS:
                            negated_dirs.add(seg)

    return (spec, has_neg, negated_dirs)


def _eval_gitignore_layers(
    rel_path: str,
    rev_layers: List[Tuple[int, pathspec.GitIgnoreSpec, bool]],
) -> Optional[bool]:
    """
    Evaluate compiled GitIgnoreSpec layers from deepest directory to root.
    Returns True if explicitly ignored, False if explicitly re-included via !,
    or None if no pattern in any layer matched.
    """
    for plen, spec, has_neg in rev_layers:
        sub = rel_path[plen:] if plen else rel_path
        if has_neg:
            res = spec.check_file(sub, separators=())
            if res.include is not None:
                return bool(res.include)
        elif spec.match_file(sub, separators=()):
            return True
    return None


def _is_ignored(
    rel_path: str,
    rev_layers: List[Tuple[int, pathspec.GitIgnoreSpec, bool]],
) -> bool:
    """Return True if rel_path is ignored by the deepest-to-root .gitignore stack."""
    return _eval_gitignore_layers(rel_path, rev_layers) is True


def _normalize_rel_path(rel_path: str) -> str:
    normalized = rel_path.replace("\\", "/").lstrip("/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


class RepoIndexer:
    """
    Indexed repository file tree with in-memory caching and .gitignore respect.
    """

    def __init__(
        self,
        root_dir: str | Path,
        *,
        max_file_size_bytes: int = MAX_FILE_SIZE_BYTES,
        max_cache_entries: int = MAX_CACHE_ENTRIES,
        max_cache_bytes: int = MAX_CACHE_BYTES,
    ):
        self.root = Path(root_dir).resolve()
        self.max_file_size_bytes = max_file_size_bytes
        self.max_cache_entries = max_cache_entries
        self.max_cache_bytes = max_cache_bytes
        self._files: List[str] = []
        self._file_set: Set[str] = set()
        self._content_cache: OrderedDict[str, str] = OrderedDict()
        self._cache_sizes: Dict[str, int] = {}
        self._cache_bytes: int = 0
        self._index_files()

    def _index_files(self) -> None:
        self._files = []
        root_str = str(self.root)
        root_prefix_len = len(root_str) if root_str.endswith(os.sep) else len(root_str) + 1

        # Stack entry: (layers, negated_default_dirs, in_default_dir, neg_default_files)
        dir_stacks: Dict[
            str,
            Tuple[
                List[Tuple[int, pathspec.GitIgnoreSpec, bool]],
                frozenset[str],
                bool,
                bool,
            ],
        ] = {"": ([], frozenset(), False, False)}

        for dirpath, dirnames, filenames in os.walk(root_str, followlinks=False):
            raw_rel = dirpath[root_prefix_len:]
            rel_dir_clean = (raw_rel.replace("\\", "/") + "/") if raw_rel else ""

            layers, neg_dirs, in_default_dir, neg_default_files = dir_stacks.pop(rel_dir_clean)

            if ".gitignore" in filenames:
                compiled = _compile_gitignore(os.path.join(dirpath, ".gitignore"))
                if compiled is not None:
                    spec, has_neg, layer_neg_dirs = compiled
                    layers = layers + [(len(rel_dir_clean), spec, has_neg)]
                    if layer_neg_dirs:
                        neg_dirs = neg_dirs | layer_neg_dirs
                    if has_neg and not neg_default_files:
                        for pat in spec.patterns:
                            if getattr(pat, "include", None) is False:
                                pat_str = getattr(pat, "pattern", "")
                                if isinstance(pat_str, str) and any(
                                    tok in pat_str
                                    for tok in (".DS_Store", ".pyc", ".pyo", ".pyd", "egg-info")
                                ):
                                    neg_default_files = True
                                    break

            rev_layers = layers[::-1]

            if dirnames:
                kept_dirs: List[str] = []
                for d in dirnames:
                    if d in ALWAYS_IGNORE_DIRS:
                        continue
                    is_default_dir = d in DEFAULT_IGNORE_DIRS or d.endswith(".egg-info")
                    if (
                        is_default_dir
                        and d not in neg_dirs
                        and not (d.endswith(".egg-info") and neg_default_files)
                    ):
                        continue

                    candidate = (rel_dir_clean + d + "/") if rel_dir_clean else (d + "/")
                    decision = _eval_gitignore_layers(candidate, rev_layers) if rev_layers else None
                    if decision is True:
                        continue

                    if decision is False:
                        child_in_default = False
                    else:
                        child_in_default = in_default_dir or is_default_dir

                    kept_dirs.append(d)
                    dir_stacks[candidate] = (layers, neg_dirs, child_in_default, neg_default_files)
                dirnames[:] = kept_dirs

            for f in filenames:
                if f in ALWAYS_IGNORE_DIRS:
                    continue
                is_default_file = (
                    f in DEFAULT_IGNORE_FILES
                    or f.endswith(DEFAULT_IGNORE_SUFFIXES)
                    or f.endswith(".egg-info")
                )
                if is_default_file and not neg_default_files:
                    continue

                rel_path = (rel_dir_clean + f) if rel_dir_clean else f
                decision = _eval_gitignore_layers(rel_path, rev_layers) if rev_layers else None
                if decision is True:
                    continue
                if decision is None and (in_default_dir or is_default_file):
                    continue
                self._files.append(rel_path)

        self._files.sort()
        self._file_set = set(self._files)

    @property
    def files(self) -> List[str]:
        return self._files

    def has_file(self, rel_path: str) -> bool:
        return _normalize_rel_path(rel_path) in self._file_set

    def read_text(self, rel_path: str) -> Optional[str]:
        normalized = _normalize_rel_path(rel_path)
        if normalized not in self._file_set:
            return None

        if normalized in self._content_cache:
            self._content_cache.move_to_end(normalized)
            return self._content_cache[normalized]

        file_path = self.root / normalized
        try:
            file_size = file_path.stat().st_size
            if file_size > self.max_file_size_bytes:
                return None
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        entry_bytes = len(content.encode("utf-8", errors="replace"))
        if entry_bytes <= self.max_cache_bytes and self.max_cache_entries > 0:
            while self._content_cache and (
                len(self._content_cache) >= self.max_cache_entries
                or self._cache_bytes + entry_bytes > self.max_cache_bytes
            ):
                evicted_key, _ = self._content_cache.popitem(last=False)
                self._cache_bytes -= self._cache_sizes.pop(evicted_key, 0)
            self._content_cache[normalized] = content
            self._cache_sizes[normalized] = entry_bytes
            self._cache_bytes += entry_bytes

        return content

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
