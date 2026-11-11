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

    @staticmethod
    def _select_schema(rel_path: str) -> Tuple[str, dict] | None:
        if ".github/workflows" in rel_path:
            return ("GitHub Workflow Schema Error", GITHUB_WORKFLOW_SCHEMA)
        if "dependabot.yml" in rel_path or "dependabot.yaml" in rel_path:
            return ("Dependabot Schema Error", DEPENDABOT_SCHEMA)
        if rel_path.startswith("k8s/") or rel_path.endswith((".k8s.yaml", ".k8s.yml")):
            return ("Kubernetes Manifest Schema Error", K8S_SCHEMA)
        return None
