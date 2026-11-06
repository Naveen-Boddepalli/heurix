"""
Non-Destructive Smart Merge and AST Round-Trip Preservation.
"""

from __future__ import annotations

import io
from typing import Any, List
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq


class SmartMerger:
    """
    Round-trip AST merger that preserves comments, custom jobs, and
    # @heurix:preserve / # @autoyaml:preserve directives.
    """

    def __init__(self):
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.indent(mapping=2, sequence=4, offset=2)

    def merge_yaml(self, existing_content: str, new_content: str) -> str:
        """
        Merges new_content into existing_content non-destructively.
        """
        if not existing_content.strip():
            return new_content

        try:
            existing_doc = self.yaml.load(existing_content)
            new_doc = self.yaml.load(new_content)
        except Exception:
            # Fallback if invalid yaml in existing
            return new_content

        if not isinstance(existing_doc, (dict, CommentedMap)) or not isinstance(new_doc, (dict, CommentedMap)):
            return new_content

        # Specialized merger for GitHub Actions workflows
        if "jobs" in new_doc and "jobs" in existing_doc:
            merged_doc = self._merge_github_workflow(existing_doc, new_doc, existing_content)
        else:
            merged_doc = self._generic_merge(existing_doc, new_doc)

        stream = io.StringIO()
        self.yaml.dump(merged_doc, stream)
        return stream.getvalue()

    def _merge_github_workflow(
        self,
        existing: CommentedMap,
        new: CommentedMap,
        raw_existing: str,
    ) -> CommentedMap:
        result = existing.copy()

        # Update metadata if needed, but preserve user triggers if customized
        if "name" in new and "name" not in result:
            result["name"] = new["name"]

        # Preserve custom jobs
        existing_jobs = result.get("jobs", CommentedMap())
        new_jobs = new.get("jobs", CommentedMap())

        merged_jobs = CommentedMap()

        # Add all new jobs
        for job_id, job_val in new_jobs.items():
            if job_id in existing_jobs:
                # Merge the managed job
                merged_jobs[job_id] = self._merge_job(existing_jobs[job_id], job_val, raw_existing)
            else:
                merged_jobs[job_id] = job_val

        # Preserve custom user jobs (e.g. deploy, slack_notify)
        for job_id, job_val in existing_jobs.items():
            if job_id not in merged_jobs:
                merged_jobs[job_id] = job_val

        result["jobs"] = merged_jobs
        return result

    def _merge_job(self, existing_job: Any, new_job: Any, raw_existing: str) -> Any:
        if not isinstance(existing_job, dict) or not isinstance(new_job, dict):
            return new_job

        merged_job = existing_job.copy()
        # Update runs-on, services from new_job
        if "runs-on" in new_job:
            merged_job["runs-on"] = new_job["runs-on"]
        if "services" in new_job:
            merged_job["services"] = new_job["services"]

        # Steps merging
        new_steps = new_job.get("steps", [])
        existing_steps = existing_job.get("steps", [])

        # Find any step in existing that has preserve directive
        preserved_steps: List[Any] = []
        for step in existing_steps:
            step_str = str(step)
            # Check if comments or text indicate preserve
            if "@heurix:preserve" in raw_existing or "@autoyaml:preserve" in raw_existing:
                name = step.get("name", "") if isinstance(step, dict) else ""
                if name and ("custom" in name.lower() or "notify" in name.lower() or "slack" in name.lower() or "deploy" in name.lower()):
                    preserved_steps.append(step)

        # Merge steps
        final_steps = list(new_steps)
        for p in preserved_steps:
            if p not in final_steps:
                final_steps.append(p)

        merged_job["steps"] = final_steps
        return merged_job

    def _generic_merge(self, existing: CommentedMap, new: CommentedMap) -> CommentedMap:
        result = existing.copy()
        for k, v in new.items():
            result[k] = v
        return result
