"""
Tests for RepoIndexer.
"""

from __future__ import annotations

import os
from pathlib import Path
from heurix.core.indexer import RepoIndexer


def test_indexer_ignores_and_caches(tmp_path: Path):
    # Setup simulated directory
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "some_lib.py").write_text("dummy", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name": "root"}', encoding="utf-8")

    indexer = RepoIndexer(tmp_path)

    assert indexer.has_file("src/main.py")
    assert indexer.has_file("package.json")
    assert not indexer.has_file(".venv/some_lib.py")
    assert not indexer.has_file("node_modules/package.json")

    content = indexer.read_text("src/main.py")
    assert content == "print('hello')"

    # Check cache
    assert "src/main.py" in indexer._content_cache


def test_indexer_language_metrics_and_manifest_bonus(tmp_path: Path):
    # Polyglot files across ecosystems + ignored files that must NOT count
    (tmp_path / "pyproject.toml").write_text("[project]\nname='poly'\n", encoding="utf-8")
    (tmp_path / "script.py").write_text("print('hi')\n", encoding="utf-8")

    src = tmp_path / "src"
    src.mkdir()
    for i in range(5):
        (src / f"mod_{i}.ts").write_text("export const x = 1;\n", encoding="utf-8")
    (src / "helper.tsx").write_text("export const C = () => null;\n", encoding="utf-8")
    (src / "lib.rs").write_text("pub fn ok() {}\n", encoding="utf-8")
    (src / "main.go").write_text("package main\n", encoding="utf-8")
    (src / "util.cpp").write_text("int f() { return 0; }\n", encoding="utf-8")

    # Ignored directory containing many JS files must be excluded from scoring
    nm = tmp_path / "node_modules"
    nm.mkdir()
    for i in range(50):
        (nm / f"dep_{i}.js").write_text("module.exports = {};\n", encoding="utf-8")

    # Nested manifest in subdir must NOT receive root manifest bonus
    sub = tmp_path / "packages" / "web"
    sub.mkdir(parents=True)
    (sub / "package.json").write_text('{"name":"web"}', encoding="utf-8")

    indexer = RepoIndexer(tmp_path)
    metrics = indexer.get_language_metrics()
    scores = indexer.compute_language_scores()

    assert metrics["python"]["file_count"] == 1
    assert metrics["python"]["has_root_manifest"] is True
    assert scores["python"] == 11  # 1 file + 10 root manifest bonus

    assert metrics["node"]["file_count"] == 6  # 5 .ts + 1 .tsx (node_modules ignored)
    assert metrics["node"]["has_root_manifest"] is False
    assert scores["node"] == 6

    assert scores["rust"] == 1
    assert scores["go"] == 1
    assert scores["cpp"] == 1


def test_primary_language_polyglot_typescript_over_python(tmp_path: Path):
    from heurix.detectors import analyze_repository

    # Both root manifests exist; PythonDetector is registered before NodeDetector,
    # but 20 TypeScript files must outweigh 1 Python script.
    (tmp_path / "pyproject.toml").write_text("[project]\nname='app'\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name": "app"}', encoding="utf-8")

    ts_dir = tmp_path / "src"
    ts_dir.mkdir()
    for i in range(20):
        (ts_dir / f"file_{i}.ts").write_text(f"export const v{i} = {i};\n", encoding="utf-8")

    context = analyze_repository(tmp_path)
    assert context.has_language("python")
    assert context.has_language("node")
    primary = context.get_primary_language()
    assert primary is not None
    assert primary.language == "node"


def test_primary_language_deterministic_tie_breaking():
    from heurix.core.context import LanguageContext, ProjectContext

    py = LanguageContext(
        language="python",
        runtime_version="3.12",
        version_source="pyproject.toml",
        package_manager="pip",
        install_cmd="pip install -e .",
    )
    node = LanguageContext(
        language="node",
        runtime_version="20.x",
        version_source="package.json",
        package_manager="npm",
        install_cmd="npm ci",
    )
    go = LanguageContext(
        language="go",
        runtime_version="1.22",
        version_source="go.mod",
        package_manager="gomod",
        install_cmd="go mod download",
    )

    # Equal scores: alphabetical tie-breaker selects "go" over "node" over "python"
    ctx_scored = ProjectContext(
        repo_name="tie",
        repo_root="/tmp/tie",
        languages=[py, node, go],
        language_scores={"python": 12, "node": 12, "go": 12},
    )
    assert ctx_scored.get_primary_language().language == "go"

    # Reversed language order produces identical result
    ctx_reversed = ProjectContext(
        repo_name="tie",
        repo_root="/tmp/tie",
        languages=[node, py],
        language_scores={"python": 10, "node": 10},
    )
    assert ctx_reversed.get_primary_language().language == "node"

    # Fallback without language_scores uses confidence + alphabetical tie-break
    ctx_unscored = ProjectContext(
        repo_name="unscored",
        repo_root="/tmp/unscored",
        languages=[py, node],
    )
    assert ctx_unscored.get_primary_language().language == "node"


def test_project_context_secret_fields_sync():
    from heurix.core.context import ProjectContext

    ctx = ProjectContext(
        repo_name="sec",
        repo_root="/tmp/sec",
        test_secrets=["DATABASE_URL"],
        deployment_secrets=["VERCEL_TOKEN"],
    )
    assert ctx.test_secrets == ["DATABASE_URL"]
    assert ctx.deployment_secrets == ["VERCEL_TOKEN"]
    assert "DATABASE_URL" in ctx.required_secrets
    assert "VERCEL_TOKEN" in ctx.required_secrets

