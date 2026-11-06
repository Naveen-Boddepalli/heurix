"""
GitHub Actions CI/CD Workflow Synthesizer.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List
from ruamel.yaml import YAML
from heurix.core.context import ProjectContext
from heurix.synthesizers.base import BaseSynthesizer


class GitHubActionsSynthesizer(BaseSynthesizer):
    @property
    def name(self) -> str:
        return "GitHub Actions CI"

    def synthesize(self, context: ProjectContext) -> Dict[str, str]:
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)

        workflow: Dict[str, Any] = {
            "name": "CI",
            "on": {
                "push": {"branches": ["main", "master"]},
                "pull_request": {"branches": ["main", "master"]},
            },
            "jobs": {},
        }

        # If monorepo, add path filters
        if context.is_monorepo and context.monorepo_packages:
            workflow["on"]["push"]["paths"] = ["**"]
            workflow["on"]["pull_request"]["paths"] = ["**"]

        test_job: Dict[str, Any] = {
            "runs-on": "ubuntu-latest",
        }

        # Configure backing services (e.g. Postgres, Redis)
        if context.services:
            services_dict: Dict[str, Any] = {}
            for svc in context.services:
                svc_entry: Dict[str, Any] = {"image": svc.image}
                if svc.env:
                    svc_entry["env"] = dict(svc.env)
                if svc.ports:
                    svc_entry["ports"] = [f"{p}:{p}" for p in svc.ports]

                # Standard healthchecks
                if "postgres" in svc.name.lower() or "postgres" in svc.image.lower():
                    svc_entry["options"] = (
                        "--health-cmd pg_isready --health-interval 10s --health-timeout 5s --health-retries 5"
                    )
                elif "redis" in svc.name.lower() or "redis" in svc.image.lower():
                    svc_entry["options"] = (
                        '--health-cmd "redis-cli ping" --health-interval 10s --health-timeout 5s --health-retries 5'
                    )

                services_dict[svc.name.lower()] = svc_entry
            test_job["services"] = services_dict

        # Build job steps
        steps: List[Dict[str, Any]] = [
            {"name": "Checkout repository", "uses": "actions/checkout@v4"}
        ]

        # Step generators per language
        for lang in context.languages:
            if lang.language == "python":
                if lang.package_manager == "uv":
                    steps.append({
                        "name": "Install uv",
                        "uses": "astral-sh/setup-uv@v5",
                        "with": {"enable-cache": True},
                    })
                    steps.append({
                        "name": f"Set up Python {lang.runtime_version}",
                        "uses": "actions/setup-python@v5",
                        "with": {"python-version": lang.runtime_version},
                    })
                    steps.append({
                        "name": "Install dependencies",
                        "run": lang.install_cmd,
                    })
                elif lang.package_manager == "poetry":
                    steps.append({
                        "name": f"Set up Python {lang.runtime_version}",
                        "uses": "actions/setup-python@v5",
                        "with": {"python-version": lang.runtime_version, "cache": "poetry"},
                    })
                    steps.append({
                        "name": "Install Poetry",
                        "uses": "snok/install-poetry@v1",
                        "with": {"virtualenvs-create": True, "virtualenvs-in-project": True},
                    })
                    steps.append({
                        "name": "Install dependencies",
                        "run": lang.install_cmd,
                    })
                else:
                    steps.append({
                        "name": f"Set up Python {lang.runtime_version}",
                        "uses": "actions/setup-python@v5",
                        "with": {"python-version": lang.runtime_version, "cache": "pip"},
                    })
                    steps.append({
                        "name": "Install dependencies",
                        "run": lang.install_cmd,
                    })

            elif lang.language == "node":
                if lang.package_manager == "pnpm":
                    steps.append({
                        "name": "Install pnpm",
                        "uses": "pnpm/action-setup@v4",
                        "with": {"version": "9"},
                    })
                    steps.append({
                        "name": f"Set up Node.js {lang.runtime_version}",
                        "uses": "actions/setup-node@v4",
                        "with": {"node-version": lang.runtime_version, "cache": "pnpm"},
                    })
                    steps.append({
                        "name": "Install dependencies",
                        "run": lang.install_cmd,
                    })
                elif lang.package_manager == "yarn":
                    steps.append({
                        "name": f"Set up Node.js {lang.runtime_version}",
                        "uses": "actions/setup-node@v4",
                        "with": {"node-version": lang.runtime_version, "cache": "yarn"},
                    })
                    steps.append({
                        "name": "Install dependencies",
                        "run": lang.install_cmd,
                    })
                elif lang.package_manager == "bun":
                    steps.append({
                        "name": "Set up Bun",
                        "uses": "oven-sh/setup-bun@v2",
                        "with": {"bun-version": "latest"},
                    })
                    steps.append({
                        "name": "Install dependencies",
                        "run": lang.install_cmd,
                    })
                else:
                    steps.append({
                        "name": f"Set up Node.js {lang.runtime_version}",
                        "uses": "actions/setup-node@v4",
                        "with": {"node-version": lang.runtime_version, "cache": "npm"},
                    })
                    steps.append({
                        "name": "Install dependencies",
                        "run": lang.install_cmd,
                    })

            elif lang.language == "rust":
                steps.append({
                    "name": f"Set up Rust ({lang.runtime_version})",
                    "uses": "dtolnay/rust-toolchain@stable",
                })
                steps.append({
                    "name": "Rust Cache",
                    "uses": "Swatinem/rust-cache@v2",
                })

            elif lang.language == "go":
                steps.append({
                    "name": f"Set up Go {lang.runtime_version}",
                    "uses": "actions/setup-go@v5",
                    "with": {"go-version": lang.runtime_version, "cache": True},
                })
                steps.append({
                    "name": "Download Go dependencies",
                    "run": lang.install_cmd,
                })

            elif lang.language == "cpp":
                steps.append({
                    "name": "Install build tools (CMake, Ninja)",
                    "run": "sudo apt-get update && sudo apt-get install -y cmake ninja-build build-essential",
                })

            # Lint step
            if lang.lint_cmd:
                steps.append({
                    "name": f"Lint code ({lang.language})",
                    "run": lang.lint_cmd,
                })

            # Build step
            if lang.build_cmd:
                steps.append({
                    "name": f"Build ({lang.language})",
                    "run": lang.build_cmd,
                })

            # Test step
            if lang.test_cmd:
                step_obj: Dict[str, Any] = {
                    "name": f"Run tests ({lang.language})",
                    "run": lang.test_cmd,
                }
                # Wire environment variables and secrets into test step
                step_env: Dict[str, str] = {}
                for k, v in context.env_vars.items():
                    step_env[k] = v
                for s in context.required_secrets:
                    step_env[s] = f"${{{{ secrets.{s} }}}}"

                if step_env:
                    step_obj["env"] = step_env

                steps.append(step_obj)

        test_job["steps"] = steps
        workflow["jobs"]["test"] = test_job

        stream = io.StringIO()
        stream.write("# Synthesized deterministically by Heurix (hx)\n")
        stream.write("# Non-destructive updates: preserve blocks marked with # @heurix:preserve\n")
        yaml.dump(workflow, stream)

        return {".github/workflows/ci.yml": stream.getvalue()}
