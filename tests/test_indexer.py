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


def test_nested_gitignore_scoping_and_sibling_isolation(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()

    # Root .gitignore: ignores *.log globally and directory-level exclusions
    (repo / ".gitignore").write_text(
        "*.log\nroot_ignored/\nsecret_dir/\n",
        encoding="utf-8",
    )
    (repo / "root.log").write_text("root log", encoding="utf-8")
    (repo / "root_ignored").mkdir()
    (repo / "root_ignored" / "x.py").write_text("x = 1", encoding="utf-8")

    # Sibling 1: apps/web with nested .gitignore
    web = repo / "apps" / "web"
    (web / "local_build").mkdir(parents=True)
    (web / "local_build" / "bundle.js").write_text("bundle", encoding="utf-8")
    (web / "src").mkdir(parents=True)
    (web / "src" / "index.ts").write_text("export {}", encoding="utf-8")
    (web / "src" / "app.gen.js").write_text("gen", encoding="utf-8")
    (web / "web_root_only.txt").write_text("root only", encoding="utf-8")
    (web / "src" / "web_root_only.txt").write_text("nested kept", encoding="utf-8")
    (web / "keep.log").write_text("keep me", encoding="utf-8")
    (web / "other.log").write_text("ignore me", encoding="utf-8")
    (web / "secret_dir").mkdir()
    (web / "secret_dir" / "token.txt").write_text("secret", encoding="utf-8")
    (web / ".gitignore").write_text(
        "local_build/\n*.gen.js\n/web_root_only.txt\n!keep.log\n!secret_dir/token.txt\n",
        encoding="utf-8",
    )

    # Sibling 2: apps/api without local .gitignore rules from apps/web
    api = repo / "apps" / "api"
    (api / "local_build").mkdir(parents=True)
    (api / "local_build" / "server.py").write_text("print('ok')", encoding="utf-8")
    (api / "schema.gen.js").write_text("export {}", encoding="utf-8")
    (api / "web_root_only.txt").write_text("api kept", encoding="utf-8")
    (api / "keep.log").write_text("ignored by root *.log", encoding="utf-8")

    # Outside symlinked directory must not be traversed (followlinks=False)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.py").write_text("SECRET = 1", encoding="utf-8")
    (repo / "apps" / "escape_link").symlink_to(outside, target_is_directory=True)

    indexer = RepoIndexer(repo)

    # Indexed files
    assert indexer.has_file("apps/web/src/index.ts")
    assert indexer.has_file("apps/web/src/web_root_only.txt")
    assert indexer.has_file("apps/web/keep.log")
    assert indexer.has_file("apps/api/local_build/server.py")
    assert indexer.has_file("apps/api/schema.gen.js")
    assert indexer.has_file("apps/api/web_root_only.txt")

    # Ignored files (root + nested + parent dir exclusion + symlink escape)
    assert not indexer.has_file("root.log")
    assert not indexer.has_file("root_ignored/x.py")
    assert not indexer.has_file("apps/web/local_build/bundle.js")
    assert not indexer.has_file("apps/web/src/app.gen.js")
    assert not indexer.has_file("apps/web/web_root_only.txt")
    assert not indexer.has_file("apps/web/other.log")
    assert not indexer.has_file("apps/web/secret_dir/token.txt")
    assert not indexer.has_file("apps/api/keep.log")
    assert not indexer.has_file("apps/escape_link/leak.py")


def test_max_file_size_guard_skips_oversized_and_allows_empty(tmp_path: Path, monkeypatch):
    from heurix.core.indexer import MAX_FILE_SIZE_BYTES

    assert MAX_FILE_SIZE_BYTES == 1_048_576

    (tmp_path / "empty.txt").write_bytes(b"")
    (tmp_path / "exact.txt").write_bytes(b"a" * MAX_FILE_SIZE_BYTES)
    (tmp_path / "oversized.txt").write_bytes(b"b" * (MAX_FILE_SIZE_BYTES + 1))

    indexer = RepoIndexer(tmp_path)

    # Empty and exact-threshold files are indexed, read, and cached
    assert indexer.has_file("empty.txt")
    assert indexer.has_file("exact.txt")
    assert indexer.has_file("oversized.txt")

    assert indexer.read_text("empty.txt") == ""
    assert "empty.txt" in indexer._content_cache

    exact_content = indexer.read_text("exact.txt")
    assert exact_content is not None
    assert len(exact_content) == MAX_FILE_SIZE_BYTES
    assert "exact.txt" in indexer._content_cache

    # Oversized file must be rejected by stat().st_size BEFORE calling Path.read_text
    orig_read_text = Path.read_text
    read_calls: list[str] = []

    def tracked_read_text(self_path: Path, *args, **kwargs):
        read_calls.append(self_path.name)
        return orig_read_text(self_path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracked_read_text)

    assert indexer.read_text("oversized.txt") is None
    assert "oversized.txt" not in indexer._content_cache
    assert "oversized.txt" not in read_calls

    # Keyword override works while preserving single-arg API
    (tmp_path / "small_ok.txt").write_bytes(b"x" * 100)
    (tmp_path / "small_big.txt").write_bytes(b"y" * 101)
    custom = RepoIndexer(tmp_path, max_file_size_bytes=100)
    assert custom.read_text("small_ok.txt") == "x" * 100
    assert custom.read_text("small_big.txt") is None


def test_lru_cache_eviction_by_count_and_bytes(tmp_path: Path):
    from collections import OrderedDict
    from heurix.core.indexer import MAX_CACHE_BYTES, MAX_CACHE_ENTRIES

    assert MAX_CACHE_ENTRIES == 512
    assert MAX_CACHE_BYTES == 32 * 1024 * 1024

    for name, data in [
        ("a.txt", "alpha"),
        ("b.txt", "bravo"),
        ("c.txt", "charlie"),
        ("d.txt", "delta"),
    ]:
        (tmp_path / name).write_text(data, encoding="utf-8")

    # 1. Entry-count LRU eviction + hit promotion
    idx_count = RepoIndexer(tmp_path, max_cache_entries=3, max_cache_bytes=1024)
    assert isinstance(idx_count._content_cache, OrderedDict)

    assert idx_count.read_text("a.txt") == "alpha"
    assert idx_count.read_text("b.txt") == "bravo"
    assert idx_count.read_text("c.txt") == "charlie"
    # Promote a.txt so b.txt becomes least-recently-used
    assert idx_count.read_text("a.txt") == "alpha"
    assert list(idx_count._content_cache.keys()) == ["b.txt", "c.txt", "a.txt"]

    # Inserting d.txt evicts b.txt
    assert idx_count.read_text("d.txt") == "delta"
    assert list(idx_count._content_cache.keys()) == ["c.txt", "a.txt", "d.txt"]
    assert "b.txt" not in idx_count._content_cache

    # 2. Byte-ceiling LRU eviction + UTF-8 byte tracking
    (tmp_path / "f1.txt").write_text("0123456789", encoding="utf-8")  # 10 bytes
    (tmp_path / "f2.txt").write_text("abcdefghij", encoding="utf-8")  # 10 bytes
    (tmp_path / "f3.txt").write_text("€" * 4, encoding="utf-8")       # 4 chars = 12 UTF-8 bytes
    (tmp_path / "un_cacheable.txt").write_text("z" * 30, encoding="utf-8")  # > 25B cache budget

    idx_bytes = RepoIndexer(tmp_path, max_cache_entries=10, max_cache_bytes=25)
    assert idx_bytes.read_text("f1.txt") == "0123456789"
    assert idx_bytes.read_text("f2.txt") == "abcdefghij"
    # Promote f1.txt so f2.txt is LRU
    assert idx_bytes.read_text("f1.txt") == "0123456789"
    assert idx_bytes._cache_bytes == 20

    # Reading 12-byte f3.txt exceeds 25 bytes (20 + 12 = 32), evicting f2.txt (leaving 10 + 12 = 22)
    assert idx_bytes.read_text("f3.txt") == "€" * 4
    assert list(idx_bytes._content_cache.keys()) == ["f1.txt", "f3.txt"]
    assert "f2.txt" not in idx_bytes._content_cache
    assert idx_bytes._cache_bytes == 22

    # File within max_file_size_bytes but larger than max_cache_bytes is read without caching or evicting
    assert idx_bytes.read_text("un_cacheable.txt") == "z" * 30
    assert "un_cacheable.txt" not in idx_bytes._content_cache
    assert list(idx_bytes._content_cache.keys()) == ["f1.txt", "f3.txt"]
    assert idx_bytes._cache_bytes == 22


def test_nested_gitignore_negation_over_default_and_deep_hierarchy(tmp_path: Path):
    # Root .gitignore negates a file inside DEFAULT_IGNORE_DIRS ("build") via build/* + !build/version.txt
    # while deep package .gitignore files override and re-ignore across 3 levels.
    (tmp_path / ".gitignore").write_text(
        "*.tmp\n*.log\nbuild/*\n!build/version.txt\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='mono'\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('root')\n", encoding="utf-8")

    (tmp_path / "build" / "sub").mkdir(parents=True)
    (tmp_path / "build" / "version.txt").write_text("1.2.3\n", encoding="utf-8")
    (tmp_path / "build" / "bundle.js").write_text("console.log(1);\n", encoding="utf-8")
    (tmp_path / "build" / "sub" / "ignored.ts").write_text("export const a = 1;\n", encoding="utf-8")

    # Intermediate packages/.gitignore re-includes keep.log and ignores *.bak
    packages = tmp_path / "packages"
    packages.mkdir()
    (packages / ".gitignore").write_text("!keep.log\n*.bak\n", encoding="utf-8")

    # Deep child packages/web: re-ignores keep.log, re-includes special.tmp,
    # and negates dist/manifest.json without dist/* in local .gitignore
    web = packages / "web"
    (web / "dist").mkdir(parents=True)
    (web / ".gitignore").write_text("keep.log\n!special.tmp\n!dist/manifest.json\n", encoding="utf-8")
    (web / "package.json").write_text('{"name":"web"}', encoding="utf-8")
    (web / "index.ts").write_text("export const web = true;\n", encoding="utf-8")
    (web / "keep.log").write_text("re-ignored by web\n", encoding="utf-8")
    (web / "special.tmp").write_text("kept by web\n", encoding="utf-8")
    (web / "other.bak").write_text("ignored by packages\n", encoding="utf-8")
    (web / "dist" / "manifest.json").write_text('{"ok":true}', encoding="utf-8")
    (web / "dist" / "chunk.js").write_text("console.log('ignored');\n", encoding="utf-8")

    # Sibling packages/api: inherits packages/.gitignore, unaffected by packages/web/.gitignore
    api = packages / "api"
    (api / "dist").mkdir(parents=True)
    (api / "build").mkdir(parents=True)
    (api / "app.py").write_text("print('api')\n", encoding="utf-8")
    (api / "keep.log").write_text("kept by packages\n", encoding="utf-8")
    (api / "special.tmp").write_text("ignored by root\n", encoding="utf-8")
    (api / "dist" / "manifest.json").write_text('{"ignored":true}', encoding="utf-8")
    (api / "build" / "artifact.ts").write_text("export const x = 0;\n", encoding="utf-8")

    indexer = RepoIndexer(tmp_path)

    # Default dir negation & deep hierarchy expectations
    assert indexer.has_file("build/version.txt")
    assert not indexer.has_file("build/bundle.js")
    assert not indexer.has_file("build/sub/ignored.ts")
    assert not indexer.has_file("packages/api/build/artifact.ts")

    assert indexer.has_file("packages/web/special.tmp")
    assert indexer.has_file("packages/web/dist/manifest.json")
    assert not indexer.has_file("packages/web/keep.log")
    assert not indexer.has_file("packages/web/other.bak")
    assert not indexer.has_file("packages/web/dist/chunk.js")

    assert indexer.has_file("packages/api/keep.log")
    assert not indexer.has_file("packages/api/special.tmp")
    assert not indexer.has_file("packages/api/dist/manifest.json")

    # Language metrics must ignore build/dist artifacts and keep root-only MANIFEST_WEIGHT
    metrics = indexer.get_language_metrics()
    assert metrics["python"]["file_count"] == 2  # main.py + packages/api/app.py
    assert metrics["python"]["has_root_manifest"] is True
    assert metrics["python"]["score"] == 12
    assert metrics["node"]["file_count"] == 1  # packages/web/index.ts only (build/dist JS/TS excluded)
    assert metrics["node"]["has_root_manifest"] is False
    assert metrics["node"]["score"] == 1


def test_indexing_benchmark_under_50ms(tmp_path: Path):
    import time

    (tmp_path / ".gitignore").write_text("*.log\n.DS_Store\n", encoding="utf-8")

    # Construct 40 packages x 150 kept files (6,000+ indexed) + 2,000 ignored files in dist/node_modules/local_build
    for pkg_i in range(40):
        pkg = tmp_path / "packages" / f"pkg_{pkg_i}"
        (pkg / "src").mkdir(parents=True)
        (pkg / "dist").mkdir(parents=True)
        (pkg / "node_modules").mkdir(parents=True)
        (pkg / "local_build").mkdir(parents=True)

        if pkg_i % 4 == 0:
            (pkg / ".gitignore").write_text("local_build/\n!keep.log\n", encoding="utf-8")
        else:
            (pkg / ".gitignore").write_text("local_build/\n", encoding="utf-8")

        (pkg / "keep.log").write_text("log", encoding="utf-8")
        for f_i in range(150):
            (pkg / "src" / f"mod_{f_i}.ts").write_text("export const x = 1;\n", encoding="utf-8")
        for d_i in range(20):
            (pkg / "dist" / f"out_{d_i}.js").write_text("ignored", encoding="utf-8")
            (pkg / "local_build" / f"tmp_{d_i}.js").write_text("ignored", encoding="utf-8")
        for n_i in range(10):
            (pkg / "node_modules" / f"dep_{n_i}.js").write_text("ignored", encoding="utf-8")

    timings_ms = []
    indexer = None
    for _ in range(3):
        t0 = time.perf_counter()
        indexer = RepoIndexer(tmp_path)
        timings_ms.append((time.perf_counter() - t0) * 1000.0)

    assert indexer is not None
    best_ms = min(timings_ms)
    assert best_ms < 50.0, f"Expected indexing <50ms, got {timings_ms}"

    # Verify deterministic sorted output and accurate inclusions/exclusions
    assert len(indexer.files) >= 6000
    assert indexer.files == sorted(indexer.files)
    assert indexer.has_file("packages/pkg_0/keep.log")
    assert not indexer.has_file("packages/pkg_1/keep.log")
    assert not indexer.has_file("packages/pkg_0/dist/out_0.js")
    assert not indexer.has_file("packages/pkg_0/local_build/tmp_0.js")
    assert not indexer.has_file("packages/pkg_0/node_modules/dep_0.js")




