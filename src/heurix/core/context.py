"""
Intermediate Representation (IR) Models for Heurix.
Generators never read the filesystem directly; they only read ProjectContext.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class ServiceRequirement(BaseModel):
    name: str  # e.g. "postgres", "redis", "mongodb"
    image: str  # e.g. "postgres:16-alpine"
    ports: List[int] = Field(default_factory=list)  # e.g. [5432]
    env: Dict[str, str] = Field(default_factory=dict)
    source_file: str = ""  # e.g. "docker-compose.yml" or "pyproject.toml"
    package_path: Optional[str] = None  # None = root/global; e.g. "services/api"


class LanguageContext(BaseModel):
    language: str  # "python", "node", "rust", "go", "cpp"
    runtime_version: str  # "3.12", "20.x", "1.78"
    version_source: str  # ".python-version", "pyproject.toml", ".nvmrc"
    package_manager: str  # "uv", "poetry", "npm", "pnpm", "yarn", "bun", "cargo", "gomod", "cmake"
    install_cmd: str
    build_cmd: Optional[str] = None
    test_cmd: Optional[str] = None
    lint_cmd: Optional[str] = None
    unit_test_runner: Optional[str] = None
    e2e_test_runner: Optional[str] = None
    e2e_cmd: Optional[str] = None
    working_dir: str = "."
    framework: Optional[str] = None
    confidence: float = 1.0
    matrix_versions: List[str] = Field(default_factory=list)
    cache_dependency_path: Optional[str] = None
    is_workspace_root: Optional[bool] = None


class ContainerContext(BaseModel):
    dockerfile_path: str
    exposed_ports: List[int] = Field(default_factory=list)
    base_image: str = ""
    has_healthcheck: bool = False
    build_target: Optional[str] = None


class DeploymentTarget(BaseModel):
    platform: str  # "vercel", "firebase", etc.
    config_file: str  # "vercel.json", "firebase.json", etc.
    project_id: Optional[str] = None
    features: List[str] = Field(default_factory=list)  # e.g. ["hosting", "functions", "firestore"]
    deploy_cmd: Optional[str] = None
    preview_deploy_cmd: Optional[str] = None
    required_secrets: List[str] = Field(default_factory=list)


class MonorepoPackage(BaseModel):
    name: str
    path: str
    language: str
    package_manager: str
    runtime_version: str = ""
    version_source: str = ""
    install_cmd: Optional[str] = None
    build_cmd: Optional[str] = None
    test_cmd: Optional[str] = None
    lint_cmd: Optional[str] = None
    unit_test_runner: Optional[str] = None
    e2e_test_runner: Optional[str] = None
    e2e_cmd: Optional[str] = None
    framework: Optional[str] = None
    cache_dependency_path: Optional[str] = None
    matrix_versions: List[str] = Field(default_factory=list)


class ProjectContext(BaseModel):
    repo_name: str
    repo_root: str
    is_monorepo: bool = False
    monorepo_packages: List[MonorepoPackage] = Field(default_factory=list)
    languages: List[LanguageContext] = Field(default_factory=list)
    services: List[ServiceRequirement] = Field(default_factory=list)
    containers: List[ContainerContext] = Field(default_factory=list)
    deployment_targets: List[DeploymentTarget] = Field(default_factory=list)
    test_secrets: List[str] = Field(default_factory=list)
    deployment_secrets: List[str] = Field(default_factory=list)
    required_secrets: List[str] = Field(default_factory=list)
    env_vars: Dict[str, str] = Field(default_factory=dict)
    language_scores: Dict[str, int] = Field(default_factory=dict)
    explain_log: List[str] = Field(default_factory=list)
    confidence: float = 1.0
    runner: str = "ubuntu-latest"
    matrix_os: List[str] = Field(default_factory=list)
    split_e2e_jobs: Optional[bool] = None
    policy_config: Dict[str, Any] = Field(default_factory=dict)

    def sync_required_secrets(self) -> None:
        """Synchronize test_secrets and deployment_secrets into required_secrets without duplicates."""
        for secret in (*self.test_secrets, *self.deployment_secrets):
            if secret not in self.required_secrets:
                self.required_secrets.append(secret)

    @model_validator(mode="after")
    def _sync_required_secrets(self) -> "ProjectContext":
        self.sync_required_secrets()
        return self

    def add_explain(self, step: str) -> None:
        self.explain_log.append(step)

    def has_language(self, name: str) -> bool:
        return any(lang.language.lower() == name.lower() for lang in self.languages)

    def get_language(self, name: str) -> Optional[LanguageContext]:
        for lang in self.languages:
            if lang.language.lower() == name.lower():
                return lang
        return None

    def get_languages(self, name: str) -> List[LanguageContext]:
        target = name.lower()
        return [lang for lang in self.languages if lang.language.lower() == target]

    def get_primary_language(self) -> Optional[LanguageContext]:
        """
        Determine primary language dynamically using indexed language scores
        (source file volume + root manifest weighting) or recorded language
        metadata, breaking ties deterministically by alphabetized language name.
        """
        if not self.languages:
            return None
        if len(self.languages) == 1:
            return self.languages[0]

        if self.language_scores:
            return min(
                self.languages,
                key=lambda lang: (
                    -self.language_scores.get(lang.language.lower(), 0),
                    lang.language.lower(),
                ),
            )

        return min(
            self.languages,
            key=lambda lang: (
                -lang.confidence,
                lang.language.lower(),
            ),
        )

    def has_deployment_target(self, platform: str) -> bool:
        return any(t.platform.lower() == platform.lower() for t in self.deployment_targets)

    def get_deployment_target(self, platform: str) -> Optional[DeploymentTarget]:
        for t in self.deployment_targets:
            if t.platform.lower() == platform.lower():
                return t
        return None
