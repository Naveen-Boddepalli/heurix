"""
Machine-readable `hx check` reports: JSON, and SARIF 2.1.0 for GitHub code scanning.

Both formats are a contract: field names and rule IDs only change in a major release.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from heurix import __version__
from heurix.core.drift import DriftFinding
from heurix.core.security import RULES as SECURITY_RULES

REPORT_FORMATS = ("text", "json", "sarif")

DOCS_URL = "https://github.com/Naveen-Boddepalli/heurix/blob/main/docs"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"

# Rules that aren't security audits: rule ID -> (description, docs page).
_CHECK_RULES: dict[str, tuple[str, str]] = {
    "drift": ("Generated CI configuration no longer matches the repository", "drift-detection.md"),
    "lockfile": ("Workflow action missing from .github/workflows/actions.lock", "drift-detection.md"),
}

# GitHub code scanning ranks security alerts by this score (0.1-10; 7.0 and up is "high").
_SECURITY_SEVERITY = {"ERROR": "8.0", "WARNING": "5.0"}
_SARIF_LEVEL = {"ERROR": "error", "WARNING": "warning", "INFO": "note"}


def _rule_meta(rule_id: str) -> tuple[str, str, bool]:
    """(description, help URL, is security rule) for a rule ID."""
    if rule_id in SECURITY_RULES:
        return SECURITY_RULES[rule_id][1], f"{DOCS_URL}/drift-detection.md#security-audit-hx-check---security", True
    description, page = _CHECK_RULES.get(rule_id, (rule_id, "drift-detection.md"))
    return description, f"{DOCS_URL}/{page}", False


def _summary(findings: Sequence[DriftFinding]) -> dict[str, int]:
    return {
        "total": len(findings),
        "errors": sum(f.severity == "ERROR" for f in findings),
        "warnings": sum(f.severity == "WARNING" for f in findings),
    }


def render_json(findings: Sequence[DriftFinding]) -> str:
    report = {
        "tool": "heurix",
        "version": __version__,
        "summary": _summary(findings),
        "findings": [
            {
                "rule_id": f.rule_id,
                "severity": f.severity,
                "file": f.file_path,
                "line": f.line,
                "issue": f.issue,
                "recommendation": f.recommendation,
            }
            for f in findings
        ],
    }
    return json.dumps(report, indent=2)


def render_sarif(findings: Sequence[DriftFinding]) -> str:
    rule_ids = sorted({f.rule_id for f in findings})
    rules: list[dict[str, Any]] = []
    for rule_id in rule_ids:
        description, help_uri, is_security = _rule_meta(rule_id)
        default = SECURITY_RULES[rule_id][0] if is_security else "WARNING"
        rule: dict[str, Any] = {
            "id": rule_id,
            "name": rule_id,
            "shortDescription": {"text": description},
            "helpUri": help_uri,
            "defaultConfiguration": {"level": _SARIF_LEVEL[default]},
            "properties": {"tags": ["security"] if is_security else ["ci"]},
        }
        if is_security:
            rule["properties"]["security-severity"] = _SECURITY_SEVERITY[default]
        rules.append(rule)

    results = []
    for f in findings:
        results.append(
            {
                "ruleId": f.rule_id,
                "ruleIndex": rule_ids.index(f.rule_id),
                "level": _SARIF_LEVEL.get(f.severity, "warning"),
                "message": {"text": f"{f.issue} {f.recommendation}"},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": f.file_path, "uriBaseId": "%SRCROOT%"},
                            # Code scanning needs a line; findings about a whole file point at line 1.
                            "region": {"startLine": f.line or 1},
                        }
                    }
                ],
            }
        )

    sarif = {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "heurix",
                        "informationUri": "https://github.com/Naveen-Boddepalli/heurix",
                        "version": __version__,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(sarif, indent=2)
