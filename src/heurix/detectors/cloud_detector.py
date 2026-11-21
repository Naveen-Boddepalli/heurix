"""
Cloud Deployment Targets Detector (Vercel, Firebase, etc.).
"""

from __future__ import annotations

import json
from typing import Any

from heurix.core.context import DeploymentTarget, ProjectContext
from heurix.core.indexer import RepoIndexer
from heurix.detectors.base import BaseDetector


def _read_json_object(indexer: RepoIndexer, context: ProjectContext, path: str) -> dict[str, Any]:
    """Parse `path` as a JSON object; warn and return {} if it is invalid or not an object."""
    raw = indexer.read_text(path) or ""
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError as e:
        context.add_warning(f"Could not parse {path} ({e}); its settings were ignored.")
        return {}
    if not isinstance(data, dict):
        context.add_warning(f"{path} is not a JSON object (found {type(data).__name__}); its settings were ignored.")
        return {}
    return data


def _str_or_none(value: Any) -> str | None:
    """Return `value` if it is a non-empty string, else None."""
    return value if isinstance(value, str) and value.strip() else None


class CloudDetector(BaseDetector):
    """
    Detects cloud deployment targets such as Vercel and Firebase,
    extracting project metadata, build hooks, and required CI secrets.
    """

    @property
    def name(self) -> str:
        return "Cloud Deployment"

    def detect(self, indexer: RepoIndexer) -> bool:
        indicators = [
            "vercel.json",
            ".vercel",
            "firebase.json",
            ".firebaserc",
        ]
        return any(indexer.has_file(f) for f in indicators)

    def analyze(self, indexer: RepoIndexer, context: ProjectContext) -> None:
        context.add_explain("Analyzing cloud deployment targets...")

        # 1. Detect Vercel
        if indexer.has_file("vercel.json") or indexer.has_file(".vercel"):
            vercel_config: dict[str, Any] = {}
            if indexer.has_file("vercel.json"):
                vercel_config = _read_json_object(indexer, context, "vercel.json")

            project_name = _str_or_none(vercel_config.get("name")) or context.repo_name
            framework = _str_or_none(vercel_config.get("framework"))
            features: list[str] = ["hosting"]
            if vercel_config.get("functions") or any(f.startswith("api/") for f in indexer.files):
                features.append("serverless")

            vercel_secrets = ["VERCEL_TOKEN", "VERCEL_ORG_ID", "VERCEL_PROJECT_ID"]
            for s in vercel_secrets:
                if s not in context.required_secrets:
                    context.required_secrets.append(s)

            target = DeploymentTarget(
                platform="vercel",
                config_file="vercel.json" if indexer.has_file("vercel.json") else ".vercel",
                project_id=project_name,
                features=features,
                deploy_cmd="vercel --prod",
                preview_deploy_cmd="vercel",
                required_secrets=vercel_secrets,
            )
            context.deployment_targets.append(target)
            context.add_explain(
                f"Detected Vercel target (project: '{project_name}', framework: {framework or 'auto'}, features: {features})"
            )

        # 2. Detect Firebase
        if indexer.has_file("firebase.json") or indexer.has_file(".firebaserc"):
            firebase_config: dict[str, Any] = {}
            if indexer.has_file("firebase.json"):
                firebase_config = _read_json_object(indexer, context, "firebase.json")

            project_id = None
            if indexer.has_file(".firebaserc"):
                rc_data = _read_json_object(indexer, context, ".firebaserc")
                projects = rc_data.get("projects")
                if isinstance(projects, dict):
                    project_id = _str_or_none(projects.get("default"))

            project_id = project_id or context.repo_name

            features = []
            for feat in ["hosting", "functions", "firestore", "storage", "emulators", "remoteconfig"]:
                if feat in firebase_config:
                    features.append(feat)

            if not features:
                features.append("hosting")

            firebase_secrets = ["FIREBASE_SERVICE_ACCOUNT"]
            for s in firebase_secrets:
                if s not in context.required_secrets:
                    context.required_secrets.append(s)

            deploy_cmd = "firebase deploy"
            if len(features) == 1 and "hosting" in features:
                deploy_cmd = "firebase deploy --only hosting"

            target = DeploymentTarget(
                platform="firebase",
                config_file="firebase.json" if indexer.has_file("firebase.json") else ".firebaserc",
                project_id=project_id,
                features=features,
                deploy_cmd=deploy_cmd,
                preview_deploy_cmd="firebase hosting:channel:deploy preview",
                required_secrets=firebase_secrets,
            )
            context.deployment_targets.append(target)
            context.add_explain(f"Detected Firebase target (project: '{project_id}', features: {features})")
