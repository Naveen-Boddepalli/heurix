"""
GitHub Actions CI/CD Workflow Synthesizer.
"""

from __future__ import annotations

from collections import Counter
import copy
from dataclasses import dataclass, replace
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from heurix.core.context import ProjectContext, ServiceRequirement
from heurix.core.policy import (
    HeurixPolicy,
    StepPolicy,
    is_deployment_secret_key,
    is_sensitive_env_key,
    normalize_service_name,
)
from heurix.synthesizers.base import BaseSynthesizer
from heurix.synthesizers.templating import render_yaml_template

ACTION_VERSIONS: Dict[str, str] = {
    "actions/checkout": "v4",
    "astral-sh/setup-uv": "v5",
    "actions/setup-python": "v5",
    "snok/install-poetry": "v1",
    "pnpm/action-setup": "v4",
    "actions/setup-node": "v4",
    "oven-sh/setup-bun": "v2",
    "dtolnay/rust-toolchain": "stable",
    "Swatinem/rust-cache": "v2",
    "actions/setup-go": "v5",
    "golangci/golangci-lint-action": "v4",
    "amondnet/vercel-action": "v25",
    "FirebaseExtended/action-hosting-deploy": "v0",
}

_SHA40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_INVALID_JOB_ID_CHARS_RE = re.compile(r"[^a-zA-Z0-9_-]+")
_MULTI_HYPHEN_RE = re.compile(r"-{2,}")

_ECOSYSTEM_SOURCE_TOKENS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("python", ("python", "pyproject.toml", "requirements", "uv.lock", "poetry.lock", "pipfile", "setup.py", "setup.cfg")),
    ("node", ("node", "package.json", "pnpm", "yarn", "bun")),
    ("rust", ("rust", "cargo.toml", "cargo.lock")),
    ("go", ("go.mod", "go.sum")),
    ("cpp", ("cmakelists", "conan", "vcpkg")),
)

MATRIX_VERSION_KEYS: Dict[str, str] = {
    "python": "python-version",
    "node": "node-version",
    "go": "go-version",
    "rust": "toolchain",
}


@dataclass(frozen=True)
class _BuildUnit:
    name: str
    language: str
    working_dir: str
    package_manager: str
    runtime_version: str
    version_source: str
    install_cmd: Optional[str]
    build_cmd: Optional[str]
    test_cmd: Optional[str]
    lint_cmd: Optional[str]
    framework: Optional[str]
    cache_dependency_path: Optional[str]
    matrix_versions: Tuple[str, ...]


def _normalize_working_dir(raw_path: Optional[str]) -> str:
    """Normalize a relative package or working directory to '.' or POSIX subpath."""
    cleaned = (raw_path or "").strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    cleaned = cleaned.strip("/")
    return cleaned if cleaned and cleaned != "." else "."


def sanitize_job_id(raw_slug: str, used_ids: Set[str]) -> str:
    """
    Sanitize a raw package path or language slug into a unique GitHub Actions job ID
    matching ^[a-zA-Z_][a-zA-Z0-9_-]*$ with length <= 100 chars.
    """
    cleaned = _INVALID_JOB_ID_CHARS_RE.sub("-", str(raw_slug or ""))
    cleaned = _MULTI_HYPHEN_RE.sub("-", cleaned).strip("-")
    if not cleaned:
        cleaned = "pkg"

    base = cleaned if cleaned.startswith("test-") else f"test-{cleaned}"
    base = base[:100].rstrip("-") or "test-pkg"
    if not re.match(r"^[a-zA-Z_]", base):
        base = f"test-{base}"[:100].rstrip("-")

    if base not in used_ids:
        used_ids.add(base)
        return base

    counter = 2
    while True:
        suffix = f"-{counter}"
        prefix = base[: 100 - len(suffix)].rstrip("-") or "test"
        candidate = f"{prefix}{suffix}"
        if candidate not in used_ids:
            used_ids.add(candidate)
            return candidate
        counter += 1


def _collect_build_units(context: ProjectContext) -> List[_BuildUnit]:
    """
    Build normalized, deduplicated execution units from MonorepoPackage and LanguageContext.
    Prefers MonorepoPackage on (working_dir, language) collisions and skips workspace coordinators.
    """
    fallback_versions: Dict[str, str] = {}
    for lang in context.languages:
        lang_key = lang.language.lower()
        if lang_key not in fallback_versions and lang.runtime_version:
            fallback_versions[lang_key] = lang.runtime_version

    units: List[_BuildUnit] = []
    seen_keys: Set[Tuple[str, str]] = set()

    sorted_pkgs = sorted(
        context.monorepo_packages,
        key=lambda p: (_normalize_working_dir(p.path), p.language.lower()),
    )
    for pkg in sorted_pkgs:
        wd = _normalize_working_dir(pkg.path)
        lang_key = pkg.language.lower()
        key = (wd, lang_key)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        runtime_ver = pkg.runtime_version or fallback_versions.get(lang_key, "")
        units.append(
            _BuildUnit(
                name=pkg.name,
                language=lang_key,
                working_dir=wd,
                package_manager=pkg.package_manager.lower(),
                runtime_version=runtime_ver,
                version_source=pkg.version_source,
                install_cmd=pkg.install_cmd,
                build_cmd=pkg.build_cmd,
                test_cmd=pkg.test_cmd,
                lint_cmd=pkg.lint_cmd,
                framework=pkg.framework,
                cache_dependency_path=pkg.cache_dependency_path,
                matrix_versions=tuple(str(v).strip() for v in pkg.matrix_versions if str(v).strip()),
            )
        )

    subpkg_langs: Set[str] = {u.language for u in units if u.working_dir != "."}

    for lang in context.languages:
        lang_key = lang.language.lower()
        wd = _normalize_working_dir(lang.working_dir)

        if lang.is_workspace_root is True and context.monorepo_packages:
            continue
        if lang.is_workspace_root is None and wd == "." and lang_key in subpkg_langs:
            continue

        key = (wd, lang_key)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        units.append(
            _BuildUnit(
                name=lang.language,
                language=lang_key,
                working_dir=wd,
                package_manager=lang.package_manager.lower(),
                runtime_version=lang.runtime_version,
                version_source=lang.version_source,
                install_cmd=lang.install_cmd,
                build_cmd=lang.build_cmd,
                test_cmd=lang.test_cmd,
                lint_cmd=lang.lint_cmd,
                framework=lang.framework,
                cache_dependency_path=lang.cache_dependency_path,
                matrix_versions=tuple(str(v).strip() for v in lang.matrix_versions if str(v).strip()),
            )
        )

    units.sort(key=lambda u: (0 if u.working_dir == "." else 1, u.working_dir, u.language))
    return units


def _infer_service_language(source_file: str) -> Optional[str]:
    src_lower = source_file.lower()
    for lang, tokens in _ECOSYSTEM_SOURCE_TOKENS:
        if any(tok in src_lower for tok in tokens):
            return lang
    if src_lower == "go" or src_lower.startswith("go "):
        return "go"
    return None


def _scope_services_for_units(
    services: Sequence[ServiceRequirement],
    units: Sequence[_BuildUnit],
) -> Dict[int, List[ServiceRequirement]]:
    """Scope each ServiceRequirement cleanly to matching test job indices."""
    scoped: Dict[int, List[ServiceRequirement]] = {i: [] for i in range(len(units))}
    if not services or not units:
        return scoped

    if len(units) == 1:
        scoped[0] = list(services)
        return scoped

    for svc in services:
        matched: List[int] = []
        if svc.package_path is not None:
            norm_pkg = _normalize_working_dir(svc.package_path)
            if norm_pkg != ".":
                matched = [i for i, u in enumerate(units) if u.working_dir == norm_pkg]
            else:
                matched = [i for i, u in enumerate(units) if u.working_dir == "."]

        if not matched:
            src_norm = (svc.source_file or "").strip().replace("\\", "/")
            while src_norm.startswith("./"):
                src_norm = src_norm[2:]
            if src_norm:
                matched = [
                    i
                    for i, u in enumerate(units)
                    if u.working_dir != "."
                    and (src_norm == u.working_dir or src_norm.startswith(f"{u.working_dir}/"))
                ]

        if not matched and svc.source_file:
            inferred_lang = _infer_service_language(svc.source_file)
            if inferred_lang:
                matched = [i for i, u in enumerate(units) if u.language == inferred_lang]

        if not matched:
            matched = list(range(len(units)))

        for idx in matched:
            scoped[idx].append(svc)

    return scoped


def _build_services_map_vm(scoped_services: Sequence[ServiceRequirement]) -> Dict[str, Any]:
    services_dict: Dict[str, Any] = {}
    for svc in scoped_services:
        svc_key = svc.name.lower()
        if svc_key in services_dict:
            continue
        svc_entry: Dict[str, Any] = {
            "image": svc.image,
            "env": dict(svc.env) if svc.env else None,
            "ports": [f"{p}:{p}" for p in svc.ports] if svc.ports else None,
            "options": None,
        }

        if "postgres" in svc_key or "postgres" in svc.image.lower():
            svc_entry["options"] = (
                "--health-cmd pg_isready --health-interval 10s --health-timeout 5s --health-retries 5"
            )
        elif "redis" in svc_key or "redis" in svc.image.lower():
            svc_entry["options"] = (
                '--health-cmd "redis-cli ping" --health-interval 10s --health-timeout 5s --health-retries 5'
            )

        services_dict[svc_key] = svc_entry
    return services_dict


def _build_action_step_vm(
    name: str,
    action_repo: str,
    action_shas: Dict[str, str],
    with_cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a plain workflow step view-model referencing a pinned tag or 40-char commit SHA."""
    default_ref = ACTION_VERSIONS[action_repo]
    step: Dict[str, Any] = {"name": name}
    pinned_sha = action_shas.get(action_repo, "").strip()
    if pinned_sha and _SHA40_RE.match(pinned_sha):
        step["uses"] = f"{action_repo}@{pinned_sha}"
        step["uses_comment"] = default_ref
    else:
        step["uses"] = f"{action_repo}@{default_ref}"
    if with_cfg:
        step["with"] = dict(with_cfg)
    return step


def _resolve_job_runner_override(policy: HeurixPolicy, job_id: str) -> Optional[str]:
    """Resolve explicit per-job runner override: [jobs.<id>].runner > [ci.runners].<id>."""
    job_policy = policy.jobs.get(job_id)
    if job_policy and job_policy.runner:
        return job_policy.runner
    ci_runner = policy.ci.runners.get(job_id)
    if ci_runner:
        return ci_runner
    return None


def _resolve_fallback_runner(context: ProjectContext, policy: HeurixPolicy) -> str:
    """Resolve fallback runner preserving context.runner / [engine].runner precedence."""
    ctx_runner = (getattr(context, "runner", None) or "").strip()
    if ctx_runner and ctx_runner != "ubuntu-latest":
        return ctx_runner
    if (
        "runner" in policy.engine.model_fields_set
        and "os" not in policy.matrix
        and "os" not in policy.overrides
    ):
        return policy.engine.runner
    return ctx_runner or policy.engine.runner or "ubuntu-latest"


def _convert_custom_step_vm(
    step_policy: StepPolicy,
    action_shas: Dict[str, str],
    pin_actions: bool,
) -> Dict[str, Any]:
    """Convert a StepPolicy into a step view-model with optional 40-char SHA pinning."""
    step = step_policy.to_step_dict()
    raw_uses = step.get("uses")
    if (
        pin_actions
        and isinstance(raw_uses, str)
        and raw_uses
        and not raw_uses.startswith(("./", "docker://"))
        and "@" in raw_uses
    ):
        action_repo, existing_ref = raw_uses.rsplit("@", 1)
        pinned_sha = action_shas.get(action_repo, "").strip()
        if pinned_sha and _SHA40_RE.match(pinned_sha):
            step["uses"] = f"{action_repo}@{pinned_sha}"
            if not _SHA40_RE.match(existing_ref):
                step["uses_comment"] = existing_ref
            elif action_repo in ACTION_VERSIONS:
                step["uses_comment"] = ACTION_VERSIONS[action_repo]
    return step


def _resolve_effective_env_and_secrets(
    context: ProjectContext,
    policy: HeurixPolicy,
) -> Tuple[Dict[str, str], List[str], Set[str]]:
    """Compute idempotent SEC-02/SEC-03 filtered env_vars, test_secrets, and deployment_secrets."""
    deployment_secret_set: Set[str] = {
        str(s).strip() for s in context.deployment_secrets if str(s).strip()
    }
    for raw_s in policy.secrets.deploy:
        s = str(raw_s).strip()
        if s:
            deployment_secret_set.add(s)

    effective_test_secrets: List[str] = []
    seen_test_secrets: Set[str] = set()
    for raw_s in (*context.test_secrets, *policy.secrets.test):
        s = str(raw_s).strip()
        if not s or s in seen_test_secrets:
            continue
        if s in deployment_secret_set or is_deployment_secret_key(s):
            continue
        seen_test_secrets.add(s)
        effective_test_secrets.append(s)

    effective_env_vars: Dict[str, str] = {}
    for raw_k, raw_v in context.env_vars.items():
        k = str(raw_k).strip()
        if not k or is_sensitive_env_key(k) or k in deployment_secret_set or k in seen_test_secrets:
            continue
        effective_env_vars[k] = str(raw_v)
    for raw_k, raw_v in policy.env.items():
        k = str(raw_k).strip()
        if not k or is_sensitive_env_key(k) or k in deployment_secret_set or k in seen_test_secrets:
            continue
        effective_env_vars[k] = str(raw_v)

    return effective_env_vars, effective_test_secrets, deployment_secret_set


def _build_test_job_vm(
    unit: _BuildUnit,
    context: ProjectContext,
    runner: str,
    action_shas: Dict[str, str],
    job_id: str,
    scoped_services: Sequence[ServiceRequirement],
    *,
    runner_override: Optional[str] = None,
    pre_steps: Sequence[Dict[str, Any]] = (),
    post_steps: Sequence[Dict[str, Any]] = (),
    effective_env_vars: Optional[Dict[str, str]] = None,
    effective_test_secrets: Optional[Sequence[str]] = None,
    effective_deployment_secrets: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Build a single CI test job view-model for a normalized _BuildUnit."""
    if runner_override is not None:
        os_matrix: List[str] = []
    else:
        raw_os = [str(o).strip() for o in getattr(context, "matrix_os", []) if str(o).strip()]
        os_matrix = list(dict.fromkeys(raw_os))
        os_matrix = os_matrix if len(os_matrix) > 1 else []

    matrix_key = MATRIX_VERSION_KEYS.get(unit.language)
    raw_vers = [str(v).strip() for v in unit.matrix_versions if str(v).strip()]
    ver_matrix = list(dict.fromkeys(raw_vers))
    if unit.language == "node" and unit.package_manager == "bun":
        ver_matrix = []
    ver_matrix = ver_matrix if (matrix_key and len(ver_matrix) > 1) else []

    matrix_dict: Dict[str, List[str]] = {}
    if os_matrix:
        matrix_dict["os"] = os_matrix
    if ver_matrix and matrix_key:
        matrix_dict[matrix_key] = ver_matrix

    effective_runs_on = (
        runner_override
        if runner_override is not None
        else ("${{ matrix.os }}" if os_matrix else runner)
    )
    effective_version = (
        f"${{{{ matrix.{matrix_key} }}}}"
        if (ver_matrix and matrix_key)
        else unit.runtime_version
    )

    job: Dict[str, Any] = {
        "name": None,
        "needs": None,
        "if": None,
        "runs-on": effective_runs_on,
        "defaults": {"run": {"working-directory": unit.working_dir}} if unit.working_dir != "." else None,
        "strategy": {"fail-fast": False, "matrix": matrix_dict} if matrix_dict else None,
        "services": _build_services_map_vm(scoped_services) if scoped_services else None,
        "steps": [],
    }

    steps: List[Dict[str, Any]] = [
        _build_action_step_vm("Checkout repository", "actions/checkout", action_shas)
    ]

    install_cmd = unit.install_cmd.strip() if isinstance(unit.install_cmd, str) and unit.install_cmd.strip() else None
    cache_dep_path = (
        unit.cache_dependency_path.strip()
        if isinstance(unit.cache_dependency_path, str) and unit.cache_dependency_path.strip()
        else None
    )

    if unit.language == "python":
        py_label = f"Set up Python {effective_version}" if effective_version else "Set up Python"
        if unit.package_manager == "uv":
            uv_with: Dict[str, Any] = {"enable-cache": True}
            if unit.working_dir != ".":
                uv_with["working-directory"] = unit.working_dir
            if ver_matrix and effective_version:
                uv_with["python-version"] = effective_version
            steps.append(
                _build_action_step_vm(
                    "Install uv",
                    "astral-sh/setup-uv",
                    action_shas,
                    uv_with,
                )
            )
            py_with: Dict[str, Any] = {}
            if effective_version:
                py_with["python-version"] = effective_version
            steps.append(
                _build_action_step_vm(
                    py_label,
                    "actions/setup-python",
                    action_shas,
                    py_with or None,
                )
            )
            if install_cmd:
                steps.append({
                    "name": "Install dependencies",
                    "run": install_cmd,
                })
        elif unit.package_manager == "poetry":
            py_with = {"cache": "poetry"}
            if effective_version:
                py_with["python-version"] = effective_version
            if cache_dep_path:
                py_with["cache-dependency-path"] = cache_dep_path
            steps.append(
                _build_action_step_vm(
                    py_label,
                    "actions/setup-python",
                    action_shas,
                    py_with,
                )
            )
            steps.append(
                _build_action_step_vm(
                    "Install Poetry",
                    "snok/install-poetry",
                    action_shas,
                    {"virtualenvs-create": True, "virtualenvs-in-project": True},
                )
            )
            if install_cmd:
                steps.append({
                    "name": "Install dependencies",
                    "run": install_cmd,
                })
        else:
            py_with = {}
            if effective_version:
                py_with["python-version"] = effective_version
            if install_cmd and ("requirements" in install_cmd or "pip install -e" in install_cmd):
                py_with["cache"] = "pip"
            if cache_dep_path:
                py_with.setdefault("cache", "pip")
                py_with["cache-dependency-path"] = cache_dep_path
            steps.append(
                _build_action_step_vm(
                    py_label,
                    "actions/setup-python",
                    action_shas,
                    py_with or None,
                )
            )
            if install_cmd:
                steps.append({
                    "name": "Install dependencies",
                    "run": install_cmd,
                })

    elif unit.language == "node":
        node_label = f"Set up Node.js {effective_version}" if effective_version else "Set up Node.js"
        if unit.package_manager == "pnpm":
            steps.append(
                _build_action_step_vm(
                    "Install pnpm",
                    "pnpm/action-setup",
                    action_shas,
                    {"version": "9"},
                )
            )
            node_with: Dict[str, Any] = {"cache": "pnpm"}
            if effective_version:
                node_with["node-version"] = effective_version
            if cache_dep_path:
                node_with["cache-dependency-path"] = cache_dep_path
            steps.append(
                _build_action_step_vm(
                    node_label,
                    "actions/setup-node",
                    action_shas,
                    node_with,
                )
            )
            if install_cmd:
                steps.append({
                    "name": "Install dependencies",
                    "run": install_cmd,
                })
        elif unit.package_manager == "yarn":
            node_with = {"cache": "yarn"}
            if effective_version:
                node_with["node-version"] = effective_version
            if cache_dep_path:
                node_with["cache-dependency-path"] = cache_dep_path
            steps.append(
                _build_action_step_vm(
                    node_label,
                    "actions/setup-node",
                    action_shas,
                    node_with,
                )
            )
            if install_cmd:
                steps.append({
                    "name": "Install dependencies",
                    "run": install_cmd,
                })
        elif unit.package_manager == "bun":
            steps.append(
                _build_action_step_vm(
                    "Set up Bun",
                    "oven-sh/setup-bun",
                    action_shas,
                    {"bun-version": "latest"},
                )
            )
            if install_cmd:
                steps.append({
                    "name": "Install dependencies",
                    "run": install_cmd,
                })
        else:
            node_with = {"cache": "npm"}
            if effective_version:
                node_with["node-version"] = effective_version
            if cache_dep_path:
                node_with["cache-dependency-path"] = cache_dep_path
            steps.append(
                _build_action_step_vm(
                    node_label,
                    "actions/setup-node",
                    action_shas,
                    node_with,
                )
            )
            if install_cmd:
                steps.append({
                    "name": "Install dependencies",
                    "run": install_cmd,
                })

    elif unit.language == "rust":
        rust_label = f"Set up Rust ({effective_version})" if effective_version else "Set up Rust"
        rust_with: Optional[Dict[str, Any]] = {"toolchain": effective_version} if effective_version else None
        steps.append(
            _build_action_step_vm(
                rust_label,
                "dtolnay/rust-toolchain",
                action_shas,
                rust_with,
            )
        )
        rust_cache_with: Optional[Dict[str, Any]] = None
        if unit.working_dir != ".":
            rust_cache_with = {
                "workspaces": f"{unit.working_dir} -> target",
                "prefix-key": job_id,
            }
        steps.append(
            _build_action_step_vm("Rust Cache", "Swatinem/rust-cache", action_shas, rust_cache_with)
        )

    elif unit.language == "go":
        go_label = f"Set up Go {effective_version}" if effective_version else "Set up Go"
        go_with: Dict[str, Any] = {"cache": True}
        if effective_version:
            go_with["go-version"] = effective_version
        if cache_dep_path:
            go_with["cache-dependency-path"] = cache_dep_path
        steps.append(
            _build_action_step_vm(
                go_label,
                "actions/setup-go",
                action_shas,
                go_with,
            )
        )
        if install_cmd:
            steps.append({
                "name": "Download Go dependencies",
                "run": install_cmd,
            })

    elif unit.language == "cpp":
        apt_pkgs = "cmake ninja-build build-essential"
        if unit.lint_cmd and "clang-tidy" in unit.lint_cmd:
            apt_pkgs += " clang-tidy"
        cpp_apt_run = f"sudo apt-get update && sudo apt-get install -y {apt_pkgs}"
        ver_suffix = f" ({unit.runtime_version})" if unit.runtime_version else ""

        if effective_runs_on == "${{ matrix.os }}":
            steps.append({
                "name": f"Install build tools (Linux){ver_suffix}",
                "if": "runner.os == 'Linux'",
                "run": cpp_apt_run,
            })
            steps.append({
                "name": f"Install build tools (macOS){ver_suffix}",
                "if": "runner.os == 'macOS'",
                "run": "brew install cmake ninja",
            })
            steps.append({
                "name": f"Install build tools (Windows){ver_suffix}",
                "if": "runner.os == 'Windows'",
                "run": "choco install cmake ninja",
            })
        else:
            runner_lower = effective_runs_on.lower()
            if "macos" in runner_lower:
                cpp_install_run = "brew install cmake ninja"
            elif "windows" in runner_lower:
                cpp_install_run = "choco install cmake ninja"
            else:
                cpp_install_run = cpp_apt_run
            steps.append({
                "name": f"Install build tools{ver_suffix}",
                "run": cpp_install_run,
            })

    if pre_steps:
        steps.extend(copy.deepcopy(step) for step in pre_steps)

    # Build and Lint steps (run build before lint for cpp to generate compile_commands.json)
    if unit.language == "cpp":
        if unit.build_cmd:
            steps.append({
                "name": f"Build ({unit.language})",
                "run": unit.build_cmd,
            })
        if unit.lint_cmd:
            steps.append({
                "name": f"Lint code ({unit.language})",
                "run": unit.lint_cmd,
            })
    elif unit.language == "go":
        if unit.lint_cmd:
            lint_with: Dict[str, Any] = {"version": "v1.57"}
            if unit.working_dir != ".":
                lint_with["working-directory"] = unit.working_dir
            steps.append(
                _build_action_step_vm(
                    "Run golangci-lint",
                    "golangci/golangci-lint-action",
                    action_shas,
                    lint_with,
                )
            )
        if unit.build_cmd:
            steps.append({
                "name": f"Build ({unit.language})",
                "run": unit.build_cmd,
            })
    else:
        if unit.lint_cmd:
            steps.append({
                "name": f"Lint code ({unit.language})",
                "run": unit.lint_cmd,
            })
        if unit.build_cmd:
            steps.append({
                "name": f"Build ({unit.language})",
                "run": unit.build_cmd,
            })

    # Test step (SEC-02 env redaction + SEC-03 secret isolation)
    if unit.test_cmd:
        step_obj: Dict[str, Any] = {
            "name": f"Run tests ({unit.language})",
            "run": unit.test_cmd,
        }
        env_source = effective_env_vars if effective_env_vars is not None else context.env_vars
        test_sec_source = (
            effective_test_secrets if effective_test_secrets is not None else context.test_secrets
        )
        deployment_secret_set = (
            effective_deployment_secrets
            if effective_deployment_secrets is not None
            else set(context.deployment_secrets)
        )

        step_env: Dict[str, str] = {}
        for k, v in env_source.items():
            if not is_sensitive_env_key(k) and k not in deployment_secret_set:
                step_env[k] = str(v)
        for s in test_sec_source:
            if s not in deployment_secret_set and not is_deployment_secret_key(s):
                step_env[s] = f"${{{{ secrets.{s} }}}}"

        if step_env:
            step_obj["env"] = step_env

        steps.append(step_obj)

    if post_steps:
        steps.extend(copy.deepcopy(step) for step in post_steps)

    job["steps"] = steps
    return job


def _build_deploy_jobs_vm(
    context: ProjectContext,
    deploy_needs: Any,
    deploy_if: str,
    action_shas: Dict[str, str],
    policy: HeurixPolicy,
) -> Dict[str, Dict[str, Any]]:
    """Build deployment job view-models for detected cloud deployment targets."""
    deploy_jobs: Dict[str, Dict[str, Any]] = {}
    for target in getattr(context, "deployment_targets", []):
        if target.platform == "vercel":
            job_policy = policy.jobs.get("deploy_vercel")
            pre_steps = [
                _convert_custom_step_vm(s, action_shas, policy.ci.pin_actions)
                for s in (job_policy.pre_steps if job_policy else ())
            ]
            post_steps = [
                _convert_custom_step_vm(s, action_shas, policy.ci.pin_actions)
                for s in (job_policy.post_steps if job_policy else ())
            ]
            deploy_jobs["deploy_vercel"] = {
                "name": "Deploy to Vercel",
                "needs": deploy_needs,
                "if": deploy_if,
                "runs-on": _resolve_job_runner_override(policy, "deploy_vercel") or "ubuntu-latest",
                "defaults": None,
                "strategy": None,
                "services": None,
                "steps": [
                    _build_action_step_vm("Checkout repository", "actions/checkout", action_shas),
                    *pre_steps,
                    _build_action_step_vm(
                        "Deploy to Vercel (Production)",
                        "amondnet/vercel-action",
                        action_shas,
                        {
                            "vercel-token": "${{ secrets.VERCEL_TOKEN }}",
                            "vercel-org-id": "${{ secrets.VERCEL_ORG_ID }}",
                            "vercel-project-id": "${{ secrets.VERCEL_PROJECT_ID }}",
                            "vercel-args": "--prod",
                        },
                    ),
                    *post_steps,
                ],
            }
        elif target.platform == "firebase":
            job_policy = policy.jobs.get("deploy_firebase")
            pre_steps = [
                _convert_custom_step_vm(s, action_shas, policy.ci.pin_actions)
                for s in (job_policy.pre_steps if job_policy else ())
            ]
            post_steps = [
                _convert_custom_step_vm(s, action_shas, policy.ci.pin_actions)
                for s in (job_policy.post_steps if job_policy else ())
            ]
            deploy_jobs["deploy_firebase"] = {
                "name": "Deploy to Firebase",
                "needs": deploy_needs,
                "if": deploy_if,
                "runs-on": _resolve_job_runner_override(policy, "deploy_firebase") or "ubuntu-latest",
                "defaults": None,
                "strategy": None,
                "services": None,
                "steps": [
                    _build_action_step_vm("Checkout repository", "actions/checkout", action_shas),
                    *pre_steps,
                    _build_action_step_vm(
                        "Deploy to Firebase Hosting",
                        "FirebaseExtended/action-hosting-deploy",
                        action_shas,
                        {
                            "repoToken": "${{ secrets.GITHUB_TOKEN }}",
                            "firebaseServiceAccount": "${{ secrets.FIREBASE_SERVICE_ACCOUNT }}",
                            "projectId": target.project_id or context.repo_name,
                            "channelId": "live",
                        },
                    ),
                    *post_steps,
                ],
            }
    return deploy_jobs


class GitHubActionsSynthesizer(BaseSynthesizer):
    @property
    def name(self) -> str:
        return "GitHub Actions CI"

    def synthesize(self, context: ProjectContext) -> Dict[str, str]:
        policy = HeurixPolicy.from_raw(context.policy_config)

        default_branch = policy.ci.default_branch
        trigger_branches: List[str] = []
        for branch in (default_branch, "main", "master"):
            if branch not in trigger_branches:
                trigger_branches.append(branch)

        action_shas: Dict[str, str] = (
            {str(k): str(v) for k, v in policy.ci.action_shas.items()}
            if policy.ci.pin_actions
            else {}
        )

        fallback_runner = _resolve_fallback_runner(context, policy)

        excluded_services = {
            normalize_service_name(item)
            for item in policy.services.exclude
            if isinstance(item, str) and item.strip()
        }
        effective_services = [
            svc
            for svc in context.services
            if normalize_service_name(svc.name) not in excluded_services
        ]

        raw_units = _collect_build_units(context)
        units = [
            replace(u, lint_cmd=None)
            if (u.lint_cmd and not policy.linters.is_enabled_for(u.language))
            else u
            for u in raw_units
        ]

        effective_env_vars, effective_test_secrets, effective_deployment_secrets = (
            _resolve_effective_env_and_secrets(context, policy)
        )

        global_pre_steps = [
            _convert_custom_step_vm(s, action_shas, policy.ci.pin_actions)
            for s in policy.ci.steps.pre_test
        ]
        global_post_steps = [
            _convert_custom_step_vm(s, action_shas, policy.ci.pin_actions)
            for s in policy.ci.steps.post_test
        ]

        def _job_steps_for(job_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
            job_policy = policy.jobs.get(job_id)
            job_pre = [
                _convert_custom_step_vm(s, action_shas, policy.ci.pin_actions)
                for s in (job_policy.pre_steps if job_policy else ())
            ]
            job_post = [
                _convert_custom_step_vm(s, action_shas, policy.ci.pin_actions)
                for s in (job_policy.post_steps if job_policy else ())
            ]
            return ([*global_pre_steps, *job_pre], [*job_post, *global_post_steps])

        path_filters: Optional[List[str]] = None
        if context.is_monorepo:
            has_root_unit = any(u.working_dir == "." for u in units)
            sub_paths = sorted(
                {
                    f"{wd}/**"
                    for wd in (
                        [_normalize_working_dir(pkg.path) for pkg in context.monorepo_packages]
                        + [u.working_dir for u in units]
                    )
                    if wd != "."
                }
            )
            path_filters = ["**"] if (has_root_unit or not sub_paths) else sub_paths

        jobs_vm: Dict[str, Dict[str, Any]] = {}
        test_job_ids: List[str] = []
        if not units:
            pre_steps, post_steps = _job_steps_for("test")
            runner_override = _resolve_job_runner_override(policy, "test")
            jobs_vm["test"] = {
                "name": None,
                "needs": None,
                "if": None,
                "runs-on": runner_override or fallback_runner,
                "defaults": None,
                "strategy": None,
                "services": _build_services_map_vm(effective_services) if effective_services else None,
                "steps": [
                    _build_action_step_vm("Checkout repository", "actions/checkout", action_shas),
                    *copy.deepcopy(pre_steps),
                    *copy.deepcopy(post_steps),
                ],
            }
            test_job_ids.append("test")
        else:
            single_root_compat = (
                len(units) == 1
                and units[0].working_dir == "."
                and not (context.is_monorepo and context.monorepo_packages)
            )
            scoped_by_idx = _scope_services_for_units(effective_services, units)
            if single_root_compat:
                pre_steps, post_steps = _job_steps_for("test")
                jobs_vm["test"] = _build_test_job_vm(
                    units[0],
                    context,
                    fallback_runner,
                    action_shas,
                    "test",
                    scoped_by_idx.get(0, ()),
                    runner_override=_resolve_job_runner_override(policy, "test"),
                    pre_steps=pre_steps,
                    post_steps=post_steps,
                    effective_env_vars=effective_env_vars,
                    effective_test_secrets=effective_test_secrets,
                    effective_deployment_secrets=effective_deployment_secrets,
                )
                test_job_ids.append("test")
            else:
                wd_counts = Counter(u.working_dir for u in units)
                used_ids: Set[str] = set()
                for idx, unit in enumerate(units):
                    if unit.working_dir == ".":
                        raw_slug = unit.language
                    elif wd_counts[unit.working_dir] > 1:
                        raw_slug = f"{unit.working_dir}-{unit.language}"
                    else:
                        raw_slug = unit.working_dir
                    job_id = sanitize_job_id(raw_slug, used_ids)
                    pre_steps, post_steps = _job_steps_for(job_id)
                    jobs_vm[job_id] = _build_test_job_vm(
                        unit,
                        context,
                        fallback_runner,
                        action_shas,
                        job_id,
                        scoped_by_idx.get(idx, ()),
                        runner_override=_resolve_job_runner_override(policy, job_id),
                        pre_steps=pre_steps,
                        post_steps=post_steps,
                        effective_env_vars=effective_env_vars,
                        effective_test_secrets=effective_test_secrets,
                        effective_deployment_secrets=effective_deployment_secrets,
                    )
                    test_job_ids.append(job_id)

        deploy_needs: Any = test_job_ids[0] if test_job_ids == ["test"] else list(test_job_ids)
        deploy_if = f"github.ref == 'refs/heads/{default_branch}' && github.event_name == 'push'"
        jobs_vm.update(_build_deploy_jobs_vm(context, deploy_needs, deploy_if, action_shas, policy))

        workflow_vm: Dict[str, Any] = {
            "name": "CI",
            "on": {
                "push": {
                    "branches": list(trigger_branches),
                    "paths": list(path_filters) if path_filters else None,
                },
                "pull_request": {
                    "branches": list(trigger_branches),
                    "paths": list(path_filters) if path_filters else None,
                },
            },
            "jobs": jobs_vm,
        }

        rendered = render_yaml_template(
            "workflows/ci.yml.j2",
            workflow_vm,
            repo_root=context.repo_root or None,
            templates_dir=policy.engine.templates_dir,
        )
        return {".github/workflows/ci.yml": rendered}


