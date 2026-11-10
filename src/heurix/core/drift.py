"""
Drift Detection Engine for Heurix (`hx check`).
Compares codebase fingerprint against existing YAML infrastructure configurations
using structural ruamel.yaml AST traversal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
import re
from typing import Any, Dict, List, NamedTuple, Set, Tuple
from ruamel.yaml import YAML
from heurix.core.context import ProjectContext


_MATRIX_REF_RE = re.compile(r"\bmatrix\.([A-Za-z0-9_-]+)\b")
_ENV_REF_RE = re.compile(r"\benv\.([A-Za-z0-9_-]+)\b")
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

_SHELL_WRAPPERS = frozenset({"sudo", "env", "time", "command", "nohup", "corepack", "npx", "bunx"})
_SHELL_KEYWORDS = frozenset({"then", "do", "else", "elif", "!"})
_KNOWN_PM_COMMANDS = frozenset({"uv", "pnpm", "poetry", "bun", "yarn", "npm", "pip"})

# action_name -> (language, version_with_keys, requires_pinned_version)
SETUP_ACTION_SPECS: Dict[str, Tuple[str, Tuple[str, ...], bool]] = {
    "actions/setup-python": ("python", ("python-version",), True),
    "astral-sh/setup-uv": ("python", ("python-version",), False),
    "actions/setup-node": ("node", ("node-version",), True),
    "actions/setup-go": ("go", ("go-version",), True),
    "dtolnay/rust-toolchain": ("rust", ("toolchain",), False),
    "actions-rs/toolchain": ("rust", ("toolchain",), False),
}

PACKAGE_MANAGER_ACTIONS: Dict[str, str] = {
    "astral-sh/setup-uv": "uv",
    "pnpm/action-setup": "pnpm",
    "snok/install-poetry": "poetry",
    "oven-sh/setup-bun": "bun",
}

PACKAGE_MANAGER_CHECKS: Dict[str, Tuple[str, str, str]] = {
    "uv": (
        "astral-sh/setup-uv",
        "uv package manager detected in codebase (uv.lock), but workflow does not use astral-sh/setup-uv.",
        "Run 'hx generate' to optimize workflow for uv.",
    ),
    "pnpm": (
        "pnpm/action-setup",
        "pnpm package manager detected in codebase, but workflow does not use pnpm.",
        "Run 'hx generate' to update workflow to pnpm.",
    ),
    "poetry": (
        "snok/install-poetry",
        "poetry package manager detected in codebase (poetry.lock), but workflow does not use snok/install-poetry or poetry.",
        "Run 'hx generate' to update workflow for poetry.",
    ),
    "bun": (
        "oven-sh/setup-bun",
        "bun package manager detected in codebase, but workflow does not use oven-sh/setup-bun or bun.",
        "Run 'hx generate' to update workflow for bun.",
    ),
}


class DriftFinding(NamedTuple):
    file_path: str
    issue: str
    severity: str  # "WARNING", "ERROR", "INFO"
    recommendation: str


class WorkflowASTInfo(NamedTuple):
    discovered_services: Set[str]
    runtime_versions: Dict[str, Set[str]]
    setup_actions: Set[str]
    package_managers: Set[str]
    run_commands: List[str]
    unpinned_jobs: Dict[str, Set[str]]


def _normalize_version(val: Any) -> str:
    """Normalize a YAML AST version scalar into a stripped string without float coercion."""
    if val is None or isinstance(val, bool):
        return ""
    s = str(val).strip()
    while len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1].strip()
    return s.strip("'\" \t\r\n")


def _collect_version_values(node: Any) -> Set[str]:
    """Extract normalized version strings from a scalar, newline-separated string, or sequence."""
    results: Set[str] = set()
    if node is None or isinstance(node, bool):
        return results
    if isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
        for item in node:
            norm = _normalize_version(item)
            if norm:
                results.add(norm)
        return results
    if isinstance(node, str) and "\n" in node:
        for line in node.splitlines():
            norm = _normalize_version(line)
            if norm:
                results.add(norm)
        return results
    norm = _normalize_version(node)
    if norm:
        results.add(norm)
    return results


def _resolve_version_expr(
    raw_val: Any,
    matrix: Mapping[str, Any],
    env_map: Mapping[str, Any],
) -> Set[str]:
    """Resolve direct values or GitHub Actions matrix/env expressions from AST nodes."""
    if raw_val is None or isinstance(raw_val, bool):
        return set()

    if isinstance(raw_val, str) and "${{" in raw_val:
        resolved: Set[str] = set()

        for matrix_key in _MATRIX_REF_RE.findall(raw_val):
            if matrix_key in matrix:
                resolved.update(_collect_version_values(matrix[matrix_key]))
            include_entries = matrix.get("include")
            if isinstance(include_entries, Sequence) and not isinstance(include_entries, (str, bytes)):
                for inc in include_entries:
                    if isinstance(inc, Mapping) and matrix_key in inc:
                        resolved.update(_collect_version_values(inc[matrix_key]))
            exclude_entries = matrix.get("exclude")
            if isinstance(exclude_entries, Sequence) and not isinstance(exclude_entries, (str, bytes)):
                for exc in exclude_entries:
                    if isinstance(exc, Mapping) and len(exc) == 1 and matrix_key in exc:
                        resolved.difference_update(_collect_version_values(exc[matrix_key]))

        for env_key in _ENV_REF_RE.findall(raw_val):
            if env_key in env_map:
                resolved.update(_collect_version_values(env_map[env_key]))

        return resolved

    return _collect_version_values(raw_val)


def _split_shell_segments(line: str) -> List[str]:
    """Split a single shell line on unquoted separators while stripping unquoted comments."""
    segments: List[str] = []
    buf: List[str] = []
    quote: str | None = None
    escaped = False
    i = 0
    n = len(line)

    while i < n:
        ch = line[i]
        if escaped:
            buf.append(ch)
            escaped = False
            i += 1
            continue

        if ch == "\\" and quote != "'":
            buf.append(ch)
            escaped = True
            i += 1
            continue

        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue

        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue

        if ch == "#" and (not buf or buf[-1].isspace()):
            break

        if ch in (";", "|") or (ch == "&" and i + 1 < n and line[i + 1] == "&"):
            seg = "".join(buf).strip()
            if seg:
                segments.append(seg)
            buf = []
            if (ch == "&" and i + 1 < n and line[i + 1] == "&") or (
                ch == "|" and i + 1 < n and line[i + 1] == "|"
            ):
                i += 2
            else:
                i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        segments.append(tail)
    return segments


def _extract_command_prefixes(run_cmd: str) -> Set[str]:
    """Extract executable command prefixes from a workflow step `run` script."""
    prefixes: Set[str] = set()
    for raw_line in run_cmd.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for seg in _split_shell_segments(stripped):
            tokens = seg.split()
            idx = 0
            while idx < len(tokens):
                tok = tokens[idx]
                if tok in _SHELL_KEYWORDS or _ENV_ASSIGN_RE.match(tok):
                    idx += 1
                    continue
                cmd_name = tok.rsplit("/", 1)[-1].lower()
                if cmd_name in _SHELL_WRAPPERS and idx + 1 < len(tokens):
                    idx += 1
                    continue
                if cmd_name:
                    prefixes.add(cmd_name)
                    if (
                        cmd_name.startswith("python")
                        and idx + 2 < len(tokens)
                        and tokens[idx + 1] == "-m"
                    ):
                        prefixes.add(tokens[idx + 2].lower())
                break
    return prefixes


def inspect_workflow_ast(doc: Any) -> WorkflowASTInfo:
    """
    Traverse a parsed GitHub Actions workflow YAML AST without string serialization.

    Collects backing services declared under `jobs.*.services`, setup actions,
    runtime versions (including `strategy.matrix` and `env` references),
    package managers, step run commands, and unpinned setup jobs across all jobs.
    """
    discovered_services: Set[str] = set()
    runtime_versions: Dict[str, Set[str]] = {
        "python": set(),
        "node": set(),
        "go": set(),
        "rust": set(),
    }
    setup_actions: Set[str] = set()
    package_managers: Set[str] = set()
    run_commands: List[str] = []
    unpinned_jobs: Dict[str, Set[str]] = {}

    if not isinstance(doc, Mapping):
        return WorkflowASTInfo(
            discovered_services=discovered_services,
            runtime_versions=runtime_versions,
            setup_actions=setup_actions,
            package_managers=package_managers,
            run_commands=run_commands,
            unpinned_jobs=unpinned_jobs,
        )

    workflow_env = doc.get("env") if isinstance(doc.get("env"), Mapping) else {}
    jobs = doc.get("jobs")
    if not isinstance(jobs, Mapping):
        return WorkflowASTInfo(
            discovered_services=discovered_services,
            runtime_versions=runtime_versions,
            setup_actions=setup_actions,
            package_managers=package_managers,
            run_commands=run_commands,
            unpinned_jobs=unpinned_jobs,
        )

    for job_id, job in jobs.items():
        if not isinstance(job, Mapping):
            continue
        job_name = str(job_id)

        # 1. Backing services declared across any workflow job
        svcs = job.get("services")
        if isinstance(svcs, Mapping):
            for svc_name in svcs.keys():
                if svc_name is not None:
                    discovered_services.add(str(svc_name).strip().lower())

        # 2. Job-scoped strategy.matrix and env mappings
        strat = job.get("strategy")
        matrix: Mapping[str, Any] = {}
        if isinstance(strat, Mapping) and isinstance(strat.get("matrix"), Mapping):
            matrix = strat["matrix"]

        job_env: Dict[str, Any] = dict(workflow_env)
        if isinstance(job.get("env"), Mapping):
            job_env.update(job["env"])

        # 3. Steps inspection
        steps = job.get("steps")
        if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
            continue

        for step in steps:
            if not isinstance(step, Mapping):
                continue

            uses_raw = step.get("uses")
            uses = str(uses_raw).strip() if isinstance(uses_raw, str) else ""
            action = uses.split("@", 1)[0].strip().lower() if uses else ""
            action_ref = uses.split("@", 1)[1].strip() if "@" in uses else ""
            if action:
                setup_actions.add(action)

            with_cfg = step.get("with")
            if not isinstance(with_cfg, Mapping):
                with_cfg = {}

            step_env = dict(job_env)
            if isinstance(step.get("env"), Mapping):
                step_env.update(step["env"])

            # Package manager actions & cache hints
            if action in PACKAGE_MANAGER_ACTIONS:
                package_managers.add(PACKAGE_MANAGER_ACTIONS[action])
            if action == "actions/setup-python":
                cache_val = str(with_cfg.get("cache") or "").strip().lower()
                if cache_val == "poetry":
                    package_managers.add("poetry")

            # Run commands & CLI command prefixes
            run_raw = step.get("run")
            if isinstance(run_raw, str) and run_raw.strip():
                run_commands.append(run_raw)
                for prefix in _extract_command_prefixes(run_raw):
                    if prefix in _KNOWN_PM_COMMANDS:
                        package_managers.add(prefix)

            # Runtime versions from setup actions
            if action in SETUP_ACTION_SPECS:
                lang, version_keys, requires_pinned = SETUP_ACTION_SPECS[action]
                extracted: Set[str] = set()
                has_version_file = False

                for vkey in version_keys:
                    if vkey in with_cfg:
                        extracted.update(_resolve_version_expr(with_cfg.get(vkey), matrix, step_env))
                    if f"{vkey}-file" in with_cfg and with_cfg.get(f"{vkey}-file"):
                        has_version_file = True

                if not extracted and action == "dtolnay/rust-toolchain" and action_ref:
                    ref_lower = action_ref.lower()
                    if ref_lower in {"stable", "beta", "nightly"} or ref_lower[0].isdigit():
                        extracted.add(action_ref)

                if extracted:
                    runtime_versions[lang].update(extracted)
                elif requires_pinned and not has_version_file:
                    unpinned_jobs.setdefault(lang, set()).add(job_name)

    return WorkflowASTInfo(
        discovered_services=discovered_services,
        runtime_versions=runtime_versions,
        setup_actions=setup_actions,
        package_managers=package_managers,
        run_commands=run_commands,
        unpinned_jobs=unpinned_jobs,
    )


class DriftDetector:
    """
    Detects configuration drift between the codebase IR and existing YAML files.
    """

    def __init__(self, repo_root: str | Path):
        self.root = Path(repo_root).resolve()
        self.yaml = YAML(typ="safe")

    def check_drift(self, context: ProjectContext, synthesized_files: dict[str, str]) -> List[DriftFinding]:
        findings: List[DriftFinding] = []

        for rel_path, expected_content in synthesized_files.items():
            file_path = self.root / rel_path

            if not file_path.exists():
                findings.append(
                    DriftFinding(
                        file_path=rel_path,
                        issue="File does not exist in repository.",
                        severity="WARNING",
                        recommendation=f"Run 'hx generate' to synthesize {rel_path}.",
                    )
                )
                continue

            is_workflow = ".github/workflows" in rel_path
            try:
                existing_text = file_path.read_text(encoding="utf-8", errors="replace")
                if is_workflow:
                    existing_doc = self.yaml.load(existing_text)
                else:
                    existing_docs = list(self.yaml.load_all(existing_text))
                    existing_doc = existing_docs[0] if existing_docs else None
            except Exception as e:
                findings.append(
                    DriftFinding(
                        file_path=rel_path,
                        issue=f"Existing YAML file is malformed: {e}",
                        severity="ERROR",
                        recommendation="Fix YAML syntax or run 'hx generate --force'.",
                    )
                )
                continue

            if not is_workflow:
                continue

            if existing_doc is None:
                findings.append(
                    DriftFinding(
                        file_path=rel_path,
                        issue="Existing workflow YAML file is empty.",
                        severity="WARNING",
                        recommendation=f"Run 'hx generate' to synthesize {rel_path}.",
                    )
                )
                continue

            if not isinstance(existing_doc, Mapping):
                findings.append(
                    DriftFinding(
                        file_path=rel_path,
                        issue="Existing workflow YAML file is not a valid mapping.",
                        severity="ERROR",
                        recommendation="Fix YAML structure or run 'hx generate --force'.",
                    )
                )
                continue

            ast_info = inspect_workflow_ast(existing_doc)

            # 1. Check if detected backing services are missing across all jobs
            for svc in context.services:
                svc_name = svc.name.strip().lower()
                if svc_name not in ast_info.discovered_services:
                    findings.append(
                        DriftFinding(
                            file_path=rel_path,
                            issue=f"Service '{svc.name}' is required by codebase dependencies ({svc.source_file}) but missing from workflow.",
                            severity="WARNING",
                            recommendation=f"Run 'hx generate' to inject service '{svc.name}'.",
                        )
                    )

            # 2. Check runtime version drift via AST setup actions & matrix resolution
            for lang in context.languages:
                lang_key = lang.language.lower()
                expected_ver = _normalize_version(lang.runtime_version)
                if not expected_ver or expected_ver == "latest":
                    continue
                if lang_key not in ast_info.runtime_versions:
                    continue

                if (
                    lang_key == "node"
                    and lang.package_manager == "bun"
                    and lang.version_source == "default"
                    and "oven-sh/setup-bun" in ast_info.setup_actions
                    and not ast_info.runtime_versions["node"]
                ):
                    continue

                found_versions = ast_info.runtime_versions[lang_key]
                if expected_ver not in found_versions:
                    findings.append(
                        DriftFinding(
                            file_path=rel_path,
                            issue=f"Runtime version mismatch: codebase specifies {lang.language} {lang.runtime_version} ({lang.version_source}), not found in workflow.",
                            severity="WARNING",
                            recommendation=f"Run 'hx generate' to update {lang.language} version.",
                        )
                    )
                elif lang_key in ast_info.unpinned_jobs:
                    for job_name in sorted(ast_info.unpinned_jobs[lang_key]):
                        findings.append(
                            DriftFinding(
                                file_path=rel_path,
                                issue=f"Unpinned {lang.language} setup step in job '{job_name}': missing version pin.",
                                severity="WARNING",
                                recommendation=f"Pin {lang.language} {lang.runtime_version} across all workflow jobs.",
                            )
                        )

            # 3. Check package manager drift via setup actions or CLI command prefixes
            for lang in context.languages:
                pm = lang.package_manager.lower()
                if pm not in PACKAGE_MANAGER_CHECKS:
                    continue
                expected_action, issue_msg, rec_msg = PACKAGE_MANAGER_CHECKS[pm]
                has_pm = (
                    expected_action in ast_info.setup_actions
                    or pm in ast_info.package_managers
                    or any(pm in _extract_command_prefixes(cmd) for cmd in ast_info.run_commands)
                )
                if not has_pm:
                    findings.append(
                        DriftFinding(
                            file_path=rel_path,
                            issue=issue_msg,
                            severity="WARNING",
                            recommendation=rec_msg,
                        )
                    )

        return findings
