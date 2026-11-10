"""
GitHub Actions CI/CD Workflow Synthesizer.
"""

from __future__ import annotations

import io
import re
from typing import Any, Dict, List, Optional
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from heurix.core.context import ProjectContext
from heurix.synthesizers.base import BaseSynthesizer

ACTION_VERSIONS: Dict[str, str] = {
    "actions/checkout": "v4",
    "astral-sh/setup-uv": "v5",
    "actions/setup-python": "v5",
    "snok/install-poetry": "v1",
    "pnpm/action-setup": "v4",
    "actions/setup-node": "v4",
    "oven-sh/setup-bun": "v2",
    "dtolnay/rust-toolchain": "stable",
    "Swatinem/rust-cache": "v2",
    "actions/setup-go": "v5",
    "golangci/golangci-lint-action": "v4",
    "amondnet/vercel-action": "v25",
    "FirebaseExtended/action-hosting-deploy": "v0",
}

_SHA40_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _build_action_step(
    name: str,
    action_repo: str,
    action_shas: Dict[str, str],
    with_cfg: Optional[Dict[str, Any]] = None,
) -> CommentedMap:
    """Build a workflow step referencing a pinned tag or optional 40-char commit SHA."""
    default_ref = ACTION_VERSIONS[action_repo]
    step = CommentedMap()
    step["name"] = name
    pinned_sha = action_shas.get(action_repo, "").strip()
    if pinned_sha and _SHA40_RE.match(pinned_sha):
        step["uses"] = f"{action_repo}@{pinned_sha}"
        step.yaml_add_eol_comment(default_ref, "uses")
    else:
        step["uses"] = f"{action_repo}@{default_ref}"
    if with_cfg:
        step["with"] = with_cfg
    return step


class GitHubActionsSynthesizer(BaseSynthesizer):
    @property
    def name(self) -> str:
        return "GitHub Actions CI"

    def synthesize(self, context: ProjectContext) -> Dict[str, str]:
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)
        yaml.width = 4096

        ci_cfg = context.policy_config.get("ci", {}) if isinstance(context.policy_config, dict) else {}
        if not isinstance(ci_cfg, dict):
            ci_cfg = {}

        default_branch = str(ci_cfg.get("default_branch") or "main").strip() or "main"
        trigger_branches: List[str] = []
        for branch in (default_branch, "main", "master"):
            if branch not in trigger_branches:
                trigger_branches.append(branch)

        pin_enabled = ci_cfg.get("pin_actions", True)
        raw_action_shas = ci_cfg.get("action_shas", {})
        action_shas: Dict[str, str] = (
            {str(k): str(v) for k, v in raw_action_shas.items()}
            if pin_enabled and isinstance(raw_action_shas, dict)
            else {}
        )

        workflow: Dict[str, Any] = {
            "name": "CI",
            "on": {
                "push": {"branches": list(trigger_branches)},
                "pull_request": {"branches": list(trigger_branches)},
            },
            "jobs": {},
        }

        # If monorepo, add path filters
        if context.is_monorepo and context.monorepo_packages:
            workflow["on"]["push"]["paths"] = ["**"]
            workflow["on"]["pull_request"]["paths"] = ["**"]

        runner = getattr(context, "runner", "ubuntu-latest") or "ubuntu-latest"
        test_job: Dict[str, Any] = {
            "runs-on": runner,
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
        steps: List[Any] = [
            _build_action_step("Checkout repository", "actions/checkout", action_shas)
        ]

        # Step generators per language
        for lang in context.languages:
            if lang.language == "python":
                if lang.package_manager == "uv":
                    steps.append(
                        _build_action_step(
                            "Install uv",
                            "astral-sh/setup-uv",
                            action_shas,
                            {"enable-cache": True},
                        )
                    )
                    steps.append(
                        _build_action_step(
                            f"Set up Python {lang.runtime_version}",
                            "actions/setup-python",
                            action_shas,
                            {"python-version": lang.runtime_version},
                        )
                    )
                    steps.append({
                        "name": "Install dependencies",
                        "run": lang.install_cmd,
                    })
                elif lang.package_manager == "poetry":
                    steps.append(
                        _build_action_step(
                            f"Set up Python {lang.runtime_version}",
                            "actions/setup-python",
                            action_shas,
                            {"python-version": lang.runtime_version, "cache": "poetry"},
                        )
                    )
                    steps.append(
                        _build_action_step(
                            "Install Poetry",
                            "snok/install-poetry",
                            action_shas,
                            {"virtualenvs-create": True, "virtualenvs-in-project": True},
                        )
                    )
                    steps.append({
                        "name": "Install dependencies",
                        "run": lang.install_cmd,
                    })
                else:
                    setup_with: Dict[str, Any] = {"python-version": lang.runtime_version}
                    if "requirements" in lang.install_cmd or "pip install -e" in lang.install_cmd:
                        setup_with["cache"] = "pip"
                    steps.append(
                        _build_action_step(
                            f"Set up Python {lang.runtime_version}",
                            "actions/setup-python",
                            action_shas,
                            setup_with,
                        )
                    )
                    steps.append({
                        "name": "Install dependencies",
                        "run": lang.install_cmd,
                    })

            elif lang.language == "node":
                if lang.package_manager == "pnpm":
                    steps.append(
                        _build_action_step(
                            "Install pnpm",
                            "pnpm/action-setup",
                            action_shas,
                            {"version": "9"},
                        )
                    )
                    steps.append(
                        _build_action_step(
                            f"Set up Node.js {lang.runtime_version}",
                            "actions/setup-node",
                            action_shas,
                            {"node-version": lang.runtime_version, "cache": "pnpm"},
                        )
                    )
                    steps.append({
                        "name": "Install dependencies",
                        "run": lang.install_cmd,
                    })
                elif lang.package_manager == "yarn":
                    steps.append(
                        _build_action_step(
                            f"Set up Node.js {lang.runtime_version}",
                            "actions/setup-node",
                            action_shas,
                            {"node-version": lang.runtime_version, "cache": "yarn"},
                        )
                    )
                    steps.append({
                        "name": "Install dependencies",
                        "run": lang.install_cmd,
                    })
                elif lang.package_manager == "bun":
                    steps.append(
                        _build_action_step(
                            "Set up Bun",
                            "oven-sh/setup-bun",
                            action_shas,
                            {"bun-version": "latest"},
                        )
                    )
                    steps.append({
                        "name": "Install dependencies",
                        "run": lang.install_cmd,
                    })
                else:
                    steps.append(
                        _build_action_step(
                            f"Set up Node.js {lang.runtime_version}",
                            "actions/setup-node",
                            action_shas,
                            {"node-version": lang.runtime_version, "cache": "npm"},
                        )
                    )
                    steps.append({
                        "name": "Install dependencies",
                        "run": lang.install_cmd,
                    })

            elif lang.language == "rust":
                steps.append(
                    _build_action_step(
                        f"Set up Rust ({lang.runtime_version})",
                        "dtolnay/rust-toolchain",
                        action_shas,
                        {"toolchain": lang.runtime_version},
                    )
                )
                steps.append(
                    _build_action_step("Rust Cache", "Swatinem/rust-cache", action_shas)
                )

            elif lang.language == "go":
                steps.append(
                    _build_action_step(
                        f"Set up Go {lang.runtime_version}",
                        "actions/setup-go",
                        action_shas,
                        {"go-version": lang.runtime_version, "cache": True},
                    )
                )
                steps.append({
                    "name": "Download Go dependencies",
                    "run": lang.install_cmd,
                })

            elif lang.language == "cpp":
                runner_lower = runner.lower()
                if "macos" in runner_lower:
                    cpp_install_run = "brew install cmake ninja"
                elif "windows" in runner_lower:
                    cpp_install_run = "choco install cmake ninja"
                else:
                    apt_pkgs = "cmake ninja-build build-essential"
                    if lang.lint_cmd and "clang-tidy" in lang.lint_cmd:
                        apt_pkgs += " clang-tidy"
                    cpp_install_run = f"sudo apt-get update && sudo apt-get install -y {apt_pkgs}"
                steps.append({
                    "name": f"Install build tools ({lang.runtime_version})",
                    "run": cpp_install_run,
                })

            # Build and Lint steps (run build before lint for cpp to generate compile_commands.json)
            if lang.language == "cpp":
                if lang.build_cmd:
                    steps.append({
                        "name": f"Build ({lang.language})",
                        "run": lang.build_cmd,
                    })
                if lang.lint_cmd:
                    steps.append({
                        "name": f"Lint code ({lang.language})",
                        "run": lang.lint_cmd,
                    })
            elif lang.language == "go":
                if lang.lint_cmd:
                    steps.append(
                        _build_action_step(
                            "Run golangci-lint",
                            "golangci/golangci-lint-action",
                            action_shas,
                            {"version": "v1.57"},
                        )
                    )
                if lang.build_cmd:
                    steps.append({
                        "name": f"Build ({lang.language})",
                        "run": lang.build_cmd,
                    })
            else:
                if lang.lint_cmd:
                    steps.append({
                        "name": f"Lint code ({lang.language})",
                        "run": lang.lint_cmd,
                    })
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
                # Wire environment variables and test-scoped secrets into test step
                step_env: Dict[str, str] = {}
                for k, v in context.env_vars.items():
                    step_env[k] = v
                deployment_secret_set = set(context.deployment_secrets)
                for s in context.test_secrets:
                    if s not in deployment_secret_set:
                        step_env[s] = f"${{{{ secrets.{s} }}}}"

                if step_env:
                    step_obj["env"] = step_env

                steps.append(step_obj)

        test_job["steps"] = steps
        workflow["jobs"]["test"] = test_job

        deploy_if = f"github.ref == 'refs/heads/{default_branch}' && github.event_name == 'push'"

        # Add deployment jobs for detected cloud deployment targets
        for target in getattr(context, "deployment_targets", []):
            if target.platform == "vercel":
                workflow["jobs"]["deploy_vercel"] = {
                    "name": "Deploy to Vercel",
                    "needs": "test",
                    "runs-on": "ubuntu-latest",
                    "if": deploy_if,
                    "steps": [
                        _build_action_step("Checkout repository", "actions/checkout", action_shas),
                        _build_action_step(
                            "Deploy to Vercel (Production)",
                            "amondnet/vercel-action",
                            action_shas,
                            {
                                "vercel-token": "${{ secrets.VERCEL_TOKEN }}",
                                "vercel-org-id": "${{ secrets.VERCEL_ORG_ID }}",
                                "vercel-project-id": "${{ secrets.VERCEL_PROJECT_ID }}",
                                "vercel-args": "--prod",
                            },
                        ),
                    ],
                }
            elif target.platform == "firebase":
                workflow["jobs"]["deploy_firebase"] = {
                    "name": "Deploy to Firebase",
                    "needs": "test",
                    "runs-on": "ubuntu-latest",
                    "if": deploy_if,
                    "steps": [
                        _build_action_step("Checkout repository", "actions/checkout", action_shas),
                        _build_action_step(
                            "Deploy to Firebase Hosting",
                            "FirebaseExtended/action-hosting-deploy",
                            action_shas,
                            {
                                "repoToken": "${{ secrets.GITHUB_TOKEN }}",
                                "firebaseServiceAccount": "${{ secrets.FIREBASE_SERVICE_ACCOUNT }}",
                                "projectId": target.project_id or context.repo_name,
                                "channelId": "live",
                            },
                        ),
                    ],
                }

        stream = io.StringIO()
        stream.write("# Synthesized deterministically by Heurix (hx)\n")
        stream.write("# Non-destructive updates: preserve blocks marked with # @heurix:preserve\n")
        yaml.dump(workflow, stream)

        return {".github/workflows/ci.yml": stream.getvalue()}
