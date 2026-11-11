"""
Rust Language and Cargo Ecosystem Detector.
"""

from __future__ import annotations

import sys
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        import tomllib  # type: ignore
from heurix.core.context import LanguageContext, MonorepoPackage, ProjectContext
from heurix.core.indexer import RepoIndexer
from heurix.core.monorepo import discover_monorepo_topology, parse_cargo_workspace
from heurix.detectors.base import BaseDetector


def _join(base_dir: str, fname: str) -> str:
    return fname if base_dir == "." else f"{base_dir}/{fname}"


class RustDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "Rust"

    def detect(self, indexer: RepoIndexer) -> bool:
        if (
            indexer.has_file("Cargo.toml")
            or indexer.has_file("rust-toolchain.toml")
            or indexer.has_file("rust-toolchain")
        ):
            return True
        return bool(discover_monorepo_topology(indexer).packages_by_lang.get("rust"))

    def _analyze_rust_dir(
        self,
        indexer: RepoIndexer,
        context: ProjectContext,
        base_dir: str,
        default_version: str = "stable",
        default_source: str = "default",
        *,
        add_language_ctx: bool = True,
        add_monorepo_pkg: bool = False,
        is_workspace_root: Optional[bool] = None,
        root_lockfile: Optional[str] = None,
    ) -> LanguageContext:
        scope_label = f" in {base_dir}" if base_dir != "." else ""
        rust_version = "stable"
        version_source = "default"

        toolchain_toml = _join(base_dir, "rust-toolchain.toml")
        toolchain_txt = _join(base_dir, "rust-toolchain")
        if indexer.has_file(toolchain_toml):
            content = indexer.read_text(toolchain_toml) or ""
            try:
                data = tomllib.loads(content)
                ch = data.get("toolchain", {}).get("channel") if isinstance(data, dict) else None
                if ch:
                    rust_version = str(ch)
                    version_source = "rust-toolchain.toml"
            except Exception:
                pass
        elif indexer.has_file(toolchain_txt):
            val = (indexer.read_text(toolchain_txt) or "").strip()
            if val:
                rust_version = val
                version_source = "rust-toolchain"

        if version_source == "default" and base_dir != "." and default_source != "default":
            rust_version = default_version
            version_source = default_source

        context.add_explain(f"Detected Rust toolchain{scope_label}: {rust_version} (via {version_source})")

        framework: Optional[str] = None
        cargo_path = _join(base_dir, "Cargo.toml")
        cargo_content = indexer.read_text(cargo_path) or ""
        if "actix-web" in cargo_content:
            framework = "Actix-Web"
        elif "axum" in cargo_content:
            framework = "Axum"
        elif "rocket" in cargo_content:
            framework = "Rocket"

        if framework:
            context.add_explain(f"Detected Framework{scope_label}: {framework}")

        cargo_lock = _join(base_dir, "Cargo.lock")
        cache_dependency_path: Optional[str] = None
        if indexer.has_file(cargo_lock):
            cache_dependency_path = cargo_lock
        elif base_dir != "." and root_lockfile is not None:
            cache_dependency_path = root_lockfile

        lang_ctx = LanguageContext(
            language="rust",
            runtime_version=rust_version,
            version_source=version_source,
            package_manager="cargo",
            install_cmd="cargo fetch",
            build_cmd="cargo build --release",
            test_cmd="cargo test --verbose",
            lint_cmd="cargo clippy -- -D warnings",
            working_dir=base_dir,
            framework=framework,
            confidence=0.98,
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
                    language="rust",
                    package_manager="cargo",
                    runtime_version=rust_version,
                    version_source=version_source,
                    install_cmd="cargo fetch",
                    build_cmd="cargo build --release",
                    test_cmd="cargo test --verbose",
                    lint_cmd="cargo clippy -- -D warnings",
                    framework=framework,
                    cache_dependency_path=cache_dependency_path,
                )
            )

        return lang_ctx

    def analyze(self, indexer: RepoIndexer, context: ProjectContext) -> None:
        context.add_explain("Analyzing Rust ecosystem...")

        topo = discover_monorepo_topology(indexer)
        rust_sub_dirs = topo.packages_by_lang.get("rust", [])
        if topo.is_monorepo:
            context.is_monorepo = True

        root_lockfile = "Cargo.lock" if indexer.has_file("Cargo.lock") else None

        if indexer.has_file("Cargo.toml"):
            cargo_raw = indexer.read_text("Cargo.toml") or ""
            members, exclude, has_package = parse_cargo_workspace(cargo_raw)
            is_cargo_ws = "cargo" in topo.workspace_kinds or bool(members or exclude)
            if is_cargo_ws:
                context.is_monorepo = True
                context.add_explain("Detected Rust Cargo Workspace in Cargo.toml")

            if is_cargo_ws and rust_sub_dirs:
                if not has_package:
                    root_ctx = self._analyze_rust_dir(
                        indexer,
                        context,
                        ".",
                        add_language_ctx=True,
                        add_monorepo_pkg=False,
                        is_workspace_root=True,
                        root_lockfile=root_lockfile,
                    )
                else:
                    root_ctx = self._analyze_rust_dir(
                        indexer,
                        context,
                        ".",
                        add_language_ctx=True,
                        add_monorepo_pkg=True,
                        is_workspace_root=False,
                        root_lockfile=root_lockfile,
                    )
            else:
                root_ctx = self._analyze_rust_dir(
                    indexer,
                    context,
                    ".",
                    add_language_ctx=True,
                    add_monorepo_pkg=False,
                    is_workspace_root=False,
                    root_lockfile=root_lockfile,
                )

            for sub_dir in rust_sub_dirs:
                self._analyze_rust_dir(
                    indexer,
                    context,
                    sub_dir,
                    default_version=root_ctx.runtime_version,
                    default_source=root_ctx.version_source,
                    add_language_ctx=False,
                    add_monorepo_pkg=True,
                    root_lockfile=root_lockfile,
                )
            return

        # No root Cargo.toml: check optional root toolchain file alongside sub-crates or standalone toolchain
        default_version = "stable"
        default_source = "default"
        if indexer.has_file("rust-toolchain.toml") or indexer.has_file("rust-toolchain"):
            if not rust_sub_dirs:
                self._analyze_rust_dir(
                    indexer,
                    context,
                    ".",
                    add_language_ctx=True,
                    add_monorepo_pkg=False,
                    is_workspace_root=False,
                    root_lockfile=root_lockfile,
                )
                return
            probe = self._analyze_rust_dir(
                indexer,
                context,
                ".",
                add_language_ctx=False,
                add_monorepo_pkg=False,
            )
            default_version = probe.runtime_version
            default_source = probe.version_source

        for idx, sub_dir in enumerate(rust_sub_dirs):
            self._analyze_rust_dir(
                indexer,
                context,
                sub_dir,
                default_version=default_version,
                default_source=default_source,
                add_language_ctx=(idx == 0),
                add_monorepo_pkg=True,
                is_workspace_root=None,
                root_lockfile=root_lockfile,
            )

