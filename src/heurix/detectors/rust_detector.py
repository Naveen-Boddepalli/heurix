"""
Rust Language and Cargo Ecosystem Detector.
"""

from __future__ import annotations

import re
import tomllib
from heurix.core.context import LanguageContext, ProjectContext
from heurix.core.indexer import RepoIndexer
from heurix.detectors.base import BaseDetector


class RustDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "Rust"

    def detect(self, indexer: RepoIndexer) -> bool:
        return indexer.has_file("Cargo.toml") or indexer.has_file("rust-toolchain.toml")

    def analyze(self, indexer: RepoIndexer, context: ProjectContext) -> None:
        context.add_explain("Analyzing Rust ecosystem...")

        rust_version = "stable"
        version_source = "default"

        if indexer.has_file("rust-toolchain.toml"):
            content = indexer.read_text("rust-toolchain.toml") or ""
            try:
                data = tomllib.loads(content)
                ch = data.get("toolchain", {}).get("channel")
                if ch:
                    rust_version = str(ch)
                    version_source = "rust-toolchain.toml"
            except Exception:
                pass
        elif indexer.has_file("rust-toolchain"):
            val = (indexer.read_text("rust-toolchain") or "").strip()
            if val:
                rust_version = val
                version_source = "rust-toolchain"

        context.add_explain(f"Detected Rust toolchain: {rust_version} (via {version_source})")

        framework = None
        cargo_content = indexer.read_text("Cargo.toml") or ""
        if "actix-web" in cargo_content:
            framework = "Actix-Web"
        elif "axum" in cargo_content:
            framework = "Axum"
        elif "rocket" in cargo_content:
            framework = "Rocket"

        if framework:
            context.add_explain(f"Detected Framework: {framework}")

        context.languages.append(
            LanguageContext(
                language="rust",
                runtime_version=rust_version,
                version_source=version_source,
                package_manager="cargo",
                install_cmd="cargo fetch",
                build_cmd="cargo build --release",
                test_cmd="cargo test --verbose",
                lint_cmd="cargo clippy -- -D warnings",
                framework=framework,
                confidence=0.98,
            )
        )
