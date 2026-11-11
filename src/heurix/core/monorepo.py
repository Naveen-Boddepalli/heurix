"""
Monorepo workspace topology parser and 1-2 level polyglot subtree discovery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import json
import posixpath
import re
import sys
from typing import Dict, List, Optional, Sequence, Set, Tuple

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        import tomllib  # type: ignore

from ruamel.yaml import YAML

from heurix.core.indexer import RepoIndexer

_NEVER_MATCH_RE = re.compile(r"(?!)")
_GO_INLINE_TOKEN_RE = re.compile(r'"[^"]*"|`[^`]*`|\S+')


def normalize_workspace_pattern(raw: str) -> str:
    """
    Normalize a workspace glob or relative path using POSIX separators.

    Strips leading "./" safely without corrupting dot-directories (e.g. ".config/*")
    and rejects path traversal ("..") or leading "/" absolute paths by returning "".
    """
    if not isinstance(raw, str):
        return ""

    text = raw.strip().replace("\\", "/")
    if not text:
        return ""

    negated = False
    if text.startswith("!"):
        negated = True
        text = text[1:].strip()

    if not text or text.startswith("/"):
        return ""

    while text.startswith("./"):
        text = text[2:]

    text = text.rstrip("/")
    if not text:
        return "" if negated else "."

    raw_parts = [part for part in text.split("/") if part and part != "."]
    if not raw_parts:
        return "" if negated else "."

    if any(part == ".." for part in raw_parts):
        return ""

    norm = posixpath.normpath("/".join(raw_parts))
    if norm == ".." or norm.startswith("../") or norm.startswith("/"):
        return ""

    return f"!{norm}" if negated else norm


def _compile_glob_segment(segment: str) -> str:
    """Compile a single non-'**' glob segment into a non-backtracking regex fragment."""
    if segment == "*":
        return r"(?!\.)[^/]+"

    parts: List[str] = []
    if segment.startswith("*") or segment.startswith("?"):
        parts.append(r"(?!\.)")

    prev_star = False
    for ch in segment:
        if ch == "*":
            if not prev_star:
                parts.append(r"[^/]*")
            prev_star = True
        elif ch == "?":
            parts.append(r"[^/]")
            prev_star = False
        else:
            parts.append(re.escape(ch))
            prev_star = False

    return "".join(parts)


@lru_cache(maxsize=512)
def compile_workspace_glob(pattern: str) -> re.Pattern[str]:
    """
    Compile a normalized workspace glob pattern segment-by-segment.

    - '*' matches within a single path segment only (never crosses '/').
    - Segments starting with '*' or '?' do not match dotfiles/dotdirs.
    - '?' matches a single non-'/' character.
    - '**' matches zero or more nested path segments.
    """
    norm = normalize_workspace_pattern(pattern)
    if not norm:
        return _NEVER_MATCH_RE
    if norm.startswith("!"):
        norm = norm[1:]
        if not norm:
            return _NEVER_MATCH_RE

    if norm == ".":
        return re.compile(r"^\.$")

    # Collapse consecutive '**' segments to prevent redundant backtracking
    segments: List[str] = []
    for seg in norm.split("/"):
        if seg == "**" and segments and segments[-1] == "**":
            continue
        segments.append(seg)

    if segments == ["**"]:
        return re.compile(r"^.+$")

    regex_parts: List[str] = ["^"]
    last_idx = len(segments) - 1
    for idx, seg in enumerate(segments):
        if seg == "**":
            if idx == 0:
                regex_parts.append(r"(?:.+/)?")
            elif idx == last_idx:
                regex_parts.append(r"(?:/.*)?")
            else:
                regex_parts.append(r"/(?:.+/)?")
        else:
            if idx > 0 and segments[idx - 1] != "**":
                regex_parts.append("/")
            regex_parts.append(_compile_glob_segment(seg))

    regex_parts.append("$")
    return re.compile("".join(regex_parts))


def _is_excluded(candidate_dir: str, exclude_patterns: Sequence[str]) -> bool:
    for raw_exc in exclude_patterns:
        norm_exc = normalize_workspace_pattern(raw_exc)
        if not norm_exc:
            continue
        if norm_exc.startswith("!"):
            norm_exc = norm_exc[1:]
        if not norm_exc:
            continue
        if compile_workspace_glob(norm_exc).fullmatch(candidate_dir):
            return True
        if "*" not in norm_exc and "?" not in norm_exc and candidate_dir.startswith(f"{norm_exc}/"):
            return True
    return False


def match_workspace_globs(
    candidate_dir: str,
    patterns: Sequence[str],
    exclude_patterns: Sequence[str] = (),
) -> bool:
    """
    Evaluate ordered positive/! negative workspace globs and explicit excludes
    against a candidate relative directory path.
    """
    cand = normalize_workspace_pattern(candidate_dir)
    if not cand or cand.startswith("!"):
        return False

    matched = False
    for raw_pat in patterns:
        norm_pat = normalize_workspace_pattern(raw_pat)
        if not norm_pat:
            continue
        if norm_pat.startswith("!"):
            body = norm_pat[1:]
            if body and compile_workspace_glob(body).fullmatch(cand):
                matched = False
        else:
            if compile_workspace_glob(norm_pat).fullmatch(cand):
                matched = True

    if not matched:
        return False

    return not _is_excluded(cand, exclude_patterns)


def _normalize_pattern_sequence(items: Sequence[object]) -> List[str]:
    result: List[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        norm = normalize_workspace_pattern(item)
        if norm:
            result.append(norm)
    return result


def parse_pnpm_workspace(content: str) -> List[str]:
    """Parse `packages:` globs from pnpm-workspace.yaml using safe YAML loading."""
    if not content or not content.strip():
        return []
    try:
        yaml = YAML(typ="safe")
        data = yaml.load(content)
    except Exception:
        return []

    if not isinstance(data, dict):
        return []
    packages = data.get("packages")
    if not isinstance(packages, list):
        return []
    return _normalize_pattern_sequence(packages)


def parse_package_json_workspaces(content: str) -> List[str]:
    """
    Parse `workspaces` from package.json supporting both npm/Yarn list format
    and Yarn Classic `{"packages": [...]}` object format.
    """
    if not content or not content.strip():
        return []
    try:
        data = json.loads(content)
    except Exception:
        return []

    if not isinstance(data, dict):
        return []

    workspaces = data.get("workspaces")
    if isinstance(workspaces, list):
        return _normalize_pattern_sequence(workspaces)
    if isinstance(workspaces, dict):
        packages = workspaces.get("packages")
        if isinstance(packages, list):
            return _normalize_pattern_sequence(packages)
    return []


def parse_cargo_workspace(content: str) -> Tuple[List[str], List[str], bool]:
    """
    Parse Cargo.toml `[workspace]` table.

    Returns `(members, exclude, has_package)` where `has_package` indicates
    whether `[package]` is also declared (non-virtual workspace root).
    """
    if not content or not content.strip():
        return ([], [], False)
    try:
        data = tomllib.loads(content)
    except Exception:
        return ([], [], False)

    if not isinstance(data, dict):
        return ([], [], False)

    has_package = isinstance(data.get("package"), dict)
    workspace = data.get("workspace")
    if not isinstance(workspace, dict):
        return ([], [], has_package)

    raw_members = workspace.get("members")
    raw_exclude = workspace.get("exclude")

    members = _normalize_pattern_sequence(raw_members) if isinstance(raw_members, list) else []
    exclude = _normalize_pattern_sequence(raw_exclude) if isinstance(raw_exclude, list) else []
    return (members, exclude, has_package)


def _strip_go_line_comment(line: str) -> str:
    """Strip `//` comments outside double-quoted or backtick-quoted strings."""
    in_double = False
    in_backtick = False
    escaped = False
    for idx, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if in_double:
            if ch == "\\":
                escaped = True
            elif ch == '"':
                in_double = False
            continue
        if in_backtick:
            if ch == "`":
                in_backtick = False
            continue
        if ch == '"':
            in_double = True
        elif ch == "`":
            in_backtick = True
        elif ch == "/" and idx + 1 < len(line) and line[idx + 1] == "/":
            return line[:idx]
    return line


def _unquote_go_token(token: str) -> str:
    stripped = token.strip()
    if len(stripped) >= 2 and (
        (stripped[0] == '"' and stripped[-1] == '"')
        or (stripped[0] == "`" and stripped[-1] == "`")
    ):
        return stripped[1:-1]
    return stripped


def parse_go_work(content: str) -> List[str]:
    """
    Parse `use` directives (single-line, inline, and multi-line blocks) from go.work,
    stripping `//` comments and quotes, normalizing POSIX paths, and rejecting `..`
    or absolute path traversal.
    """
    if not content or not content.strip():
        return []

    raw_paths: List[str] = []
    in_use_block = False

    for raw_line in content.splitlines():
        line = _strip_go_line_comment(raw_line).strip()
        if not line:
            continue

        if in_use_block:
            if line.startswith(")"):
                in_use_block = False
                continue
            if ")" in line:
                before_close = line.split(")", 1)[0].strip()
                for tok in _GO_INLINE_TOKEN_RE.findall(before_close):
                    unquoted = _unquote_go_token(tok)
                    if unquoted:
                        raw_paths.append(unquoted)
                in_use_block = False
                continue
            unquoted = _unquote_go_token(line)
            if unquoted:
                raw_paths.append(unquoted)
            continue

        inline_match = re.match(r"^use\s*\(([^)]*)\)\s*$", line)
        if inline_match:
            for tok in _GO_INLINE_TOKEN_RE.findall(inline_match.group(1)):
                unquoted = _unquote_go_token(tok)
                if unquoted:
                    raw_paths.append(unquoted)
            continue

        block_open = re.match(r"^use\s*\((.*)$", line)
        if block_open:
            in_use_block = True
            remainder = block_open.group(1).strip()
            if remainder:
                for tok in _GO_INLINE_TOKEN_RE.findall(remainder):
                    unquoted = _unquote_go_token(tok)
                    if unquoted:
                        raw_paths.append(unquoted)
            continue

        single_match = re.match(r"^use\s+(.+)$", line)
        if single_match:
            unquoted = _unquote_go_token(single_match.group(1))
            if unquoted:
                raw_paths.append(unquoted)

    result: List[str] = []
    for raw_path in raw_paths:
        norm = normalize_workspace_pattern(raw_path)
        if not norm or norm.startswith("!"):
            continue
        if norm not in result:
            result.append(norm)
    return result


NON_PACKAGE_DIRS = frozenset({
    "docs",
    "doc",
    "examples",
    "example",
    "fixtures",
    "fixture",
    "tests",
    "test",
    "__tests__",
    "scripts",
    "requirements",
    ".github",
    "k8s",
    "packaging",
    "site",
})

PREFERRED_CONTAINER_GROUPS = frozenset({
    "apps",
    "services",
    "packages",
    "crates",
    "libs",
    "modules",
})

ECOSYSTEM_MANIFESTS: Dict[str, frozenset[str]] = {
    "node": frozenset({"package.json"}),
    "python": frozenset({
        "pyproject.toml",
        "uv.lock",
        "poetry.lock",
        "Pipfile",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
    }),
    "rust": frozenset({"Cargo.toml"}),
    "go": frozenset({"go.mod"}),
    "cpp": frozenset({"CMakeLists.txt", "conanfile.txt", "conanfile.py", "vcpkg.json"}),
}

_MANIFEST_TO_LANG: Dict[str, str] = {
    manifest: lang
    for lang, manifests in ECOSYSTEM_MANIFESTS.items()
    for manifest in manifests
}

_PYTHON_PREFERRED_GROUPS = frozenset({"apps", "services", "packages"})


@dataclass
class MonorepoTopology:
    is_monorepo: bool
    has_workspace_config: bool
    workspace_kinds: List[str] = field(default_factory=list)
    packages_by_lang: Dict[str, List[str]] = field(default_factory=dict)
    all_packages: List[Tuple[str, str]] = field(default_factory=list)


def discover_monorepo_topology(indexer: RepoIndexer) -> MonorepoTopology:
    """
    Resolve monorepo workspace topology strictly over RepoIndexer indexed paths
    and read_text(), combining explicit workspace configs with 1-2 level polyglot
    heuristic discovery and false-positive directory filtering.
    """
    has_workspace_config = False
    workspace_kinds: List[str] = []
    discovered: Set[Tuple[str, str]] = set()
    explicit_langs: Set[str] = set()

    # 1. Explicit Node workspace configs
    pnpm_patterns: List[str] = []
    if indexer.has_file("pnpm-workspace.yaml"):
        has_workspace_config = True
        workspace_kinds.append("pnpm")
        pnpm_patterns = parse_pnpm_workspace(indexer.read_text("pnpm-workspace.yaml") or "")

    pkg_json_patterns: List[str] = []
    if indexer.has_file("package.json"):
        pkg_raw = indexer.read_text("package.json") or ""
        try:
            pkg_json_data = json.loads(pkg_raw)
        except Exception:
            pkg_json_data = {}
        if isinstance(pkg_json_data, dict) and isinstance(
            pkg_json_data.get("workspaces"), (list, dict)
        ):
            has_workspace_config = True
            workspace_kinds.append("npm")
            pkg_json_patterns = parse_package_json_workspaces(pkg_raw)

    if indexer.has_file("turbo.json"):
        has_workspace_config = True
        workspace_kinds.append("turbo")

    if indexer.has_file("nx.json"):
        has_workspace_config = True
        workspace_kinds.append("nx")

    node_patterns = pnpm_patterns if pnpm_patterns else pkg_json_patterns
    if node_patterns:
        explicit_langs.add("node")
        for pkg_path in indexer.find_by_name("package.json"):
            if pkg_path == "package.json":
                continue
            cand_dir = pkg_path.rsplit("/", 1)[0]
            if match_workspace_globs(cand_dir, node_patterns):
                discovered.add((cand_dir, "node"))

    # 2. Explicit Rust Cargo [workspace]
    cargo_members: List[str] = []
    cargo_excludes: List[str] = []
    if indexer.has_file("Cargo.toml"):
        cargo_raw = indexer.read_text("Cargo.toml") or ""
        try:
            cargo_data = tomllib.loads(cargo_raw)
        except Exception:
            cargo_data = {}
        if isinstance(cargo_data, dict) and isinstance(cargo_data.get("workspace"), dict):
            has_workspace_config = True
            workspace_kinds.append("cargo")
            cargo_members, cargo_excludes, _ = parse_cargo_workspace(cargo_raw)

    if cargo_members:
        explicit_langs.add("rust")
        for cargo_path in indexer.find_by_name("Cargo.toml"):
            if cargo_path == "Cargo.toml":
                continue
            cand_dir = cargo_path.rsplit("/", 1)[0]
            if match_workspace_globs(cand_dir, cargo_members, cargo_excludes):
                discovered.add((cand_dir, "rust"))

    # 3. Explicit Go workspace (go.work)
    if indexer.has_file("go.work"):
        has_workspace_config = True
        workspace_kinds.append("go.work")
        go_work_dirs = parse_go_work(indexer.read_text("go.work") or "")
        if go_work_dirs:
            explicit_langs.add("go")
            for go_dir in go_work_dirs:
                if go_dir == ".":
                    continue
                if indexer.has_file(f"{go_dir}/go.mod"):
                    discovered.add((go_dir, "go"))

    # 4. Precompute directories containing at least one .py file for requirements.txt guard
    dirs_with_py: Set[str] = set()
    for rel_path in indexer.files:
        if rel_path.endswith(".py") and "/" in rel_path:
            parts = rel_path.split("/")
            if len(parts) == 2 or parts[0].lower() not in PREFERRED_CONTAINER_GROUPS:
                dirs_with_py.add(parts[0])
            if len(parts) >= 3:
                dirs_with_py.add(f"{parts[0]}/{parts[1]}")

    # 5. Heuristic 1-2 level polyglot subtree discovery
    candidates: Dict[Tuple[str, str], Set[str]] = {}
    for rel_path in indexer.files:
        parts = rel_path.split("/")
        if len(parts) not in (2, 3):
            continue
        dir_parts = parts[:-1]
        filename = parts[-1]
        lang = _MANIFEST_TO_LANG.get(filename)
        if lang is None or lang in explicit_langs:
            continue
        if any(part.startswith(".") or part.lower() in NON_PACKAGE_DIRS for part in dir_parts):
            continue
        pkg_dir = "/".join(dir_parts)
        candidates.setdefault((pkg_dir, lang), set()).add(filename)

    has_root_cmake = indexer.has_file("CMakeLists.txt")
    for (pkg_dir, lang), manifests in candidates.items():
        dir_parts = pkg_dir.split("/")
        top_group = dir_parts[0].lower()

        if lang == "rust" and cargo_excludes and _is_excluded(pkg_dir, cargo_excludes):
            continue

        if lang == "python" and manifests == {"requirements.txt"}:
            in_preferred_group = len(dir_parts) == 2 and top_group in _PYTHON_PREFERRED_GROUPS
            if not in_preferred_group and pkg_dir not in dirs_with_py:
                continue

        if lang == "cpp" and manifests == {"CMakeLists.txt"}:
            has_parent_cmake = has_root_cmake or (
                len(dir_parts) == 2 and indexer.has_file(f"{dir_parts[0]}/CMakeLists.txt")
            )
            if has_parent_cmake and top_group not in PREFERRED_CONTAINER_GROUPS:
                continue

        discovered.add((pkg_dir, lang))

    all_packages = sorted(discovered)
    raw_by_lang: Dict[str, List[str]] = {}
    for pkg_dir, lang in all_packages:
        raw_by_lang.setdefault(lang, []).append(pkg_dir)
    packages_by_lang = {lang: paths for lang, paths in sorted(raw_by_lang.items())}

    has_root_manifest = any(
        indexer.has_file(manifest)
        for manifests in ECOSYSTEM_MANIFESTS.values()
        for manifest in manifests
    )
    is_monorepo = (
        has_workspace_config
        or len(all_packages) >= 2
        or (len(all_packages) == 1 and has_root_manifest)
    )

    return MonorepoTopology(
        is_monorepo=is_monorepo,
        has_workspace_config=has_workspace_config,
        workspace_kinds=workspace_kinds,
        packages_by_lang=packages_by_lang,
        all_packages=all_packages,
    )

