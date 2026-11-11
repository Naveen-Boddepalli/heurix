"""
Python Language and Ecosystem Detector.
"""

from __future__ import annotations

import configparser
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        import tomllib  # type: ignore
from heurix.core.context import LanguageContext, MonorepoPackage, ProjectContext, ServiceRequirement
from heurix.core.indexer import RepoIndexer
from heurix.core.monorepo import NON_PACKAGE_DIRS, discover_monorepo_topology
from heurix.detectors.base import BaseDetector

PYTHON_MOCK_SERVICES = {"fakeredis", "mockredispy", "testing.postgresql", "pgmock"}

_MOCK_DEP_PATTERN = re.compile(
    r"(?:testing[._-]postgresql|fakeredis|mockredispy|pgmock)(?:\[[^\]]*\])?",
    re.IGNORECASE,
)
_CLASSIFIER_PYTHON_RE = re.compile(r"Programming Language :: Python :: (3\.\d+)")
_TOX_PY_FACTOR_RE = re.compile(r"^(?:py)?(3)\.?(\d+)$", re.IGNORECASE)

_ROOT_INDICATORS = (
    "pyproject.toml",
    "requirements.txt",
    "Pipfile",
    "setup.py",
    "setup.cfg",
    ".python-version",
    "uv.lock",
    "poetry.lock",
)
_ROOT_PACKAGE_MANIFESTS = (
    "pyproject.toml",
    "requirements.txt",
    "Pipfile",
    "setup.py",
    "setup.cfg",
    "uv.lock",
    "poetry.lock",
)


def _join(base_dir: str, fname: str) -> str:
    return fname if base_dir == "." else f"{base_dir}/{fname}"


def _strip_python_mock_deps(deps_lower: str) -> tuple[str, list[str]]:
    """Strip mock service package references (including extras) from dependency text."""
    found_mocks = sorted({m.split("[")[0] for m in _MOCK_DEP_PATTERN.findall(deps_lower)})
    cleaned = _MOCK_DEP_PATTERN.sub("", deps_lower)
    return cleaned, found_mocks


def _extract_classifier_versions(data: Dict[str, Any]) -> List[str]:
    """
    Extract discrete Python 3.x minor versions from pyproject.toml Trove classifiers
    across `[project].classifiers` and `[tool.poetry].classifiers`, sorted numerically.
    """
    if not isinstance(data, dict):
        return []

    raw_classifiers: List[Any] = []
    project = data.get("project")
    if isinstance(project, dict) and isinstance(project.get("classifiers"), list):
        raw_classifiers.extend(project["classifiers"])

    tool = data.get("tool")
    if isinstance(tool, dict):
        poetry = tool.get("poetry")
        if isinstance(poetry, dict) and isinstance(poetry.get("classifiers"), list):
            raw_classifiers.extend(poetry["classifiers"])

    versions: Dict[Tuple[int, int], str] = {}
    for entry in raw_classifiers:
        if not isinstance(entry, str):
            continue
        match = _CLASSIFIER_PYTHON_RE.fullmatch(entry.strip())
        if match:
            ver = match.group(1)
            major_s, minor_s = ver.split(".", 1)
            versions[(int(major_s), int(minor_s))] = ver

    return [versions[k] for k in sorted(versions)]


def _split_tox_envlist_tokens(raw_envlist: str) -> List[str]:
    """Split tox envlist on commas, newlines, and whitespace outside {...} braces."""
    tokens: List[str] = []
    buf: List[str] = []
    depth = 0
    for line in raw_envlist.splitlines():
        cleaned_line = re.sub(r"(?:^|\s)#.*$", "", line)
        for ch in cleaned_line:
            if ch == "{":
                depth += 1
                buf.append(ch)
            elif ch == "}":
                depth = max(0, depth - 1)
                buf.append(ch)
            elif depth == 0 and (ch == "," or ch.isspace()):
                tok = "".join(buf).strip()
                if tok:
                    tokens.append(tok)
                buf = []
            else:
                buf.append(ch)
        if depth == 0:
            tok = "".join(buf).strip()
            if tok:
                tokens.append(tok)
            buf = []
    tail = "".join(buf).strip()
    if tail:
        tokens.append(tail)
    return tokens


def _expand_tox_braces(token: str, max_results: int = 128) -> List[str]:
    """Expand brace factor expressions like `py{310,311,312}-django{42,50}` safely."""
    results = [token]
    while True:
        next_results: List[str] = []
        expanded_any = False
        for item in results:
            match = re.search(r"\{([^{}]+)\}", item)
            if not match:
                next_results.append(item)
                continue
            expanded_any = True
            prefix = item[: match.start()]
            suffix = item[match.end() :]
            for alt in match.group(1).split(","):
                next_results.append(f"{prefix}{alt.strip()}{suffix}")
                if len(next_results) >= max_results:
                    break
            if len(next_results) >= max_results:
                break
        results = next_results
        if not expanded_any or len(results) >= max_results:
            break
    return results


def _extract_tox_versions(content: str) -> List[str]:
    """
    Parse tox.ini `[tox]` `envlist` / `env_list` using ConfigParser(interpolation=None),
    expanding brace factor expressions and extracting sorted Python 3.x versions.
    """
    if not content or not content.strip():
        return []

    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(content)
    except Exception:
        return []

    if not parser.has_section("tox"):
        return []

    raw_envlist = parser.get("tox", "envlist", fallback=None) or parser.get("tox", "env_list", fallback=None)
    if not raw_envlist:
        return []

    versions: Dict[Tuple[int, int], str] = {}
    for token in _split_tox_envlist_tokens(raw_envlist):
        for expanded in _expand_tox_braces(token):
            for factor in re.split(r"[-_]", expanded):
                match = _TOX_PY_FACTOR_RE.fullmatch(factor.strip())
                if match:
                    major, minor = int(match.group(1)), int(match.group(2))
                    versions[(major, minor)] = f"{major}.{minor}"

    return [versions[k] for k in sorted(versions)]


def _has_root_python(indexer: RepoIndexer, py_sub_dirs: Sequence[str]) -> bool:
    if any(indexer.has_file(f) for f in _ROOT_PACKAGE_MANIFESTS):
        return True
    if not py_sub_dirs:
        return any(indexer.has_file(f) for f in _ROOT_INDICATORS) or bool(indexer.find_files("*.py"))

    for py_file in indexer.find_files("*.py"):
        if any(py_file == d or py_file.startswith(f"{d}/") for d in py_sub_dirs):
            continue
        top = py_file.split("/", 1)[0].lower() if "/" in py_file else ""
        if top and top in NON_PACKAGE_DIRS:
            continue
        return True
    return False


class PythonDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "Python"

    def detect(self, indexer: RepoIndexer) -> bool:
        if any(indexer.has_file(f) for f in _ROOT_INDICATORS):
            return True
        if discover_monorepo_topology(indexer).packages_by_lang.get("python"):
            return True
        return bool(indexer.find_files("*.py"))

    def _detect_root_lockfile(self, indexer: RepoIndexer) -> Optional[Tuple[str, str, str]]:
        if indexer.has_file("uv.lock"):
            return ("uv", "uv sync --frozen", "uv.lock")
        if indexer.has_file("poetry.lock"):
            return ("poetry", "poetry install --no-interaction", "poetry.lock")
        if indexer.has_file("Pipfile.lock"):
            return ("pipenv", "pipenv install --deploy", "Pipfile.lock")
        if indexer.has_file("Pipfile"):
            return ("pipenv", "pipenv install --deploy", "Pipfile")
        return None

    def _analyze_python_dir(
        self,
        indexer: RepoIndexer,
        context: ProjectContext,
        base_dir: str,
        add_language_ctx: bool = True,
        *,
        add_monorepo_pkg: Optional[bool] = None,
        is_workspace_root: Optional[bool] = None,
        root_version: Optional[Tuple[str, str]] = None,
        root_lockfile: Optional[Tuple[str, str, str]] = None,
    ) -> LanguageContext:
        pkg_path = None if base_dir == "." else base_dir
        pyproject_path = _join(base_dir, "pyproject.toml")
        pyproject_content = (indexer.read_text(pyproject_path) or "") if indexer.has_file(pyproject_path) else ""
        pyproject_data: Dict[str, Any] = {}
        if pyproject_content:
            try:
                parsed = tomllib.loads(pyproject_content)
                if isinstance(parsed, dict):
                    pyproject_data = parsed
            except Exception:
                pyproject_data = {}

        # 1. Determine Runtime Version
        runtime_version = "3.12"
        version_source = "default"

        py_ver_path = _join(base_dir, ".python-version")
        tool_ver_path = _join(base_dir, ".tool-versions")
        if indexer.has_file(py_ver_path):
            raw = indexer.read_text(py_ver_path) or ""
            match = re.search(r"(\d+\.\d+)", raw.strip())
            if match:
                runtime_version = match.group(1)
                version_source = ".python-version"
        elif indexer.has_file(tool_ver_path):
            raw = indexer.read_text(tool_ver_path) or ""
            match = re.search(r"python\s+(\d+\.\d+)", raw)
            if match:
                runtime_version = match.group(1)
                version_source = ".tool-versions"
        elif pyproject_data:
            req_python = (
                pyproject_data.get("project", {}).get("requires-python")
                if isinstance(pyproject_data.get("project"), dict)
                else None
            ) or (
                pyproject_data.get("tool", {}).get("poetry", {}).get("dependencies", {}).get("python")
                if isinstance(pyproject_data.get("tool"), dict)
                and isinstance(pyproject_data.get("tool", {}).get("poetry"), dict)
                and isinstance(pyproject_data.get("tool", {}).get("poetry", {}).get("dependencies"), dict)
                else None
            )
            if req_python:
                match = re.search(r"(\d+\.\d+)", str(req_python))
                if match:
                    runtime_version = match.group(1)
                    version_source = "pyproject.toml"

        if version_source == "default" and base_dir != "." and root_version and root_version[1] != "default":
            runtime_version, version_source = root_version

        # Extract discrete matrix_versions unconditionally even when .python-version/.tool-versions exists
        classifier_versions = _extract_classifier_versions(pyproject_data) if pyproject_data else []
        tox_path = _join(base_dir, "tox.ini")
        tox_versions = _extract_tox_versions(indexer.read_text(tox_path) or "") if indexer.has_file(tox_path) else []

        matrix_versions: List[str] = []
        if len(classifier_versions) >= 2:
            matrix_versions = classifier_versions
            if version_source == "default":
                runtime_version = matrix_versions[-1]
                version_source = "pyproject.toml"
        elif len(tox_versions) >= 2:
            matrix_versions = tox_versions
            if version_source == "default":
                runtime_version = matrix_versions[-1]
                version_source = "tox.ini"

        scope_label = f" in {base_dir}" if base_dir != "." else ""
        context.add_explain(f"Detected Python {runtime_version}{scope_label} (via {version_source})")
        if matrix_versions:
            context.add_explain(f"Detected Python matrix versions{scope_label}: {matrix_versions}")

        # 2. Package Manager, Lockfile, and cache_dependency_path
        package_manager = "pip"
        install_cmd = ""
        cache_dependency_path: Optional[str] = None

        uv_lock = _join(base_dir, "uv.lock")
        poetry_lock = _join(base_dir, "poetry.lock")
        pipfile_lock = _join(base_dir, "Pipfile.lock")
        pipfile = _join(base_dir, "Pipfile")
        req_txt = _join(base_dir, "requirements.txt")
        req_dev_txt = _join(base_dir, "requirements-dev.txt")

        if indexer.has_file(uv_lock):
            package_manager = "uv"
            install_cmd = "uv sync --frozen"
            cache_dependency_path = uv_lock
            context.add_explain(f"Detected Package Manager: uv (via {uv_lock})")
        elif indexer.has_file(poetry_lock):
            package_manager = "poetry"
            install_cmd = "poetry install --no-interaction"
            cache_dependency_path = poetry_lock
            context.add_explain(f"Detected Package Manager: poetry (via {poetry_lock})")
        elif indexer.has_file(pipfile_lock) or indexer.has_file(pipfile):
            package_manager = "pipenv"
            install_cmd = "pipenv install --deploy"
            cache_dependency_path = pipfile_lock if indexer.has_file(pipfile_lock) else pipfile
            context.add_explain(f"Detected Package Manager: pipenv (via {pipfile})")
        elif indexer.has_file(req_txt):
            package_manager = "pip"
            install_cmd = "pip install -r requirements.txt"
            if indexer.has_file(req_dev_txt):
                install_cmd += " -r requirements-dev.txt"
            cache_dependency_path = req_txt
            context.add_explain(f"Detected Package Manager: pip (via {req_txt})")
        elif base_dir != "." and root_lockfile is not None:
            package_manager, install_cmd, cache_dependency_path = root_lockfile
            context.add_explain(f"Inherited workspace Package Manager{scope_label}: {package_manager} (via {cache_dependency_path})")
        elif indexer.has_file(pyproject_path):
            package_manager = "pip"
            install_cmd = "pip install -e ."
            opt_deps = (
                pyproject_data.get("project", {}).get("optional-dependencies", {})
                if isinstance(pyproject_data.get("project"), dict)
                else {}
            )
            if isinstance(opt_deps, dict):
                if "dev" in opt_deps:
                    install_cmd = "pip install -e '.[dev]'"
                elif "test" in opt_deps:
                    install_cmd = "pip install -e '.[test]'"
                elif opt_deps:
                    first_opt = next(iter(opt_deps.keys()))
                    install_cmd = f"pip install -e '.[{first_opt}]'"
            context.add_explain(f"Detected Package Manager: pip (via {pyproject_path}, cmd: {install_cmd})")

        # 3. Framework & Dependency Scanning
        framework: Optional[str] = None
        deps_text = ""
        for fn in ["pyproject.toml", "requirements.txt", "Pipfile", "setup.py"]:
            c = indexer.read_text(_join(base_dir, fn))
            if c:
                deps_text += "\n" + c

        deps_lower = deps_text.lower()
        tests_prefix = "tests/" if base_dir == "." else f"{base_dir}/tests/"
        has_tests_dir = indexer.has_file(_join(base_dir, "tests")) or any(
            f.startswith(tests_prefix) for f in indexer.files
        )

        if not install_cmd:
            install_cmd = "python -m pip install --upgrade pip"
            if "pytest" in deps_lower or has_tests_dir:
                install_cmd += " pytest"
            context.add_explain(f"No lockfile or manifest found{scope_label}; using minimal pip setup")

        # Prefix commands for isolated lockfile managers
        cmd_prefix = ""
        if package_manager == "uv":
            cmd_prefix = "uv run "
        elif package_manager == "poetry":
            cmd_prefix = "poetry run "

        if "fastapi" in deps_lower:
            framework = "FastAPI"
        elif "streamlit" in deps_lower:
            framework = "Streamlit"
        elif "django" in deps_lower:
            framework = "Django"
        elif "flask" in deps_lower:
            framework = "Flask"

        if framework:
            context.add_explain(f"Detected Framework{scope_label}: {framework}")

        # 4. Test Runner & Linter
        test_cmd = "pytest"
        if "pytest" in deps_lower or indexer.has_file(_join(base_dir, "pytest.ini")) or has_tests_dir or "[tool.pytest" in deps_text:
            test_cmd = "pytest"
            context.add_explain(f"Detected Test Runner{scope_label}: pytest")
        elif "django" in deps_lower and indexer.has_file(_join(base_dir, "manage.py")):
            test_cmd = "python manage.py test"
            context.add_explain(f"Detected Test Runner{scope_label}: django manage.py test")
        else:
            test_cmd = "python -m unittest discover"

        lint_cmd = None
        if "ruff" in deps_lower or "[tool.ruff" in deps_text or indexer.has_file(_join(base_dir, "ruff.toml")):
            lint_cmd = "ruff check ."
            context.add_explain(f"Detected Linter{scope_label}: ruff")
        elif "flake8" in deps_lower:
            lint_cmd = "flake8 ."
            context.add_explain(f"Detected Linter{scope_label}: flake8")

        if test_cmd:
            test_cmd = f"{cmd_prefix}{test_cmd}"
        if lint_cmd:
            lint_cmd = f"{cmd_prefix}{lint_cmd}"

        # 5. Service Container Inference from dependencies (excluding purely mock packages)
        deps_clean, found_mocks = _strip_python_mock_deps(deps_lower)
        service_source = "python dependencies" if base_dir == "." else f"{base_dir}/python dependencies"

        has_real_postgres = any(
            db in deps_clean for db in ["psycopg2", "asyncpg", "postgresql", "pgvector"]
        )
        if has_real_postgres:
            if not any(s.name == "postgres" and s.package_path == pkg_path for s in context.services):
                context.services.append(
                    ServiceRequirement(
                        name="postgres",
                        image="postgres:16-alpine",
                        ports=[5432],
                        env={
                            "POSTGRES_USER": "test_user",
                            "POSTGRES_PASSWORD": "test_password",
                            "POSTGRES_DB": "test_db",
                        },
                        source_file=service_source,
                        package_path=pkg_path,
                    )
                )
                context.add_explain(f"Inferred Backing Service{scope_label}: PostgreSQL 16 (via python postgres client)")
        elif any(m in {"testing.postgresql", "testing-postgresql", "testing_postgresql", "pgmock"} for m in found_mocks):
            context.add_explain(f"Filtered mock postgres dependency from backing services{scope_label}")

        has_real_redis = any(r in deps_clean for r in ["redis", "aioredis", "celery"])
        if has_real_redis:
            if not any(s.name == "redis" and s.package_path == pkg_path for s in context.services):
                context.services.append(
                    ServiceRequirement(
                        name="redis",
                        image="redis:7-alpine",
                        ports=[6379],
                        env={},
                        source_file=service_source,
                        package_path=pkg_path,
                    )
                )
                context.add_explain(f"Inferred Backing Service{scope_label}: Redis 7 (via python redis client/celery)")
        elif any(m in {"fakeredis", "mockredispy"} for m in found_mocks):
            context.add_explain(f"Filtered mock redis dependency from backing services{scope_label}")

        lang_ctx = LanguageContext(
            language="python",
            runtime_version=runtime_version,
            version_source=version_source,
            package_manager=package_manager,
            install_cmd=install_cmd,
            test_cmd=test_cmd,
            lint_cmd=lint_cmd,
            working_dir=base_dir,
            framework=framework,
            confidence=0.98 if version_source != "default" else 0.85,
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
                    language="python",
                    package_manager=package_manager,
                    runtime_version=runtime_version,
                    version_source=version_source,
                    install_cmd=install_cmd,
                    build_cmd=None,
                    test_cmd=test_cmd,
                    lint_cmd=lint_cmd,
                    framework=framework,
                    cache_dependency_path=cache_dependency_path,
                    matrix_versions=list(matrix_versions),
                )
            )

        return lang_ctx

    def analyze(self, indexer: RepoIndexer, context: ProjectContext) -> None:
        context.add_explain("Analyzing Python ecosystem...")

        topo = discover_monorepo_topology(indexer)
        py_sub_dirs = topo.packages_by_lang.get("python", [])
        if topo.is_monorepo:
            context.is_monorepo = True

        has_root = _has_root_python(indexer, py_sub_dirs)
        root_lockfile = self._detect_root_lockfile(indexer)

        # Resolve optional root .python-version / .tool-versions even when no root package exists
        root_version: Optional[Tuple[str, str]] = None
        if indexer.has_file(".python-version"):
            raw = indexer.read_text(".python-version") or ""
            match = re.search(r"(\d+\.\d+)", raw.strip())
            if match:
                root_version = (match.group(1), ".python-version")
        elif indexer.has_file(".tool-versions"):
            raw = indexer.read_text(".tool-versions") or ""
            match = re.search(r"python\s+(\d+\.\d+)", raw)
            if match:
                root_version = (match.group(1), ".tool-versions")

        if has_root:
            root_ctx = self._analyze_python_dir(
                indexer,
                context,
                ".",
                add_language_ctx=True,
                add_monorepo_pkg=False,
                is_workspace_root=False,
            )
            if root_version is None:
                root_version = (root_ctx.runtime_version, root_ctx.version_source)
            for sub_dir in py_sub_dirs:
                self._analyze_python_dir(
                    indexer,
                    context,
                    sub_dir,
                    add_language_ctx=False,
                    add_monorepo_pkg=True,
                    root_version=root_version,
                    root_lockfile=root_lockfile,
                )
        else:
            for idx, sub_dir in enumerate(py_sub_dirs):
                self._analyze_python_dir(
                    indexer,
                    context,
                    sub_dir,
                    add_language_ctx=(idx == 0),
                    add_monorepo_pkg=True,
                    is_workspace_root=None,
                    root_version=root_version,
                    root_lockfile=root_lockfile,
                )

