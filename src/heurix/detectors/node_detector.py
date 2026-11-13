"""
Node.js / TypeScript Ecosystem Detector.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple
from heurix.core.context import LanguageContext, MonorepoPackage, ProjectContext, ServiceRequirement
from heurix.core.indexer import RepoIndexer
from heurix.core.monorepo import discover_monorepo_topology
from heurix.detectors.base import BaseDetector
from heurix.detectors.python_detector import _extract_pg_credentials

NODE_MOCK_SERVICES = {"redis-mock", "ioredis-mock", "pg-mem"}
SQLITE_ADAPTERS = {"sqlite3", "better-sqlite3", "sqlite", "@libsql/client", "sql.js"}

_PRISMA_DATASOURCE_RE = re.compile(
    r"datasource\s+\w+\s*\{[^}]*provider\s*=\s*[\"']([^\"']+)[\"']",
    re.DOTALL | re.IGNORECASE,
)
_TYPEORM_POSTGRES_RE = re.compile(
    r"type\s*[:=]\s*[\"']postgres(?:ql)?[\"']",
    re.IGNORECASE,
)
_ENGINE_MAJOR_RE = re.compile(r"(?:>=|\^|~|=|<=|<|>)?\s*v?(\d+)")
_ROOT_INDICATORS = (
    "package.json",
    ".nvmrc",
    ".node-version",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
    "bun.lock",
    "pnpm-workspace.yaml",
    "turbo.json",
    "nx.json",
)


def _join(base_dir: str, fname: str) -> str:
    return fname if base_dir == "." else f"{base_dir}/{fname}"


def _extract_engines_node_matrix(engine_spec: Any) -> List[str]:
    """
    Extract discrete Node.js major versions from `engines.node` when explicit `||`
    branches exist (e.g. `"18 || 20 || 22"` -> `["18.x", "20.x", "22.x"]`).
    Returns an empty list for single constraints without `||` or < 2 distinct majors.
    """
    if not isinstance(engine_spec, str) or "||" not in engine_spec:
        return []

    versions: List[str] = []
    for branch in engine_spec.split("||"):
        match = _ENGINE_MAJOR_RE.search(branch)
        if match:
            ver = f"{match.group(1)}.x"
            if ver not in versions:
                versions.append(ver)

    return versions if len(versions) >= 2 else []


def _matches_scope(rel_path: str, base_dir: str, exclude_dirs: Sequence[str] = ()) -> bool:
    if base_dir != ".":
        return rel_path.startswith(f"{base_dir}/")
    return not any(rel_path.startswith(f"{d}/") for d in exclude_dirs)


def _has_real_postgres_adapter(
    indexer: RepoIndexer,
    active_deps: Dict[str, Any],
    base_dir: str = ".",
    exclude_dirs: Sequence[str] = (),
) -> bool:
    """
    Verify that Node dependencies or ORM schemas declare an explicit PostgreSQL
    backing adapter rather than mock or embedded SQLite drivers.
    """
    if any(k in active_deps for k in ["pg", "pg-pool", "postgres", "@prisma/adapter-pg"]):
        return True

    if "prisma" in active_deps or "@prisma/client" in active_deps:
        for prisma_file in indexer.find_files("*.prisma"):
            if not _matches_scope(prisma_file, base_dir, exclude_dirs):
                continue
            schema_text = indexer.read_text(prisma_file) or ""
            match = _PRISMA_DATASOURCE_RE.search(schema_text)
            if match and match.group(1).strip().lower() in {"postgresql", "postgres", "cockroachdb"}:
                return True

    if "typeorm" in active_deps:
        for cfg_file in indexer.find_files("*ormconfig*") + indexer.find_files("*data-source*"):
            if not _matches_scope(cfg_file, base_dir, exclude_dirs):
                continue
            cfg_text = indexer.read_text(cfg_file) or ""
            if _TYPEORM_POSTGRES_RE.search(cfg_text):
                return True

    return False


def _detect_node_lockfile(indexer: RepoIndexer, base_dir: str) -> Optional[Tuple[str, str, str]]:
    """Detect package manager, install command, and lockfile path inside `base_dir`."""
    pnpm_lock = _join(base_dir, "pnpm-lock.yaml")
    if indexer.has_file(pnpm_lock):
        return ("pnpm", "pnpm i --frozen-lockfile", pnpm_lock)

    yarn_lock = _join(base_dir, "yarn.lock")
    if indexer.has_file(yarn_lock):
        return ("yarn", "yarn install --frozen-lockfile", yarn_lock)

    bun_lockb = _join(base_dir, "bun.lockb")
    if indexer.has_file(bun_lockb):
        return ("bun", "bun install --frozen-lockfile", bun_lockb)

    bun_lock = _join(base_dir, "bun.lock")
    if indexer.has_file(bun_lock):
        return ("bun", "bun install --frozen-lockfile", bun_lock)

    pkg_lock = _join(base_dir, "package-lock.json")
    if indexer.has_file(pkg_lock):
        return ("npm", "npm ci", pkg_lock)

    return None


def _detect_node_unit_runner(
    indexer: RepoIndexer,
    base_dir: str,
    deps: Dict[str, Any],
    scripts: Dict[str, Any],
) -> Optional[str]:
    """Detect unit test runner ('vitest', 'jest', or 'mocha') from scripts, deps, and config files."""
    raw_test = scripts.get("test")
    test_lower = raw_test.lower() if isinstance(raw_test, str) else ""

    for runner in ("vitest", "jest", "mocha"):
        if runner in test_lower:
            return runner

    has_vitest_cfg = any(
        indexer.has_file(_join(base_dir, f"vitest.config.{ext}"))
        for ext in ("ts", "js", "mts", "mjs", "cts", "cjs")
    )
    if "vitest" in deps or has_vitest_cfg:
        return "vitest"

    has_jest_cfg = any(
        indexer.has_file(_join(base_dir, f"jest.config.{ext}"))
        for ext in ("ts", "js", "mts", "mjs", "cts", "cjs")
    )
    if "jest" in deps or "@jest/core" in deps or has_jest_cfg:
        return "jest"

    if "mocha" in deps:
        return "mocha"

    return None


def _detect_node_e2e_runner(
    indexer: RepoIndexer,
    base_dir: str,
    deps: Dict[str, Any],
    scripts: Dict[str, Any],
    package_manager: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Detect E2E test runner ('playwright' or 'cypress') and resolved command without prompting."""
    script_values = [val.lower() for val in scripts.values() if isinstance(val, str)]

    has_playwright_cfg = any(
        indexer.has_file(_join(base_dir, f"playwright.config.{ext}"))
        for ext in ("ts", "js", "mts", "mjs")
    )
    has_playwright = (
        "@playwright/test" in deps
        or "playwright" in deps
        or has_playwright_cfg
        or any("playwright" in val for val in script_values)
    )

    has_cypress_cfg = indexer.has_file(_join(base_dir, "cypress.json")) or any(
        indexer.has_file(_join(base_dir, f"cypress.config.{ext}"))
        for ext in ("ts", "js", "mts", "mjs")
    )
    has_cypress = (
        "cypress" in deps
        or has_cypress_cfg
        or any("cypress" in val for val in script_values)
    )

    if has_playwright:
        e2e_runner = "playwright"
        priority_keys = ("test:e2e", "e2e", "test:playwright", "playwright")
        default_subcmd = "playwright test"
    elif has_cypress:
        e2e_runner = "cypress"
        priority_keys = ("test:e2e", "e2e", "test:cypress", "cypress")
        default_subcmd = "cypress run"
    else:
        return None, None

    e2e_cmd: Optional[str] = None
    for key in priority_keys:
        val = scripts.get(key)
        if isinstance(val, str) and val.strip():
            e2e_cmd = f"{package_manager} run {key}"
            break

    if e2e_cmd is None:
        exec_prefix = {
            "pnpm": "pnpm exec",
            "yarn": "yarn",
            "bun": "bunx",
        }.get(package_manager, "npx")
        e2e_cmd = f"{exec_prefix} {default_subcmd}"

    return e2e_runner, e2e_cmd


class NodeDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "Node"

    def detect(self, indexer: RepoIndexer) -> bool:
        if any(indexer.has_file(f) for f in _ROOT_INDICATORS):
            return True
        return bool(discover_monorepo_topology(indexer).packages_by_lang.get("node"))

    def _analyze_node_dir(
        self,
        indexer: RepoIndexer,
        context: ProjectContext,
        base_dir: str,
        root_pm: str = "npm",
        root_version: str = "20.x",
        root_lockfile: Optional[str] = None,
        *,
        root_version_source: str = "default",
        root_install_cmd: Optional[str] = None,
        exclude_dirs: Sequence[str] = (),
        add_language_ctx: bool = True,
        add_monorepo_pkg: Optional[bool] = None,
        is_workspace_root: Optional[bool] = None,
    ) -> LanguageContext:
        pkg_scope = None if base_dir == "." else base_dir
        scope_label = f" in {base_dir}" if base_dir != "." else ""

        # 1. Determine Node Version
        node_version = "20.x"
        version_source = "default"

        nvmrc_path = _join(base_dir, ".nvmrc")
        node_ver_path = _join(base_dir, ".node-version")
        if indexer.has_file(nvmrc_path):
            raw = (indexer.read_text(nvmrc_path) or "").strip().lstrip("v")
            match_full = re.search(r"^(\d+\.\d+(?:\.\d+)?)", raw)
            match_major = re.search(r"^(\d+)", raw)
            if match_full:
                node_version = match_full.group(1)
                version_source = ".nvmrc"
            elif match_major:
                node_version = f"{match_major.group(1)}.x"
                version_source = ".nvmrc"
        elif indexer.has_file(node_ver_path):
            raw = (indexer.read_text(node_ver_path) or "").strip().lstrip("v")
            match_full = re.search(r"^(\d+\.\d+(?:\.\d+)?)", raw)
            match_major = re.search(r"^(\d+)", raw)
            if match_full:
                node_version = match_full.group(1)
                version_source = ".node-version"
            elif match_major:
                node_version = f"{match_major.group(1)}.x"
                version_source = ".node-version"

        # 2. Parse package.json
        pkg_data: Dict[str, Any] = {}
        pkg_json_path = _join(base_dir, "package.json")
        if indexer.has_file(pkg_json_path):
            try:
                content = indexer.read_text(pkg_json_path) or "{}"
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    pkg_data = parsed
            except Exception:
                pkg_data = {}

        engines_raw = pkg_data.get("engines")
        node_engine = engines_raw.get("node") if isinstance(engines_raw, dict) else None
        matrix_versions = _extract_engines_node_matrix(node_engine)

        if version_source == "default":
            if matrix_versions:
                node_version = matrix_versions[-1]
                version_source = "package.json (engines)"
            elif node_engine:
                match = re.search(r"(\d+)", str(node_engine))
                if match:
                    node_version = f"{match.group(1)}.x"
                    version_source = "package.json (engines)"
            elif base_dir != "." and root_version_source != "default":
                node_version = root_version
                version_source = root_version_source

        context.add_explain(f"Detected Node.js {node_version}{scope_label} (via {version_source})")
        if matrix_versions:
            context.add_explain(f"Detected Node.js matrix versions{scope_label}: {matrix_versions}")

        # 3. Determine Package Manager, install command, and cache_dependency_path
        local_lock = _detect_node_lockfile(indexer, base_dir)
        cache_dependency_path: Optional[str] = None
        if local_lock is not None:
            package_manager, install_cmd, cache_dependency_path = local_lock
            context.add_explain(f"Detected Package Manager: {package_manager} (via {cache_dependency_path})")
        elif base_dir != "." and root_lockfile is not None:
            package_manager = root_pm
            install_cmd = root_install_cmd or (
                "pnpm i --frozen-lockfile"
                if root_pm == "pnpm"
                else ("yarn install --frozen-lockfile" if root_pm == "yarn" else ("bun install --frozen-lockfile" if root_pm == "bun" else "npm ci"))
            )
            cache_dependency_path = root_lockfile
            context.add_explain(f"Inherited workspace Package Manager{scope_label}: {package_manager} (via {root_lockfile})")
        elif base_dir == "." and indexer.has_file("pnpm-workspace.yaml"):
            package_manager = "pnpm"
            install_cmd = "pnpm install"
            context.add_explain("Detected Package Manager: pnpm (via pnpm-workspace.yaml)")
        elif base_dir != "." and root_pm != "npm":
            package_manager = root_pm
            install_cmd = root_install_cmd or f"{root_pm} install"
        else:
            package_manager = "npm"
            install_cmd = "npm install"
            context.add_explain(f"Detected Package Manager: npm{scope_label}")

        # 4. Scripts: test, build, lint
        raw_scripts = pkg_data.get("scripts", {})
        scripts = raw_scripts if isinstance(raw_scripts, dict) else {}

        test_cmd: Optional[str] = None
        if "test" in scripts and isinstance(scripts["test"], str):
            test_val = scripts["test"]
            if "no test specified" not in test_val.lower():
                test_cmd = f"{package_manager} test" if package_manager != "npm" else "npm test"
                context.add_explain(f"Detected Test Script{scope_label}: '{test_val}' (via {pkg_json_path})")

        build_cmd: Optional[str] = None
        if "build" in scripts:
            build_cmd = f"{package_manager} run build" if package_manager != "npm" else "npm run build"
            context.add_explain(f"Detected Build Script{scope_label}: 'build' (via {pkg_json_path})")

        lint_cmd: Optional[str] = None
        if "lint" in scripts:
            lint_cmd = f"{package_manager} run lint" if package_manager != "npm" else "npm run lint"
            context.add_explain(f"Detected Linter Script{scope_label}: 'lint' (via {pkg_json_path})")

        # 5. Framework Detection & Backing Services
        raw_deps = pkg_data.get("dependencies", {})
        raw_dev_deps = pkg_data.get("devDependencies", {})
        deps: Dict[str, Any] = {
            **(raw_deps if isinstance(raw_deps, dict) else {}),
            **(raw_dev_deps if isinstance(raw_dev_deps, dict) else {}),
        }
        framework: Optional[str] = None

        if "next" in deps:
            framework = "Next.js"
        elif "nuxt" in deps:
            framework = "Nuxt"
        elif "@remix-run/react" in deps or "@remix-run/node" in deps:
            framework = "Remix"
        elif "vite" in deps:
            framework = "Vite"
        elif "express" in deps:
            framework = "Express"
        elif "@nestjs/core" in deps:
            framework = "NestJS"
        elif "astro" in deps:
            framework = "Astro"
        elif "@sveltejs/kit" in deps:
            framework = "SvelteKit"

        if framework:
            context.add_explain(f"Detected Framework{scope_label}: {framework}")

        active_deps = {k: v for k, v in deps.items() if k not in NODE_MOCK_SERVICES}
        svc_source = "package.json dependencies" if base_dir == "." else f"{base_dir}/package.json dependencies"

        has_orm_or_pg_mock = any(
            k in deps for k in ["typeorm", "prisma", "@prisma/client", "pg-mem", *SQLITE_ADAPTERS]
        )
        if _has_real_postgres_adapter(indexer, active_deps, base_dir, exclude_dirs):
            if not any(s.name == "postgres" and s.package_path == pkg_scope for s in context.services):
                pg_user, pg_password, pg_db = _extract_pg_credentials(context, indexer=indexer)
                context.services.append(
                    ServiceRequirement(
                        name="postgres",
                        image="postgres:16-alpine",
                        ports=[5432],
                        env={
                            "POSTGRES_USER": pg_user,
                            "POSTGRES_PASSWORD": pg_password,
                            "POSTGRES_DB": pg_db,
                        },
                        source_file=svc_source,
                        package_path=pkg_scope,
                    )
                )
                context.add_explain(f"Inferred Backing Service{scope_label}: PostgreSQL 16 (via node pg/prisma)")
        elif has_orm_or_pg_mock:
            context.add_explain(
                f"Skipped PostgreSQL inference{scope_label}: no real postgres adapter detected (mock or non-postgres datasource)"
            )

        redis_mocks_found = [k for k in deps if k in {"redis-mock", "ioredis-mock"}]
        if any(k in active_deps for k in ["redis", "ioredis"]):
            if not any(s.name == "redis" and s.package_path == pkg_scope for s in context.services):
                context.services.append(
                    ServiceRequirement(
                        name="redis",
                        image="redis:7-alpine",
                        ports=[6379],
                        env={},
                        source_file=svc_source,
                        package_path=pkg_scope,
                    )
                )
                context.add_explain(f"Inferred Backing Service{scope_label}: Redis 7 (via node redis/ioredis)")
        elif redis_mocks_found:
            context.add_explain(
                f"Filtered mock dependency '{', '.join(redis_mocks_found)}' from backing services{scope_label}"
            )

        if any(k in active_deps for k in ["mongodb", "mongoose"]):
            if not any(s.name == "mongodb" and s.package_path == pkg_scope for s in context.services):
                context.services.append(
                    ServiceRequirement(
                        name="mongodb",
                        image="mongo:6",
                        ports=[27017],
                        env={},
                        source_file=svc_source,
                        package_path=pkg_scope,
                    )
                )
                context.add_explain(f"Inferred Backing Service{scope_label}: MongoDB 6 (via mongoose/mongodb)")

        unit_test_runner = _detect_node_unit_runner(indexer, base_dir, deps, scripts)
        if unit_test_runner:
            context.add_explain(f"Detected Unit Test Runner{scope_label}: {unit_test_runner}")

        e2e_test_runner, e2e_cmd = _detect_node_e2e_runner(
            indexer, base_dir, deps, scripts, package_manager
        )
        if e2e_test_runner:
            context.add_explain(f"Detected E2E Test Runner{scope_label}: {e2e_test_runner} ({e2e_cmd})")

        lang_ctx = LanguageContext(
            language="node",
            runtime_version=node_version,
            version_source=version_source,
            package_manager=package_manager,
            install_cmd=install_cmd,
            build_cmd=build_cmd,
            test_cmd=test_cmd,
            lint_cmd=lint_cmd,
            unit_test_runner=unit_test_runner,
            e2e_test_runner=e2e_test_runner,
            e2e_cmd=e2e_cmd,
            working_dir=base_dir,
            framework=framework,
            confidence=0.95,
            matrix_versions=list(matrix_versions),
            cache_dependency_path=cache_dependency_path,
            is_workspace_root=is_workspace_root,
        )

        if add_language_ctx:
            context.languages.append(lang_ctx)

        should_add_pkg = add_monorepo_pkg if add_monorepo_pkg is not None else (base_dir != ".")
        if should_add_pkg:
            context.monorepo_packages.append(
                MonorepoPackage(
                    name=base_dir,
                    path=base_dir,
                    language="node",
                    package_manager=package_manager,
                    runtime_version=node_version,
                    version_source=version_source,
                    install_cmd=install_cmd,
                    build_cmd=build_cmd,
                    test_cmd=test_cmd,
                    lint_cmd=lint_cmd,
                    unit_test_runner=unit_test_runner,
                    e2e_test_runner=e2e_test_runner,
                    e2e_cmd=e2e_cmd,
                    framework=framework,
                    cache_dependency_path=cache_dependency_path,
                    matrix_versions=list(matrix_versions),
                )
            )

        return lang_ctx

    def analyze(self, indexer: RepoIndexer, context: ProjectContext) -> None:
        context.add_explain("Analyzing Node.js / JavaScript / TypeScript ecosystem...")

        root_pkg_data: Dict[str, Any] = {}
        if indexer.has_file("package.json"):
            try:
                parsed = json.loads(indexer.read_text("package.json") or "{}")
                if isinstance(parsed, dict):
                    root_pkg_data = parsed
            except Exception:
                root_pkg_data = {}

        has_ws_marker = False
        if indexer.has_file("pnpm-workspace.yaml"):
            has_ws_marker = True
            context.is_monorepo = True
            context.add_explain("Detected Monorepo Topology: pnpm-workspace.yaml")
        elif indexer.has_file("turbo.json"):
            has_ws_marker = True
            context.is_monorepo = True
            context.add_explain("Detected Monorepo Topology: Turborepo (turbo.json)")
        elif indexer.has_file("nx.json"):
            has_ws_marker = True
            context.is_monorepo = True
            context.add_explain("Detected Monorepo Topology: Nx (nx.json)")
        elif isinstance(root_pkg_data.get("workspaces"), (list, dict)):
            has_ws_marker = True
            context.is_monorepo = True
            context.add_explain("Detected Monorepo Topology: npm/yarn workspaces")

        topo = discover_monorepo_topology(indexer)
        node_sub_dirs = topo.packages_by_lang.get("node", [])
        if topo.is_monorepo:
            context.is_monorepo = True

        has_root_indicators = any(indexer.has_file(f) for f in _ROOT_INDICATORS)

        if has_root_indicators:
            is_ws_root = bool(has_ws_marker and len(node_sub_dirs) > 0)
            root_ctx = self._analyze_node_dir(
                indexer,
                context,
                ".",
                exclude_dirs=node_sub_dirs,
                add_language_ctx=True,
                add_monorepo_pkg=False,
                is_workspace_root=is_ws_root,
            )
            for sub_dir in node_sub_dirs:
                self._analyze_node_dir(
                    indexer,
                    context,
                    sub_dir,
                    root_pm=root_ctx.package_manager,
                    root_version=root_ctx.runtime_version,
                    root_lockfile=root_ctx.cache_dependency_path,
                    root_version_source=root_ctx.version_source,
                    root_install_cmd=root_ctx.install_cmd,
                    add_language_ctx=False,
                    add_monorepo_pkg=True,
                )
        else:
            for idx, sub_dir in enumerate(node_sub_dirs):
                self._analyze_node_dir(
                    indexer,
                    context,
                    sub_dir,
                    add_language_ctx=(idx == 0),
                    add_monorepo_pkg=True,
                    is_workspace_root=None,
                )

