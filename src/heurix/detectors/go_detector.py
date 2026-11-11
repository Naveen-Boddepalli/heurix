"""
Go Language Ecosystem Detector.
"""

from __future__ import annotations

import re
from typing import Optional, Sequence
from heurix.core.context import LanguageContext, MonorepoPackage, ProjectContext
from heurix.core.indexer import RepoIndexer
from heurix.core.monorepo import NON_PACKAGE_DIRS, discover_monorepo_topology, parse_go_work
from heurix.detectors.base import BaseDetector


def _join(base_dir: str, fname: str) -> str:
    return fname if base_dir == "." else f"{base_dir}/{fname}"


def _has_root_go(indexer: RepoIndexer, go_sub_dirs: Sequence[str]) -> bool:
    if indexer.has_file("go.mod"):
        return True
    if indexer.has_file("go.work"):
        return False
    if not go_sub_dirs:
        return bool(indexer.find_files("*.go"))

    for go_file in indexer.find_files("*.go"):
        if any(go_file == d or go_file.startswith(f"{d}/") for d in go_sub_dirs):
            continue
        top = go_file.split("/", 1)[0].lower() if "/" in go_file else ""
        if top and top in NON_PACKAGE_DIRS:
            continue
        return True
    return False


class GoDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "Go"

    def detect(self, indexer: RepoIndexer) -> bool:
        if indexer.has_file("go.mod") or indexer.has_file("go.work") or bool(indexer.find_files("*.go")):
            return True
        return bool(discover_monorepo_topology(indexer).packages_by_lang.get("go"))

    def _analyze_go_dir(
        self,
        indexer: RepoIndexer,
        context: ProjectContext,
        base_dir: str,
        *,
        default_version: str = "1.22",
        default_source: str = "default",
        add_language_ctx: bool = True,
        add_monorepo_pkg: bool = False,
        is_workspace_root: Optional[bool] = None,
    ) -> LanguageContext:
        scope_label = f" in {base_dir}" if base_dir != "." else ""
        go_version = default_version
        version_source = default_source

        go_mod_path = _join(base_dir, "go.mod")
        go_mod_content = ""
        if indexer.has_file(go_mod_path):
            go_mod_content = indexer.read_text(go_mod_path) or ""
            match = re.search(r"^go\s+([0-9]+(?:\.[0-9]+)?)", go_mod_content, re.MULTILINE)
            if match:
                go_version = match.group(1)
                version_source = "go.mod"

        context.add_explain(f"Detected Go version{scope_label}: {go_version} (via {version_source})")

        framework: Optional[str] = None
        if "github.com/gin-gonic/gin" in go_mod_content:
            framework = "Gin"
        elif "github.com/labstack/echo" in go_mod_content:
            framework = "Echo"
        elif "github.com/gofiber/fiber" in go_mod_content:
            framework = "Fiber"

        if framework:
            context.add_explain(f"Detected Framework{scope_label}: {framework}")

        go_sum_path = _join(base_dir, "go.sum")
        cache_dependency_path = go_sum_path if indexer.has_file(go_sum_path) else None

        lang_ctx = LanguageContext(
            language="go",
            runtime_version=go_version,
            version_source=version_source,
            package_manager="gomod",
            install_cmd="go mod download",
            build_cmd="go build -v ./...",
            test_cmd="go test -v -race -cover ./...",
            lint_cmd="golangci-lint run",
            working_dir=base_dir,
            framework=framework,
            confidence=0.95,
            cache_dependency_path=cache_dependency_path,
            is_workspace_root=is_workspace_root,
        )

        if add_language_ctx:
            context.languages.append(lang_ctx)

        if add_monorepo_pkg:
            context.monorepo_packages.append(
                MonorepoPackage(
                    name=base_dir,
                    path=base_dir,
                    language="go",
                    package_manager="gomod",
                    runtime_version=go_version,
                    version_source=version_source,
                    install_cmd="go mod download",
                    build_cmd="go build -v ./...",
                    test_cmd="go test -v -race -cover ./...",
                    lint_cmd="golangci-lint run",
                    framework=framework,
                    cache_dependency_path=cache_dependency_path,
                )
            )

        return lang_ctx

    def analyze(self, indexer: RepoIndexer, context: ProjectContext) -> None:
        context.add_explain("Analyzing Go ecosystem...")

        topo = discover_monorepo_topology(indexer)
        go_sub_dirs = topo.packages_by_lang.get("go", [])
        if topo.is_monorepo:
            context.is_monorepo = True

        if indexer.has_file("go.work"):
            context.is_monorepo = True
            work_content = indexer.read_text("go.work") or ""
            work_dirs = parse_go_work(work_content)
            work_version = "1.22"
            work_source = "default"
            work_match = re.search(r"^go\s+([0-9]+(?:\.[0-9]+)?)", work_content, re.MULTILINE)
            if work_match:
                work_version = work_match.group(1)
                work_source = "go.work"

            context.add_explain(f"Detected Go workspace (go.work) with {len(work_dirs)} use directive(s)")

            root_is_active = indexer.has_file("go.mod") and ("." in work_dirs or not go_sub_dirs)
            if root_is_active:
                self._analyze_go_dir(
                    indexer,
                    context,
                    ".",
                    default_version=work_version,
                    default_source=work_source,
                    add_language_ctx=True,
                    add_monorepo_pkg=False,
                    is_workspace_root=False,
                )
            else:
                context.add_explain(f"Detected Go version: {work_version} (via {work_source})")
                context.languages.append(
                    LanguageContext(
                        language="go",
                        runtime_version=work_version,
                        version_source=work_source,
                        package_manager="gomod",
                        install_cmd="go mod download",
                        build_cmd="go build -v ./...",
                        test_cmd="go test -v -race -cover ./...",
                        lint_cmd="golangci-lint run",
                        working_dir=".",
                        confidence=0.95,
                        is_workspace_root=bool(go_sub_dirs),
                    )
                )

            for sub_dir in go_sub_dirs:
                self._analyze_go_dir(
                    indexer,
                    context,
                    sub_dir,
                    default_version=work_version,
                    default_source=work_source,
                    add_language_ctx=False,
                    add_monorepo_pkg=True,
                )
            return

        if _has_root_go(indexer, go_sub_dirs):
            self._analyze_go_dir(
                indexer,
                context,
                ".",
                add_language_ctx=True,
                add_monorepo_pkg=False,
                is_workspace_root=False,
            )
            for sub_dir in go_sub_dirs:
                self._analyze_go_dir(
                    indexer,
                    context,
                    sub_dir,
                    add_language_ctx=False,
                    add_monorepo_pkg=True,
                )
        else:
            for idx, sub_dir in enumerate(go_sub_dirs):
                self._analyze_go_dir(
                    indexer,
                    context,
                    sub_dir,
                    add_language_ctx=(idx == 0),
                    add_monorepo_pkg=True,
                    is_workspace_root=None,
                )

