"""
Pre-Flight YAML and JSON Schema Validation.
Ensures zero invalid YAML is written to disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Tuple

import jsonschema
from ruamel.yaml import YAML

# Lightweight structural schema for GitHub Actions workflow
GITHUB_WORKFLOW_SCHEMA = {
    "type": "object",
    "required": ["jobs"],
    "properties": {
        "name": {"type": "string"},
        "on": {"type": ["object", "string", "array"]},
        "jobs": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {
                "type": "object",
                "required": ["runs-on", "steps"],
                "properties": {
                    "runs-on": {"type": "string"},
                    "needs": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ]
                    },
                    "defaults": {"type": "object"},
                    "strategy": {"type": "object"},
                    "steps": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                    "services": {"type": "object"},
                },
            },
        },
    },
}

DEPENDABOT_SCHEMA = {
    "type": "object",
    "required": ["version", "updates"],
    "properties": {
        "version": {"type": "integer"},
        "updates": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["package-ecosystem", "directory", "schedule"],
            },
        },
    },
}

K8S_SCHEMA = {
    "type": "object",
    "required": ["apiVersion", "kind", "metadata"],
    "properties": {
        "apiVersion": {"type": "string"},
        "kind": {"type": "string"},
        "metadata": {"type": "object"},
    },
}


@dataclass
class ValidationOutcome:
    """Structured pre-flight validation result distinguishing critical and optional failures."""

    valid_files: Dict[str, str] = field(default_factory=dict)
    critical_errors: Dict[str, List[str]] = field(default_factory=dict)
    optional_warnings: Dict[str, List[str]] = field(default_factory=dict)
    excluded_files: Dict[str, str] = field(default_factory=dict)

    @property
    def has_critical_errors(self) -> bool:
        return bool(self.critical_errors)

    @property
    def has_warnings(self) -> bool:
        return bool(self.optional_warnings)

    @property
    def is_ok(self) -> bool:
        return not self.critical_errors


class PreflightValidator:
    """
    Validates YAML content syntax and schema conformance before disk writes.
    """

    def __init__(self):
        self.yaml = YAML(typ="safe")

    def validate(self, rel_path: str, content: str) -> Tuple[bool, List[str]]:
        errors: List[str] = []

        # 1. Parse YAML syntax across all documents in stream
        try:
            raw_docs = list(self.yaml.load_all(content))
        except Exception as e:
            return False, [f"YAML Syntax Error in '{rel_path}': {e}"]

        docs = [d for d in raw_docs if d is not None]
        if not docs:
            return False, [f"YAML Content in '{rel_path}' is not a valid dictionary/mapping."]

        multi = len(docs) > 1

        schema_entry = self._select_schema(rel_path)

        # 2. Schema check across each parsed document based on file path
        for idx, doc in enumerate(docs, start=1):
            doc_suffix = f" (document {idx})" if multi else ""
            if not isinstance(doc, dict):
                errors.append(
                    f"YAML Content in '{rel_path}'{doc_suffix} is not a valid dictionary/mapping."
                )
                continue

            if schema_entry is not None:
                label, schema = schema_entry
                try:
                    jsonschema.validate(instance=doc, schema=schema)
                except jsonschema.ValidationError as ve:
                    errors.append(f"{label}{doc_suffix}: {ve.message}")

        return (len(errors) == 0), errors

    def validate_batch(
        self,
        files: Mapping[str, str],
        strict: bool = False,
    ) -> ValidationOutcome:
        """
        Validate candidate generated files and separate fatal CI/Dependabot errors
        from non-fatal optional Kubernetes manifest warnings unless strict=True.
        """
        outcome = ValidationOutcome()
        for rel_path, content in files.items():
            is_valid, errors = self.validate(rel_path, content)
            if is_valid:
                outcome.valid_files[rel_path] = content
            elif not strict and self.is_optional_manifest(rel_path):
                outcome.optional_warnings[rel_path] = errors
                outcome.excluded_files[rel_path] = content
            else:
                outcome.critical_errors[rel_path] = errors
        return outcome

    @staticmethod
    def _normalize_rel_path(rel_path: str) -> str:
        norm = rel_path.strip().replace("\\", "/")
        while norm.startswith("./"):
            norm = norm[2:]
        return norm

    @staticmethod
    def is_optional_manifest(rel_path: str) -> bool:
        """
        Return True for optional Kubernetes manifest paths ('k8s/*' or '*.k8s.yaml'/'*.k8s.yml'),
        and False for core CI workflows and Dependabot configs.
        """
        norm = PreflightValidator._normalize_rel_path(rel_path)
        if ".github/workflows" in norm or "dependabot.yml" in norm or "dependabot.yaml" in norm:
            return False
        return norm.startswith("k8s/") or norm.endswith((".k8s.yaml", ".k8s.yml"))

    @staticmethod
    def _select_schema(rel_path: str) -> Tuple[str, dict] | None:
        norm = PreflightValidator._normalize_rel_path(rel_path)
        if ".github/workflows" in norm:
            return ("GitHub Workflow Schema Error", GITHUB_WORKFLOW_SCHEMA)
        if "dependabot.yml" in norm or "dependabot.yaml" in norm:
            return ("Dependabot Schema Error", DEPENDABOT_SCHEMA)
        if norm.startswith("k8s/") or norm.endswith((".k8s.yaml", ".k8s.yml")):
            return ("Kubernetes Manifest Schema Error", K8S_SCHEMA)
        return None
