"""
Tests for extended IR models and monorepo workspace topology discovery.
"""

from __future__ import annotations

from pathlib import Path

from heurix.core.context import (
    LanguageContext,
    MonorepoPackage,
    ProjectContext,
    ServiceRequirement,
)
from heurix.core.indexer import RepoIndexer
from heurix.core.monorepo import (
    ECOSYSTEM_MANIFESTS,
    NON_PACKAGE_DIRS,
    PREFERRED_CONTAINER_GROUPS,
    MonorepoTopology,
    compile_workspace_glob,
    discover_monorepo_topology,
    match_workspace_globs,
    normalize_workspace_pattern,
    parse_cargo_workspace,
    parse_go_work,
    parse_package_json_workspaces,
    parse_pnpm_workspace,
)


def test_ir_monorepo_package_backward_compat_and_extended_fields():
    # Legacy 4-argument construction must still succeed without new fields
    legacy_pkg = MonorepoPackage(
        name="apps/web",
        path="apps/web",
        language="node",
        package_manager="pnpm",
    )
    assert legacy_pkg.runtime_version == ""
    assert legacy_pkg.version_source == ""
    assert legacy_pkg.install_cmd is None
    assert legacy_pkg.build_cmd is None
    assert legacy_pkg.test_cmd is None
    assert legacy_pkg.lint_cmd is None
    assert legacy_pkg.framework is None
    assert legacy_pkg.cache_dependency_path is None
    assert legacy_pkg.matrix_versions == []

    # Extended construction and Pydantic JSON round-trip
    rich_pkg = MonorepoPackage(
        name="services/api",
        path="services/api",
        language="python",
        package_manager="uv",
        runtime_version="3.12",
        version_source="pyproject.toml",
        install_cmd="uv sync --frozen",
        build_cmd=None,
        test_cmd="uv run pytest",
        lint_cmd="uv run ruff check .",
        framework="FastAPI",
        cache_dependency_path="services/api/uv.lock",
        matrix_versions=["3.11", "3.12"],
    )
    dumped = rich_pkg.model_dump()
    restored = MonorepoPackage.model_validate(dumped)
    assert restored == rich_pkg
    assert restored.cache_dependency_path == "services/api/uv.lock"
    assert restored.matrix_versions == ["3.11", "3.12"]


def test_ir_language_context_and_service_requirement_extensions():
    svc_global = ServiceRequirement(
        name="postgres",
        image="postgres:16-alpine",
        ports=[5432],
        source_file="docker-compose.yml",
    )
    svc_scoped = ServiceRequirement(
        name="redis",
        image="redis:7-alpine",
        ports=[6379],
        source_file="services/api/pyproject.toml",
        package_path="services/api",
    )
    assert svc_global.package_path is None
    assert svc_scoped.package_path == "services/api"

    lang_default = LanguageContext(
        language="node",
        runtime_version="20.x",
        version_source=".nvmrc",
        package_manager="pnpm",
        install_cmd="pnpm i --frozen-lockfile",
    )
    assert lang_default.matrix_versions == []
    assert lang_default.cache_dependency_path is None
    assert lang_default.is_workspace_root is None

    lang_ws = LanguageContext(
        language="node",
        runtime_version="20.x",
        version_source="package.json",
        package_manager="pnpm",
        install_cmd="pnpm i --frozen-lockfile",
        working_dir=".",
        matrix_versions=["18.x", "20.x"],
        cache_dependency_path="pnpm-lock.yaml",
        is_workspace_root=True,
    )
    assert lang_ws.is_workspace_root is True
    assert lang_ws.matrix_versions == ["18.x", "20.x"]
    assert lang_ws.cache_dependency_path == "pnpm-lock.yaml"


def test_ir_project_context_matrix_os_and_get_languages():
    py_api = LanguageContext(
        language="python",
        runtime_version="3.12",
        version_source="pyproject.toml",
        package_manager="uv",
        install_cmd="uv sync --frozen",
        working_dir="services/api",
    )
    py_worker = LanguageContext(
        language="python",
        runtime_version="3.11",
        version_source=".python-version",
        package_manager="poetry",
        install_cmd="poetry install",
        working_dir="services/worker",
    )
    node_web = LanguageContext(
        language="node",
        runtime_version="20.x",
        version_source=".nvmrc",
        package_manager="pnpm",
        install_cmd="pnpm i --frozen-lockfile",
        working_dir="apps/web",
    )

    ctx = ProjectContext(
        repo_name="poly",
        repo_root="/tmp/poly",
        languages=[py_api, node_web, py_worker],
        matrix_os=["ubuntu-latest", "macos-latest"],
    )
    assert ctx.matrix_os == ["ubuntu-latest", "macos-latest"]
    assert ctx.get_language("python") == py_api
    assert ctx.get_languages("Python") == [py_api, py_worker]
    assert ctx.get_languages("node") == [node_web]
    assert ctx.get_languages("rust") == []

    # Serialization round-trip preserves new fields
    json_str = ctx.model_dump_json()
    rehydrated = ProjectContext.model_validate_json(json_str)
    assert rehydrated.matrix_os == ["ubuntu-latest", "macos-latest"]
    assert len(rehydrated.get_languages("python")) == 2


def test_glob_normalize_workspace_pattern_and_dotdir_preservation():
    assert normalize_workspace_pattern("  ./apps/*  ") == "apps/*"
    assert normalize_workspace_pattern("././packages/**/") == "packages/**"
    assert normalize_workspace_pattern(".\\apps\\web\\") == "apps/web"
    # Critical: must NOT strip leading '.' from hidden config dirs like '.config/*'
    assert normalize_workspace_pattern(".config/*") == ".config/*"
    assert normalize_workspace_pattern("./.config/*") == ".config/*"
    assert normalize_workspace_pattern("!./apps/legacy/") == "!apps/legacy"
    assert normalize_workspace_pattern(".") == "."
    assert normalize_workspace_pattern("./") == "."

    # Path traversal and leading slashes must be rejected
    assert normalize_workspace_pattern("../outside") == ""
    assert normalize_workspace_pattern("apps/../../etc") == ""
    assert normalize_workspace_pattern("/etc/passwd") == ""
    assert normalize_workspace_pattern("!../outside") == ""
    assert normalize_workspace_pattern("!/abs/path") == ""
    assert normalize_workspace_pattern("") == ""
    assert normalize_workspace_pattern("   ") == ""


def test_glob_segment_matching_and_recursive_starstar():
    # Single-segment '*' must NOT match deeper nested paths (unlike fnmatch)
    pat_apps = compile_workspace_glob("apps/*")
    assert pat_apps.match("apps/web") is not None
    assert pat_apps.match("apps/api") is not None
    assert pat_apps.match("apps/web/examples/demo") is None
    assert pat_apps.match("apps") is None

    # Recursive '**' handles 0, 1, or more nested segments
    assert match_workspace_globs("packages/core", ["packages/**"]) is True
    assert match_workspace_globs("packages/ui/button", ["packages/**"]) is True
    assert match_workspace_globs("apps/web/src", ["apps/**/src"]) is True
    assert match_workspace_globs("apps/src", ["apps/**/src"]) is True
    assert match_workspace_globs("apps/web/src/deep", ["apps/**/src"]) is False

    # '?' matches a single non-slash char
    assert match_workspace_globs("apps/v1", ["apps/v?"]) is True
    assert match_workspace_globs("apps/v12", ["apps/v?"]) is False
    assert match_workspace_globs("apps/v/", ["apps/v?"]) is False

    # Special regex chars in folder names are escaped safely
    assert match_workspace_globs("packages/@scope/core", ["packages/@scope/*"]) is True
    assert match_workspace_globs("packages/v1.0", ["packages/v1.0"]) is True
    assert match_workspace_globs("packages/v1X0", ["packages/v1.0"]) is False


def test_glob_dotfile_guard_and_ordered_negation():
    patterns = ["./apps/*", "packages/**", "!**/test/**", ".config/*"]

    # Dotfiles/dotdirs skipped when segment starts with '*' or '?'
    assert match_workspace_globs("apps/.cache", patterns) is False
    assert match_workspace_globs("apps/.env", ["apps/?nv"]) is False
    # Explicit leading dot directory is preserved and matched
    assert match_workspace_globs(".config/eslint", patterns) is True
    assert match_workspace_globs(".config/.hidden", patterns) is False

    # Ordered negation: '**/test/**' excludes test dirs but keeps 'testing'
    assert match_workspace_globs("packages/testing", patterns) is True
    assert match_workspace_globs("packages/test", patterns) is False
    assert match_workspace_globs("packages/test/unit", patterns) is False
    assert match_workspace_globs("apps/web", patterns) is True
    assert match_workspace_globs("apps/web/examples/demo", patterns) is False

    # Last match wins when a later positive pattern re-includes an excluded item
    re_included = ["packages/**", "!packages/legacy", "packages/legacy"]
    assert match_workspace_globs("packages/legacy", re_included) is True


def test_glob_exclude_patterns_and_traversal_rejection():
    # Explicit exclude_patterns (e.g. Cargo [workspace].exclude) remove matches
    assert (
        match_workspace_globs(
            "crates/core",
            ["crates/*"],
            exclude_patterns=["crates/ignored"],
        )
        is True
    )
    assert (
        match_workspace_globs(
            "crates/ignored",
            ["crates/*"],
            exclude_patterns=["crates/ignored"],
        )
        is False
    )
    assert (
        match_workspace_globs(
            "crates/ignored/sub",
            ["crates/**"],
            exclude_patterns=["crates/ignored"],
        )
        is False
    )
    assert (
        match_workspace_globs(
            "crates/ignored2",
            ["crates/*"],
            exclude_patterns=["crates/ignored"],
        )
        is True
    )

    # Traversal candidate paths never match
    assert match_workspace_globs("../outside", ["**"]) is False
    assert match_workspace_globs("/etc/passwd", ["**"]) is False


def test_parser_pnpm_workspace_yaml():
    yaml_content = """
packages:
  - './apps/*'
  - "packages/**"
  - '!**/test/**'
  - '.config/*'
  - '../escape'
  - '/abs/escape'
"""
    parsed = parse_pnpm_workspace(yaml_content)
    assert parsed == ["apps/*", "packages/**", "!**/test/**", ".config/*"]

    assert parse_pnpm_workspace("") == []
    assert parse_pnpm_workspace("packages: not-a-list\n") == []
    assert parse_pnpm_workspace(":::invalid yaml:::") == []


def test_parser_package_json_workspaces_list_and_yarn_object():
    npm_pkg = '{"name": "root", "workspaces": ["./apps/*", "packages/*", "!packages/fixtures", "../bad"]}'
    assert parse_package_json_workspaces(npm_pkg) == ["apps/*", "packages/*", "!packages/fixtures"]

    yarn_pkg = (
        '{"name": "yarn-root", "workspaces": {"packages": ["./apps/*", "libs/**"], "nohoist": ["**/react-native"]}}'
    )
    assert parse_package_json_workspaces(yarn_pkg) == ["apps/*", "libs/**"]

    assert parse_package_json_workspaces('{"name": "single"}') == []
    assert parse_package_json_workspaces("{not json") == []


def test_parser_cargo_workspace_members_exclude_and_virtual():
    virtual_cargo = """
[workspace]
resolver = "2"
members = [
    "./crates/*",
    "services/*",
    "../outside",
]
exclude = [
    "crates/bench",
    "examples/**",
]
"""
    members, exclude, has_pkg = parse_cargo_workspace(virtual_cargo)
    assert members == ["crates/*", "services/*"]
    assert exclude == ["crates/bench", "examples/**"]
    assert has_pkg is False

    hybrid_cargo = """
[package]
name = "root-cli"
version = "0.1.0"

[workspace]
members = ["crates/*"]
"""
    members2, exclude2, has_pkg2 = parse_cargo_workspace(hybrid_cargo)
    assert members2 == ["crates/*"]
    assert exclude2 == []
    assert has_pkg2 is True

    assert parse_cargo_workspace("not valid = toml [") == ([], [], False)


def test_parser_go_work_directives_comments_and_traversal_rejection():
    go_work = """
go 1.22

// single-line and inline comments
use ./services/gateway // api gateway

use (
    "./services/billing"
    `./pkg/shared`
    .
    // ./disabled
    ../outside-repo
    /etc/passwd
    ./apps/../../escape
)

replace example.com/mod => ../local-mod
"""
    modules = parse_go_work(go_work)
    assert modules == [
        "services/gateway",
        "services/billing",
        "pkg/shared",
        ".",
    ]

    inline_go_work = 'go 1.22\nuse ( "./cmd/api" ./pkg/core )\n'
    assert parse_go_work(inline_go_work) == ["cmd/api", "pkg/core"]


def _write(base: Path, rel: str, content: str = "") -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_discover_explicit_pnpm_workspace_with_exclusions_and_deep_glob(tmp_path: Path):
    _write(
        tmp_path,
        "pnpm-workspace.yaml",
        "packages:\n  - './apps/*'\n  - 'packages/**'\n  - '!**/test/**'\n  - 'examples/demo'\n",
    )
    _write(tmp_path, "package.json", '{"name": "root", "private": true}')
    _write(tmp_path, "apps/web/package.json", '{"name": "web"}')
    _write(tmp_path, "apps/.cache/package.json", '{"name": "cache"}')
    _write(tmp_path, "apps/web/examples/nested/package.json", '{"name": "nested"}')
    _write(tmp_path, "packages/ui/button/package.json", '{"name": "button"}')
    _write(tmp_path, "packages/test/unit/package.json", '{"name": "test-unit"}')
    _write(tmp_path, "examples/demo/package.json", '{"name": "explicit-demo"}')
    # Unlisted Node package must NOT leak when explicit pnpm-workspace.yaml is present
    _write(tmp_path, "site/package.json", '{"name": "docs-site"}')

    topo = discover_monorepo_topology(RepoIndexer(tmp_path))
    assert isinstance(topo, MonorepoTopology)
    assert topo.is_monorepo is True
    assert topo.has_workspace_config is True
    assert "pnpm" in topo.workspace_kinds
    assert topo.packages_by_lang == {
        "node": ["apps/web", "examples/demo", "packages/ui/button"]
    }
    assert topo.all_packages == [
        ("apps/web", "node"),
        ("examples/demo", "node"),
        ("packages/ui/button", "node"),
    ]


def test_discover_package_json_workspaces_and_turbo_nx(tmp_path: Path):
    # Yarn Classic object workspaces + turbo.json
    _write(tmp_path, "turbo.json", '{"pipeline": {}}')
    _write(
        tmp_path,
        "package.json",
        '{"name": "root", "workspaces": {"packages": ["apps/*", "!apps/legacy"]}}',
    )
    _write(tmp_path, "apps/portal/package.json", '{"name": "portal"}')
    _write(tmp_path, "apps/legacy/package.json", '{"name": "legacy"}')

    topo = discover_monorepo_topology(RepoIndexer(tmp_path))
    assert topo.is_monorepo is True
    assert topo.has_workspace_config is True
    assert "turbo" in topo.workspace_kinds
    assert topo.packages_by_lang == {"node": ["apps/portal"]}

    # Standalone nx.json without package.json#workspaces falls back to 1-2 level heuristic
    nx_root = tmp_path / "nx_only"
    _write(nx_root, "nx.json", "{}")
    _write(nx_root, "apps/admin/package.json", '{"name": "admin"}')
    _write(nx_root, "site/package.json", '{"name": "docs-site"}')

    nx_topo = discover_monorepo_topology(RepoIndexer(nx_root))
    assert nx_topo.is_monorepo is True
    assert nx_topo.has_workspace_config is True
    assert "nx" in nx_topo.workspace_kinds
    assert nx_topo.packages_by_lang == {"node": ["apps/admin"]}


def test_discover_cargo_workspace_members_and_exclude(tmp_path: Path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[workspace]\nmembers = ["crates/*"]\nexclude = ["crates/ignored"]\n',
    )
    _write(tmp_path, "crates/core/Cargo.toml", '[package]\nname = "core"\nversion = "0.1.0"\n')
    _write(tmp_path, "crates/cli/Cargo.toml", '[package]\nname = "cli"\nversion = "0.1.0"\n')
    _write(tmp_path, "crates/ignored/Cargo.toml", '[package]\nname = "ignored"\nversion = "0.1.0"\n')

    topo = discover_monorepo_topology(RepoIndexer(tmp_path))
    assert topo.is_monorepo is True
    assert topo.has_workspace_config is True
    assert "cargo" in topo.workspace_kinds
    assert topo.packages_by_lang == {"rust": ["crates/cli", "crates/core"]}
    assert topo.all_packages == [("crates/cli", "rust"), ("crates/core", "rust")]


def test_discover_go_work_modules_and_traversal_guard(tmp_path: Path):
    _write(
        tmp_path,
        "go.work",
        """
go 1.22
use (
    .
    ./services/gateway // active module
    ./services/missing // no go.mod -> ignored
    ../outside
    /etc/passwd
)
""",
    )
    _write(tmp_path, "go.mod", "module example.com/root\n\ngo 1.22\n")
    _write(tmp_path, "services/gateway/go.mod", "module example.com/gateway\n\ngo 1.22\n")
    _write(tmp_path, "services/unused/go.mod", "module example.com/unused\n\ngo 1.22\n")

    topo = discover_monorepo_topology(RepoIndexer(tmp_path))
    assert topo.is_monorepo is True
    assert topo.has_workspace_config is True
    assert "go.work" in topo.workspace_kinds
    assert topo.packages_by_lang == {"go": ["services/gateway"]}
    assert "." not in topo.packages_by_lang.get("go", [])


def test_discover_polyglot_1_2_level_subtrees_and_dedup(tmp_path: Path):
    # Mixed polyglot monorepo without root workspace config: Node + Python + Go + Rust + C++
    _write(tmp_path, "apps/web/package.json", '{"name": "web"}')
    _write(tmp_path, "services/api/pyproject.toml", '[project]\nname = "api"\n')
    _write(tmp_path, "services/api/requirements.txt", "fastapi\n")  # deduped with pyproject.toml
    _write(tmp_path, "services/auth/go.mod", "module example.com/auth\n\ngo 1.22\n")
    _write(tmp_path, "crates/engine/Cargo.toml", '[package]\nname = "engine"\nversion = "0.1.0"\n')
    _write(tmp_path, "cpp-worker/CMakeLists.txt", "cmake_minimum_required(VERSION 3.20)\n")
    # Mixed directory with both Node and Python yields one entry per language
    _write(tmp_path, "tools/cli/package.json", '{"name": "cli"}')
    _write(tmp_path, "tools/cli/pyproject.toml", '[project]\nname = "cli"\n')

    topo = discover_monorepo_topology(RepoIndexer(tmp_path))
    assert topo.is_monorepo is True
    assert topo.has_workspace_config is False
    assert topo.workspace_kinds == []
    assert topo.packages_by_lang == {
        "cpp": ["cpp-worker"],
        "go": ["services/auth"],
        "node": ["apps/web", "tools/cli"],
        "python": ["services/api", "tools/cli"],
        "rust": ["crates/engine"],
    }
    assert topo.all_packages == sorted(
        [
            ("apps/web", "node"),
            ("cpp-worker", "cpp"),
            ("crates/engine", "rust"),
            ("services/api", "python"),
            ("services/auth", "go"),
            ("tools/cli", "node"),
            ("tools/cli", "python"),
        ]
    )


def test_discover_false_positive_suppression_docs_site_and_cmake(tmp_path: Path):
    # Simulate Heurix-like Python root repo with docs/, site/, tests/, scripts/, packaging/, src/
    _write(tmp_path, "pyproject.toml", '[project]\nname = "main-app"\n')
    _write(tmp_path, "src/main.py", "print('ok')\n")
    _write(tmp_path, "docs/conf.py", "project = 'docs'\n")
    _write(tmp_path, "docs/requirements.txt", "sphinx\n")
    _write(tmp_path, "requirements/dev.txt", "pytest\n")
    _write(tmp_path, "site/package.json", '{"name": "docs-site"}')
    _write(tmp_path, "examples/demo/package.json", '{"name": "demo"}')
    _write(tmp_path, "tests/fixtures/pyproject.toml", '[project]\nname = "fixture"\n')
    _write(tmp_path, "scripts/requirements.txt", "click\n")
    _write(tmp_path, "packaging/homebrew/package.json", '{"name": "brew"}')
    _write(tmp_path, ".github/actions/package.json", '{"name": "action"}')
    _write(tmp_path, "k8s/helm/requirements.txt", "pyyaml\n")

    assert {"docs", "site", "examples", "fixtures", "tests", "scripts", "requirements", ".github", "k8s", "packaging"}.issubset(
        NON_PACKAGE_DIRS
    )
    assert {"apps", "services", "packages", "crates", "libs", "modules"} == PREFERRED_CONTAINER_GROUPS
    assert set(ECOSYSTEM_MANIFESTS.keys()) == {"node", "python", "rust", "go", "cpp"}

    topo = discover_monorepo_topology(RepoIndexer(tmp_path))
    assert topo.is_monorepo is False
    assert topo.all_packages == []
    assert topo.packages_by_lang == {}

    # Root CMake project with internal add_subdirectory CMakeLists must NOT become a monorepo
    cmake_root = tmp_path / "cmake_app"
    _write(cmake_root, "CMakeLists.txt", "project(app)\nadd_subdirectory(src)\n")
    _write(cmake_root, "src/CMakeLists.txt", "add_library(core lib.cpp)\n")
    _write(cmake_root, "include/CMakeLists.txt", "target_include_directories(core INTERFACE .)\n")
    cmake_topo = discover_monorepo_topology(RepoIndexer(cmake_root))
    assert cmake_topo.is_monorepo is False
    assert cmake_topo.all_packages == []

    # CMake subdir inside PREFERRED_CONTAINER_GROUPS or with independent conanfile IS discovered
    cmake_mono = tmp_path / "cmake_mono"
    _write(cmake_mono, "CMakeLists.txt", "project(mono)\n")
    _write(cmake_mono, "services/engine/CMakeLists.txt", "project(engine)\n")
    _write(cmake_mono, "standalone/CMakeLists.txt", "project(standalone)\n")
    _write(cmake_mono, "standalone/conanfile.txt", "[requires]\nfmt/10.0.0\n")
    cmake_mono_topo = discover_monorepo_topology(RepoIndexer(cmake_mono))
    assert cmake_mono_topo.is_monorepo is True
    assert cmake_mono_topo.packages_by_lang == {"cpp": ["services/engine", "standalone"]}


def test_discover_requirements_txt_py_neighbor_and_preferred_group_rules(tmp_path: Path):
    # misc/requirements.txt without any .py file -> ignored
    _write(tmp_path, "misc/requirements.txt", "ansible\n")
    # worker/requirements.txt WITH worker/app.py -> discovered
    _write(tmp_path, "worker/requirements.txt", "celery\n")
    _write(tmp_path, "worker/app.py", "print('worker')\n")
    # services/ml/requirements.txt under preferred group 'services/' even without .py -> discovered
    _write(tmp_path, "services/ml/requirements.txt", "torch\n")

    topo = discover_monorepo_topology(RepoIndexer(tmp_path))
    assert topo.packages_by_lang == {"python": ["services/ml", "worker"]}
    assert topo.is_monorepo is True


def test_discover_is_monorepo_boundary_conditions_and_determinism(tmp_path: Path):
    # 1. Single sub-package with NO root manifest -> is_monorepo is False
    sub_only = tmp_path / "sub_only"
    _write(sub_only, "README.md", "# Nested single app\n")
    _write(sub_only, "backend/pyproject.toml", '[project]\nname = "backend"\n')
    topo_sub = discover_monorepo_topology(RepoIndexer(sub_only))
    assert topo_sub.packages_by_lang == {"python": ["backend"]}
    assert topo_sub.is_monorepo is False

    # 2. Root manifest + 1 sub-package -> is_monorepo is True
    hybrid = tmp_path / "hybrid"
    _write(hybrid, "pyproject.toml", '[project]\nname = "api"\n')
    _write(hybrid, "frontend/package.json", '{"name": "web"}')
    topo_hybrid = discover_monorepo_topology(RepoIndexer(hybrid))
    assert topo_hybrid.packages_by_lang == {"node": ["frontend"]}
    assert topo_hybrid.is_monorepo is True

    # 3. Root pnpm-workspace.yaml with no subdirs yet -> is_monorepo is True
    ws_empty = tmp_path / "ws_empty"
    _write(ws_empty, "pnpm-workspace.yaml", "packages:\n  - 'apps/*'\n")
    _write(ws_empty, "package.json", '{"name": "root"}')
    topo_ws = discover_monorepo_topology(RepoIndexer(ws_empty))
    assert topo_ws.has_workspace_config is True
    assert topo_ws.is_monorepo is True
    assert topo_ws.all_packages == []

