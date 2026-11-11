"""
Drift Detection Engine for Heurix (`hx check`).
Compares codebase fingerprint against existing YAML infrastructure configurations
using structural ruamel.yaml AST traversal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Dict, List, NamedTuple, Optional, Set, Tuple
from ruamel.yaml import YAML
from heurix.core.context import ProjectContext
from heurix.core.policy import HeurixPolicy, StepPolicy, normalize_service_name


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


@dataclass
class WorkflowASTInfo:
    discovered_services: Set[str]
    runtime_versions: Dict[str, Set[str]]
    setup_actions: Set[str]
    package_managers: Set[str]
    run_commands: List[str]
    unpinned_jobs: Dict[str, Set[str]]
    working_dirs: Set[str] = field(default_factory=set)
    runs_on_oses: Set[str] = field(default_factory=set)
    job_working_dirs: Dict[str, str] = field(default_factory=dict)
    job_runtime_versions: Dict[str, Dict[str, Set[str]]] = field(default_factory=dict)
    job_package_managers: Dict[str, Set[str]] = field(default_factory=dict)
    job_runs_on: Dict[str, Set[str]] = field(default_factory=dict)
    job_steps: Dict[str, List[Tuple[Optional[str], Optional[str], Optional[str]]]] = field(
        default_factory=dict
    )


def _normalize_working_dir(raw_wd: Any) -> str:
    """Normalize a workflow working-directory scalar to '.' or a clean POSIX subpath."""
    if raw_wd is None or isinstance(raw_wd, bool):
        return ""
    cleaned = str(raw_wd).strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    cleaned = cleaned.strip("/")
    if not cleaned:
        return ""
    return "." if cleaned == "." else cleaned


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
    package managers, step run commands, unpinned setup jobs, working directories,
    runner OS targets, and per-job AST attributes across all jobs.
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
    working_dirs: Set[str] = set()
    runs_on_oses: Set[str] = set()
    job_working_dirs: Dict[str, str] = {}
    job_runtime_versions: Dict[str, Dict[str, Set[str]]] = {}
    job_package_managers: Dict[str, Set[str]] = {}
    job_runs_on: Dict[str, Set[str]] = {}
    job_steps: Dict[str, List[Tuple[Optional[str], Optional[str], Optional[str]]]] = {}

    if not isinstance(doc, Mapping):
        return WorkflowASTInfo(
            discovered_services=discovered_services,
            runtime_versions=runtime_versions,
            setup_actions=setup_actions,
            package_managers=package_managers,
            run_commands=run_commands,
            unpinned_jobs=unpinned_jobs,
            working_dirs=working_dirs,
            runs_on_oses=runs_on_oses,
            job_working_dirs=job_working_dirs,
            job_runtime_versions=job_runtime_versions,
            job_package_managers=job_package_managers,
            job_runs_on=job_runs_on,
            job_steps=job_steps,
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
            working_dirs=working_dirs,
            runs_on_oses=runs_on_oses,
            job_working_dirs=job_working_dirs,
            job_runtime_versions=job_runtime_versions,
            job_package_managers=job_package_managers,
            job_runs_on=job_runs_on,
            job_steps=job_steps,
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

        # 2. Job-scoped strategy.matrix, env, working-directory, and runs-on OS resolution
        strat = job.get("strategy")
        matrix: Mapping[str, Any] = {}
        if isinstance(strat, Mapping) and isinstance(strat.get("matrix"), Mapping):
            matrix = strat["matrix"]

        job_env: Dict[str, Any] = dict(workflow_env)
        if isinstance(job.get("env"), Mapping):
            job_env.update(job["env"])

        defaults = job.get("defaults")
        job_wd = ""
        if isinstance(defaults, Mapping):
            run_defaults = defaults.get("run")
            if isinstance(run_defaults, Mapping):
                job_wd = _normalize_working_dir(run_defaults.get("working-directory"))
        if job_wd:
            working_dirs.add(job_wd)
            job_working_dirs[job_name] = job_wd

        runs_on_raw = job.get("runs-on")
        if runs_on_raw is not None:
            resolved_runs_on = _resolve_version_expr(runs_on_raw, matrix, job_env)
            runs_on_oses.update(resolved_runs_on)
            job_runs_on[job_name] = resolved_runs_on

        job_rt: Dict[str, Set[str]] = {
            "python": set(),
            "node": set(),
            "go": set(),
            "rust": set(),
        }
        job_pms: Set[str] = set()
        job_runtime_versions[job_name] = job_rt
        job_package_managers[job_name] = job_pms

        # 3. Steps inspection
        steps = job.get("steps")
        if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
            continue

        job_step_sigs: List[Tuple[Optional[str], Optional[str], Optional[str]]] = []
        job_steps[job_name] = job_step_sigs
        step_wds: Set[str] = set()
        for step in steps:
            if not isinstance(step, Mapping):
                continue

            step_wd = _normalize_working_dir(step.get("working-directory"))
            if step_wd:
                working_dirs.add(step_wd)
                step_wds.add(step_wd)

            uses_raw = step.get("uses")
            uses = str(uses_raw).strip() if isinstance(uses_raw, str) else ""
            action = uses.split("@", 1)[0].strip().lower() if uses else ""
            action_ref = uses.split("@", 1)[1].strip() if "@" in uses else ""
            if action:
                setup_actions.add(action)

            name_raw = step.get("name")
            lower_name: Optional[str] = None
            if name_raw is not None:
                norm_name = str(name_raw).strip().lower()
                if norm_name:
                    lower_name = norm_name

            with_cfg = step.get("with")
            if not isinstance(with_cfg, Mapping):
                with_cfg = {}

            step_env = dict(job_env)
            if isinstance(step.get("env"), Mapping):
                step_env.update(step["env"])

            # Package manager actions & cache hints
            if action in PACKAGE_MANAGER_ACTIONS:
                pm_name = PACKAGE_MANAGER_ACTIONS[action]
                package_managers.add(pm_name)
                job_pms.add(pm_name)
            if action == "actions/setup-python":
                cache_val = str(with_cfg.get("cache") or "").strip().lower()
                if cache_val == "poetry":
                    package_managers.add("poetry")
                    job_pms.add("poetry")

            # Run commands & CLI command prefixes
            run_raw = step.get("run")
            norm_run_val: Optional[str] = None
            if isinstance(run_raw, str) and run_raw.strip():
                run_commands.append(run_raw)
                norm_run = " ".join(run_raw.split())
                if norm_run:
                    norm_run_val = norm_run
                for prefix in _extract_command_prefixes(run_raw):
                    if prefix in _KNOWN_PM_COMMANDS:
                        package_managers.add(prefix)
                        job_pms.add(prefix)

            job_step_sigs.append((action if action else None, lower_name, norm_run_val))

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
                    job_rt[lang].update(extracted)
                elif requires_pinned and not has_version_file:
                    unpinned_jobs.setdefault(lang, set()).add(job_name)

        if not job_wd and len(step_wds) == 1:
            job_working_dirs[job_name] = next(iter(step_wds))

    return WorkflowASTInfo(
        discovered_services=discovered_services,
        runtime_versions=runtime_versions,
        setup_actions=setup_actions,
        package_managers=package_managers,
        run_commands=run_commands,
        unpinned_jobs=unpinned_jobs,
        working_dirs=working_dirs,
        runs_on_oses=runs_on_oses,
        job_working_dirs=job_working_dirs,
        job_runtime_versions=job_runtime_versions,
        job_package_managers=job_package_managers,
        job_runs_on=job_runs_on,
        job_steps=job_steps,
    )


class DriftDetector:
    """
    Detects configuration drift between the codebase IR and existing YAML files.
    """

    def __init__(self, repo_root: str | Path):
        self.root = Path(repo_root).resolve()
        self.yaml = YAML(typ="safe")

    def _check_unit_drift(
        self,
        findings: List[DriftFinding],
        rel_path: str,
        ast_info: WorkflowASTInfo,
        *,
        language: str,
        working_dir: str,
        runtime_version: str,
        version_source: str,
        package_manager: str,
        matrix_versions: Sequence[str],
    ) -> None:
        """Verify working-directory, runtime/matrix versions, and package manager for one build unit."""
        lang_key = language.lower()
        pm = package_manager.lower()
        wd = _normalize_working_dir(working_dir) or "."

        if wd != "." and wd not in ast_info.working_dirs:
            findings.append(
                DriftFinding(
                    file_path=rel_path,
                    issue=(
                        f"Working directory '{wd}' for {language} package is missing from workflow "
                        "(expected defaults.run.working-directory or step working-directory)."
                    ),
                    severity="WARNING",
                    recommendation="Run 'hx generate' to synthesize multi-job working-directory configuration.",
                )
            )

        if wd != ".":
            matching_jobs = [jid for jid, jwd in ast_info.job_working_dirs.items() if jwd == wd]
        else:
            matching_jobs = [
                jid
                for jid in ast_info.job_runtime_versions
                if ast_info.job_working_dirs.get(jid, ".") == "."
            ]

        use_aggregate = not matching_jobs
        if not use_aggregate:
            found_versions: Set[str] = set()
            found_pms: Set[str] = set()
            for jid in matching_jobs:
                found_versions.update(ast_info.job_runtime_versions.get(jid, {}).get(lang_key, set()))
                found_pms.update(ast_info.job_package_managers.get(jid, set()))
            check_unpinned = ast_info.unpinned_jobs.get(lang_key, set()).intersection(matching_jobs)
        else:
            found_versions = ast_info.runtime_versions.get(lang_key, set())
            found_pms = ast_info.package_managers
            check_unpinned = ast_info.unpinned_jobs.get(lang_key, set())

        # Runtime & matrix version checks
        if lang_key in ast_info.runtime_versions:
            dedup_matrix = [
                v for v in dict.fromkeys(_normalize_version(m) for m in matrix_versions)
                if v and v != "latest"
            ]
            if len(dedup_matrix) > 1:
                expected_versions = dedup_matrix
            else:
                norm_ver = _normalize_version(runtime_version)
                expected_versions = [norm_ver] if (norm_ver and norm_ver != "latest") else []

            skip_bun = (
                lang_key == "node"
                and pm == "bun"
                and version_source in ("", "default")
                and "oven-sh/setup-bun" in ast_info.setup_actions
                and not found_versions
            )

            if expected_versions and not skip_bun:
                missing_vers = [v for v in expected_versions if v not in found_versions]
                pkg_suffix = f" for '{wd}'" if wd != "." else ""
                src_label = version_source or "manifest"
                if missing_vers:
                    for exp_ver in missing_vers:
                        findings.append(
                            DriftFinding(
                                file_path=rel_path,
                                issue=(
                                    f"Runtime version mismatch{pkg_suffix}: codebase specifies "
                                    f"{language} {exp_ver} ({src_label}), not found in workflow."
                                ),
                                severity="WARNING",
                                recommendation=f"Run 'hx generate' to update {language} version.",
                            )
                        )
                elif check_unpinned:
                    pin_target = ", ".join(expected_versions)
                    for job_name in sorted(check_unpinned):
                        findings.append(
                            DriftFinding(
                                file_path=rel_path,
                                issue=f"Unpinned {language} setup step in job '{job_name}': missing version pin.",
                                severity="WARNING",
                                recommendation=f"Pin {language} {pin_target} across all workflow jobs.",
                            )
                        )

        # Package manager checks
        if pm in PACKAGE_MANAGER_CHECKS:
            expected_action, issue_msg, rec_msg = PACKAGE_MANAGER_CHECKS[pm]
            if not use_aggregate:
                has_pm = pm in found_pms
            else:
                has_pm = (
                    expected_action in ast_info.setup_actions
                    or pm in ast_info.package_managers
                    or any(pm in _extract_command_prefixes(cmd) for cmd in ast_info.run_commands)
                )
            if not has_pm:
                msg = issue_msg if wd == "." else f"{issue_msg} (package: {wd})"
                findings.append(
                    DriftFinding(
                        file_path=rel_path,
                        issue=msg,
                        severity="WARNING",
                        recommendation=rec_msg,
                    )
                )

    @staticmethod
    def _step_policy_present(
        step_pol: StepPolicy,
        actual_steps: Sequence[Tuple[Optional[str], Optional[str], Optional[str]]],
    ) -> bool:
        """Return True if an expected StepPolicy matches any normalized AST step signature."""
        if step_pol.uses and step_pol.uses.strip():
            exp_uses = step_pol.uses.split("@", 1)[0].strip().lower()
            return any(act_uses == exp_uses for act_uses, _, _ in actual_steps)
        if step_pol.name and step_pol.name.strip():
            exp_name = step_pol.name.strip().lower()
            return any(act_name == exp_name for _, act_name, _ in actual_steps)
        if step_pol.run and step_pol.run.strip():
            exp_run = " ".join(step_pol.run.split())
            return any(act_run == exp_run for _, _, act_run in actual_steps)
        return True

    def check_drift(self, context: ProjectContext, synthesized_files: dict[str, str]) -> List[DriftFinding]:
        findings: List[DriftFinding] = []
        policy = HeurixPolicy.from_raw(context.policy_config)

        excluded_services = {
            normalize_service_name(item)
            for item in policy.services.exclude
            if isinstance(item, str) and item.strip()
        }
        active_services = [
            svc
            for svc in context.services
            if normalize_service_name(svc.name) not in excluded_services
        ]

        runner_overrides: Dict[str, str] = {
            str(jid): str(r).strip()
            for jid, r in policy.ci.runners.items()
            if str(jid).strip() and str(r).strip()
        }
        for jid, job_pol in policy.jobs.items():
            if job_pol.runner and job_pol.runner.strip():
                runner_overrides[str(jid)] = job_pol.runner.strip()

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

            # 1. Check if active (non-excluded) backing services are missing across all jobs
            for svc in active_services:
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

            # 2. Check OS matrix targets when multi-OS matrix is configured and unoverridden test jobs exist
            dedup_os = [
                o
                for o in dict.fromkeys(_normalize_version(item) for item in getattr(context, "matrix_os", []))
                if o
            ]
            test_job_ids = [
                jid for jid in ast_info.job_runs_on
                if jid == "test" or jid.startswith("test-")
            ]
            if test_job_ids:
                has_unoverridden_test_job = any(jid not in runner_overrides for jid in test_job_ids)
            else:
                has_unoverridden_test_job = (
                    not ast_info.job_runs_on
                    or any(jid not in runner_overrides for jid in ast_info.job_runs_on)
                )
            if len(dedup_os) > 1 and has_unoverridden_test_job:
                for os_name in dedup_os:
                    if os_name not in ast_info.runs_on_oses:
                        findings.append(
                            DriftFinding(
                                file_path=rel_path,
                                issue=f"OS matrix mismatch: codebase requires runner '{os_name}', not found in workflow runs-on targets.",
                                severity="WARNING",
                                recommendation="Run 'hx generate' to update workflow OS build matrix.",
                            )
                        )

            # 2b. Check explicit per-job runner overrides ([ci.runners] and [jobs.<id>].runner)
            for job_id, expected_runner in runner_overrides.items():
                if job_id in ast_info.job_runs_on:
                    if ast_info.job_runs_on[job_id] != {expected_runner}:
                        found_runners = ", ".join(sorted(ast_info.job_runs_on[job_id])) or "<missing>"
                        findings.append(
                            DriftFinding(
                                file_path=rel_path,
                                issue=(
                                    f"Runner mismatch for job '{job_id}': policy requires '{expected_runner}', "
                                    f"found '{found_runners}' in workflow."
                                ),
                                severity="WARNING",
                                recommendation="Run 'hx generate' to update job runner configuration.",
                            )
                        )

            # 2c. Check policy-injected workflow steps (pre_test, post_test, pre_steps, post_steps)
            for job_id, actual_steps in ast_info.job_steps.items():
                job_policy = policy.jobs.get(job_id)
                if job_id == "test" or job_id.startswith("test-"):
                    expected_steps: List[StepPolicy] = [
                        *policy.ci.steps.pre_test,
                        *policy.ci.steps.post_test,
                        *(job_policy.pre_steps if job_policy else ()),
                        *(job_policy.post_steps if job_policy else ()),
                    ]
                elif job_policy is not None:
                    expected_steps = [
                        *job_policy.pre_steps,
                        *job_policy.post_steps,
                    ]
                else:
                    expected_steps = []

                for step_pol in expected_steps:
                    if not self._step_policy_present(step_pol, actual_steps):
                        step_label = (
                            step_pol.name
                            or step_pol.uses
                            or (" ".join(step_pol.run.split())[:60] if step_pol.run else "custom step")
                        )
                        findings.append(
                            DriftFinding(
                                file_path=rel_path,
                                issue=f"Policy step '{step_label}' is missing from job '{job_id}'.",
                                severity="WARNING",
                                recommendation="Run 'hx generate' to inject configured policy workflow steps.",
                            )
                        )

            # 3. Check monorepo packages and active non-coordinator LanguageContext entries
            covered_keys: Set[Tuple[str, str]] = set()
            subpkg_langs: Set[str] = set()
            for pkg in getattr(context, "monorepo_packages", []):
                pkg_wd = _normalize_working_dir(pkg.path) or "."
                lang_key = pkg.language.lower()
                key = (pkg_wd, lang_key)
                if key in covered_keys:
                    continue
                covered_keys.add(key)
                if pkg_wd != ".":
                    subpkg_langs.add(lang_key)
                self._check_unit_drift(
                    findings,
                    rel_path,
                    ast_info,
                    language=pkg.language,
                    working_dir=pkg_wd,
                    runtime_version=pkg.runtime_version,
                    version_source=pkg.version_source,
                    package_manager=pkg.package_manager,
                    matrix_versions=pkg.matrix_versions,
                )

            for lang in context.languages:
                lang_key = lang.language.lower()
                lang_wd = _normalize_working_dir(lang.working_dir) or "."
                if lang.is_workspace_root is True and context.monorepo_packages:
                    continue
                if lang.is_workspace_root is None and lang_wd == "." and lang_key in subpkg_langs:
                    continue
                if (lang_wd, lang_key) in covered_keys:
                    continue
                covered_keys.add((lang_wd, lang_key))
                self._check_unit_drift(
                    findings,
                    rel_path,
                    ast_info,
                    language=lang.language,
                    working_dir=lang_wd,
                    runtime_version=lang.runtime_version,
                    version_source=lang.version_source,
                    package_manager=lang.package_manager,
                    matrix_versions=lang.matrix_versions,
                )

        return findings
