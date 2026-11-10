"""
Cloud Deployment Targets Detector (Vercel, Firebase, etc.).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from heurix.core.context import DeploymentTarget, ProjectContext
from heurix.core.indexer import RepoIndexer
from heurix.detectors.base import BaseDetector


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
            vercel_config: Dict[str, Any] = {}
            if indexer.has_file("vercel.json"):
                raw = indexer.read_text("vercel.json") or ""
                try:
                    vercel_config = json.loads(raw)
                except Exception:
                    pass

            project_name = vercel_config.get("name") or context.repo_name
            framework = vercel_config.get("framework")
            features = ["hosting"]
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
            firebase_config: Dict[str, Any] = {}
            if indexer.has_file("firebase.json"):
                raw = indexer.read_text("firebase.json") or ""
                try:
                    firebase_config = json.loads(raw)
                except Exception:
                    pass

            project_id = None
            if indexer.has_file(".firebaserc"):
                raw_rc = indexer.read_text(".firebaserc") or ""
                try:
                    rc_data = json.loads(raw_rc)
                    project_id = rc_data.get("projects", {}).get("default")
                except Exception:
                    pass

            project_id = project_id or context.repo_name

            features: List[str] = []
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
            context.add_explain(
                f"Detected Firebase target (project: '{project_id}', features: {features})"
            )
