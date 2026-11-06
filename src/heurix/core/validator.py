"""
Pre-Flight YAML and JSON Schema Validation.
Ensures zero invalid YAML is written to disk.
"""

from __future__ import annotations

from typing import List, Tuple
from ruamel.yaml import YAML
import jsonschema

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


class PreflightValidator:
    """
    Validates YAML content syntax and schema conformance before disk writes.
    """

    def __init__(self):
        self.yaml = YAML(typ="safe")

    def validate(self, rel_path: str, content: str) -> Tuple[bool, List[str]]:
        errors: List[str] = []

        # 1. Parse YAML syntax
        try:
            doc = self.yaml.load(content)
        except Exception as e:
            return False, [f"YAML Syntax Error in '{rel_path}': {e}"]

        if not isinstance(doc, dict):
            return False, [f"YAML Content in '{rel_path}' is not a valid dictionary/mapping."]

        # 2. Schema check based on file path
        if ".github/workflows" in rel_path:
            try:
                jsonschema.validate(instance=doc, schema=GITHUB_WORKFLOW_SCHEMA)
            except jsonschema.ValidationError as ve:
                errors.append(f"GitHub Workflow Schema Error: {ve.message}")
        elif "dependabot.yml" in rel_path or "dependabot.yaml" in rel_path:
            try:
                jsonschema.validate(instance=doc, schema=DEPENDABOT_SCHEMA)
            except jsonschema.ValidationError as ve:
                errors.append(f"Dependabot Schema Error: {ve.message}")
        elif rel_path.startswith("k8s/") or rel_path.endswith(".k8s.yaml"):
            try:
                jsonschema.validate(instance=doc, schema=K8S_SCHEMA)
            except jsonschema.ValidationError as ve:
                errors.append(f"Kubernetes Manifest Schema Error: {ve.message}")

        return (len(errors) == 0), errors
