"""
Intermediate Representation (IR) Models for Heurix.
Generators never read the filesystem directly; they only read ProjectContext.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ServiceRequirement(BaseModel):
    name: str  # e.g. "postgres", "redis", "mongodb"
    image: str  # e.g. "postgres:16-alpine"
    ports: List[int] = Field(default_factory=list)  # e.g. [5432]
    env: Dict[str, str] = Field(default_factory=dict)
    source_file: str = ""  # e.g. "docker-compose.yml" or "pyproject.toml"


class LanguageContext(BaseModel):
    language: str  # "python", "node", "rust", "go", "cpp"
    runtime_version: str  # "3.12", "20.x", "1.78"
    version_source: str  # ".python-version", "pyproject.toml", ".nvmrc"
    package_manager: str  # "uv", "poetry", "npm", "pnpm", "yarn", "bun", "cargo", "gomod", "cmake"
    install_cmd: str
    build_cmd: Optional[str] = None
    test_cmd: Optional[str] = None
    lint_cmd: Optional[str] = None
    working_dir: str = "."
    framework: Optional[str] = None
    confidence: float = 1.0


class ContainerContext(BaseModel):
    dockerfile_path: str
    exposed_ports: List[int] = Field(default_factory=list)
    base_image: str = ""
    has_healthcheck: bool = False
    build_target: Optional[str] = None


class MonorepoPackage(BaseModel):
    name: str
    path: str
    language: str
    package_manager: str


class ProjectContext(BaseModel):
    repo_name: str
    repo_root: str
    is_monorepo: bool = False
    monorepo_packages: List[MonorepoPackage] = Field(default_factory=list)
    languages: List[LanguageContext] = Field(default_factory=list)
    services: List[ServiceRequirement] = Field(default_factory=list)
    containers: List[ContainerContext] = Field(default_factory=list)
    required_secrets: List[str] = Field(default_factory=list)
    env_vars: Dict[str, str] = Field(default_factory=dict)
    explain_log: List[str] = Field(default_factory=list)
    confidence: float = 1.0

    def add_explain(self, step: str) -> None:
        self.explain_log.append(step)

    def has_language(self, name: str) -> bool:
        return any(lang.language.lower() == name.lower() for lang in self.languages)

    def get_language(self, name: str) -> Optional[LanguageContext]:
        for lang in self.languages:
            if lang.language.lower() == name.lower():
                return lang
        return None

    def get_primary_language(self) -> Optional[LanguageContext]:
        return self.languages[0] if self.languages else None
