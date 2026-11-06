"""
Environment Variables and Secrets Discovery Detector.
"""

from __future__ import annotations

import re
from typing import Set
from heurix.core.context import ProjectContext
from heurix.core.indexer import RepoIndexer
from heurix.detectors.base import BaseDetector

SENSITIVE_KEYWORDS = [
    "SECRET",
    "PASSWORD",
    "TOKEN",
    "KEY",
    "AUTH",
    "PRIVATE",
    "CREDENTIAL",
    "CERT",
]


class EnvDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "Environment"

    def detect(self, indexer: RepoIndexer) -> bool:
        indicators = [
            ".env.example",
            ".env.template",
            ".env.sample",
            ".env.dist",
            ".env.local.example",
        ]
        return any(indexer.has_file(f) for f in indicators)

    def analyze(self, indexer: RepoIndexer, context: ProjectContext) -> None:
        context.add_explain("Analyzing environment templates and secret definitions...")

        env_files = [
            f for f in [
                ".env.example",
                ".env.template",
                ".env.sample",
                ".env.dist",
                ".env.local.example",
            ] if indexer.has_file(f)
        ]

        found_secrets: Set[str] = set()

        for ef in env_files:
            content = indexer.read_text(ef) or ""
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")

                    is_sensitive = any(sk in key.upper() for sk in SENSITIVE_KEYWORDS)
                    if is_sensitive:
                        found_secrets.add(key)
                    else:
                        context.env_vars[key] = val

            context.add_explain(f"Scanned {ef}: discovered {len(context.env_vars)} env defaults and {len(found_secrets)} potential secrets")

        for s in sorted(found_secrets):
            if s not in context.required_secrets:
                context.required_secrets.append(s)
                context.add_explain(f"Wired sensitive secret: {s} -> ${{ secrets.{s} }}")
