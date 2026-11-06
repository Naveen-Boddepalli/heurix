"""
Node.js / TypeScript Ecosystem Detector.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional
from heurix.core.context import LanguageContext, MonorepoPackage, ProjectContext, ServiceRequirement
from heurix.core.indexer import RepoIndexer
from heurix.detectors.base import BaseDetector


class NodeDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "Node"

    def detect(self, indexer: RepoIndexer) -> bool:
        indicators = ["package.json", ".nvmrc", ".node-version", "pnpm-lock.yaml", "yarn.lock", "bun.lockb"]
        return any(indexer.has_file(f) for f in indicators)

    def analyze(self, indexer: RepoIndexer, context: ProjectContext) -> None:
        context.add_explain("Analyzing Node.js / JavaScript / TypeScript ecosystem...")

        # 1. Determine Node Version
        node_version = "20.x"
        version_source = "default"

        if indexer.has_file(".nvmrc"):
            raw = (indexer.read_text(".nvmrc") or "").strip().lstrip("v")
            match = re.search(r"^(\d+)", raw)
            if match:
                node_version = f"{match.group(1)}.x"
                version_source = ".nvmrc"
        elif indexer.has_file(".node-version"):
            raw = (indexer.read_text(".node-version") or "").strip().lstrip("v")
            match = re.search(r"^(\d+)", raw)
            if match:
                node_version = f"{match.group(1)}.x"
                version_source = ".node-version"

        # 2. Parse Root package.json
        pkg_data: Dict[str, Any] = {}
        if indexer.has_file("package.json"):
            try:
                content = indexer.read_text("package.json") or "{}"
                pkg_data = json.loads(content)
            except Exception:
                pass

        if version_source == "default" and "engines" in pkg_data:
            node_engine = pkg_data.get("engines", {}).get("node")
            if node_engine:
                match = re.search(r"(\d+)", str(node_engine))
                if match:
                    node_version = f"{match.group(1)}.x"
                    version_source = "package.json (engines)"

        context.add_explain(f"Detected Node.js {node_version} (via {version_source})")

        # 3. Determine Package Manager & Lockfile
        package_manager = "npm"
        install_cmd = "npm ci"

        if indexer.has_file("pnpm-lock.yaml"):
            package_manager = "pnpm"
            install_cmd = "pnpm i --frozen-lockfile"
            context.add_explain("Detected Package Manager: pnpm (via pnpm-lock.yaml)")
        elif indexer.has_file("yarn.lock"):
            package_manager = "yarn"
            install_cmd = "yarn install --frozen-lockfile"
            context.add_explain("Detected Package Manager: yarn (via yarn.lock)")
        elif indexer.has_file("bun.lockb") or indexer.has_file("bun.lock"):
            package_manager = "bun"
            install_cmd = "bun install --frozen-lockfile"
            context.add_explain("Detected Package Manager: bun (via bun.lock)")
        elif indexer.has_file("package-lock.json"):
            package_manager = "npm"
            install_cmd = "npm ci"
            context.add_explain("Detected Package Manager: npm (via package-lock.json)")
        else:
            install_cmd = "npm install"
            context.add_explain("Detected Package Manager: npm")

        # 4. Check for Monorepo & Workspaces
        is_monorepo = False
        if indexer.has_file("pnpm-workspace.yaml"):
            is_monorepo = True
            context.is_monorepo = True
            context.add_explain("Detected Monorepo Topology: pnpm-workspace.yaml")
        elif indexer.has_file("turbo.json"):
            is_monorepo = True
            context.is_monorepo = True
            context.add_explain("Detected Monorepo Topology: Turborepo (turbo.json)")
        elif indexer.has_file("nx.json"):
            is_monorepo = True
            context.is_monorepo = True
            context.add_explain("Detected Monorepo Topology: Nx (nx.json)")
        elif "workspaces" in pkg_data:
            is_monorepo = True
            context.is_monorepo = True
            context.add_explain("Detected Monorepo Topology: npm/yarn workspaces")

        # Sub-packages in monorepo
        if is_monorepo:
            all_pkgs = indexer.find_by_name("package.json")
            for p in all_pkgs:
                if p != "package.json":
                    sub_dir = p.rsplit("/", 1)[0]
                    context.monorepo_packages.append(
                        MonorepoPackage(
                            name=sub_dir,
                            path=sub_dir,
                            language="node",
                            package_manager=package_manager,
                        )
                    )

        # 5. Scripts: test, build, lint
        scripts = pkg_data.get("scripts", {})
        test_cmd: Optional[str] = None
        if "test" in scripts:
            test_val = scripts["test"]
            if "no test specified" not in test_val.lower():
                test_cmd = f"{package_manager} test" if package_manager != "npm" else "npm test"
                context.add_explain(f"Detected Test Script: '{test_val}' (via package.json)")

        build_cmd: Optional[str] = None
        if "build" in scripts:
            build_cmd = f"{package_manager} run build" if package_manager != "npm" else "npm run build"
            context.add_explain("Detected Build Script: 'build' (via package.json)")

        lint_cmd: Optional[str] = None
        if "lint" in scripts:
            lint_cmd = f"{package_manager} run lint" if package_manager != "npm" else "npm run lint"
            context.add_explain("Detected Linter Script: 'lint' (via package.json)")

        # 6. Framework Detection & Backing Services
        deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
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
            context.add_explain(f"Detected Framework: {framework}")

        # Service Container Inference
        if any(k in deps for k in ["pg", "pg-pool", "typeorm", "prisma", "@prisma/client"]):
            if not any(s.name == "postgres" for s in context.services):
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
                        source_file="package.json dependencies",
                    )
                )
                context.add_explain("Inferred Backing Service: PostgreSQL 16 (via node pg/prisma)")

        if any(k in deps for k in ["redis", "ioredis"]):
            if not any(s.name == "redis" for s in context.services):
                context.services.append(
                    ServiceRequirement(
                        name="redis",
                        image="redis:7-alpine",
                        ports=[6379],
                        env={},
                        source_file="package.json dependencies",
                    )
                )
                context.add_explain("Inferred Backing Service: Redis 7 (via node redis/ioredis)")

        if any(k in deps for k in ["mongodb", "mongoose"]):
            if not any(s.name == "mongodb" for s in context.services):
                context.services.append(
                    ServiceRequirement(
                        name="mongodb",
                        image="mongo:6",
                        ports=[27017],
                        env={},
                        source_file="package.json dependencies",
                    )
                )
                context.add_explain("Inferred Backing Service: MongoDB 6 (via mongoose/mongodb)")

        context.languages.append(
            LanguageContext(
                language="node",
                runtime_version=node_version,
                version_source=version_source,
                package_manager=package_manager,
                install_cmd=install_cmd,
                build_cmd=build_cmd,
                test_cmd=test_cmd,
                lint_cmd=lint_cmd,
                framework=framework,
                confidence=0.95,
            )
        )
