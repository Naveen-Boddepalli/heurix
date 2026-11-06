"""
Go Language Ecosystem Detector.
"""

from __future__ import annotations

import re
from heurix.core.context import LanguageContext, ProjectContext
from heurix.core.indexer import RepoIndexer
from heurix.detectors.base import BaseDetector


class GoDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "Go"

    def detect(self, indexer: RepoIndexer) -> bool:
        return indexer.has_file("go.mod") or bool(indexer.find_files("*.go"))

    def analyze(self, indexer: RepoIndexer, context: ProjectContext) -> None:
        context.add_explain("Analyzing Go ecosystem...")

        go_version = "1.22"
        version_source = "default"

        if indexer.has_file("go.mod"):
            content = indexer.read_text("go.mod") or ""
            match = re.search(r"^go\s+([0-9]+(?:\.[0-9]+)?)", content, re.MULTILINE)
            if match:
                go_version = match.group(1)
                version_source = "go.mod"

        context.add_explain(f"Detected Go version: {go_version} (via {version_source})")

        framework = None
        go_mod_content = indexer.read_text("go.mod") or ""
        if "github.com/gin-gonic/gin" in go_mod_content:
            framework = "Gin"
        elif "github.com/labstack/echo" in go_mod_content:
            framework = "Echo"
        elif "github.com/gofiber/fiber" in go_mod_content:
            framework = "Fiber"

        if framework:
            context.add_explain(f"Detected Framework: {framework}")

        context.languages.append(
            LanguageContext(
                language="go",
                runtime_version=go_version,
                version_source=version_source,
                package_manager="gomod",
                install_cmd="go mod download",
                build_cmd="go build -v ./...",
                test_cmd="go test -v -race -cover ./...",
                lint_cmd="golangci-lint run",
                framework=framework,
                confidence=0.95,
            )
        )
