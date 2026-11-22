"""
Typed `.heurix.toml` Policy Schema, Resilient Validation, and Security Predicates.

All policy models, SEC-02/SEC-03 keyword predicates, and IR mutation helpers live here
with zero reverse imports from `heurix.detectors`.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from heurix.core.context import ProjectContext

# Canonical SEC-02 sensitive environment variable keywords (matching env_detector.py)
SENSITIVE_KEYWORDS: tuple[str, ...] = (
    "SECRET",
    "PASSWORD",
    "TOKEN",
    "KEY",
    "AUTH",
    "PRIVATE",
    "CREDENTIAL",
    "CERT",
    "URL",
    "URI",
    "DSN",
    "CONN",
    "WEBHOOK",
    "SESSION",
)

# Canonical SEC-03 deployment-only secret prefixes
DEPLOYMENT_SECRET_PREFIXES: tuple[str, ...] = (
    "VERCEL_",
    "FIREBASE_",
    "AWS_",
    "DOCKER_",
)

_KNOWN_TOP_LEVEL_KEYS = frozenset(
    {
        "engine",
        "ci",
        "jobs",
        "matrix",
        "overrides",
        "services",
        "env",
        "secrets",
        "linters",
        "kubernetes",
        "k8s",
    }
)

_LOC_KEY_FALLBACKS: dict[str, str] = {
    "if": "if_",
    "if_": "if",
    "with": "with_",
    "with_": "with",
    "working_directory": "working-directory",
    "working-directory": "working_directory",
    "continue_on_error": "continue-on-error",
    "continue-on-error": "continue_on_error",
    "timeout_minutes": "timeout-minutes",
    "timeout-minutes": "timeout_minutes",
    "paths_ignore": "paths-ignore",
    "paths-ignore": "paths_ignore",
}


def is_sensitive_env_key(key: str) -> bool:
    """Return True if an environment variable key matches any SEC-02 sensitive credential token."""
    key_upper = str(key).strip().upper()
    return any(sk in key_upper for sk in SENSITIVE_KEYWORDS) or "SERVICE_ACCOUNT" in key_upper


_IMAGE_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")


def is_valid_image_tag(tag: str) -> bool:
    """Return True if ``tag`` is a syntactically valid OCI/Docker image tag."""
    return bool(_IMAGE_TAG_RE.fullmatch(str(tag)))


def is_deployment_secret_key(key: str) -> bool:
    """Return True if a secret key matches a SEC-03 deployment credential prefix."""
    return str(key).strip().upper().startswith(DEPLOYMENT_SECRET_PREFIXES)


def _validate_non_empty_str(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("String value must not be empty")
    return cleaned


def _reject_bool_for_int(value: Any) -> Any:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a valid integer")
    return value


def _coerce_scalar_env_dict(val: Any) -> Any:
    """Coerce scalar int/float/bool values in env mappings into strings."""
    if not isinstance(val, Mapping):
        return val
    coerced: dict[Any, Any] = {}
    for raw_k, raw_v in val.items():
        if isinstance(raw_v, bool):
            coerced[raw_k] = "true" if raw_v else "false"
        elif isinstance(raw_v, (int, float)):
            coerced[raw_k] = str(raw_v)
        else:
            coerced[raw_k] = raw_v
    return coerced


def _deep_merge_dicts(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Deep merge two mappings so `override` takes precedence on overlapping leaf values."""
    merged: dict[str, Any] = copy.deepcopy(dict(base))
    for key, val in override.items():
        if key in merged and isinstance(merged[key], Mapping) and isinstance(val, Mapping):
            merged[key] = _deep_merge_dicts(merged[key], val)
        else:
            merged[key] = copy.deepcopy(val)
    return merged


def _reject_negated_pattern(value: str) -> str:
    if value.startswith("!"):
        raise ValueError("Path pattern must not start with '!'; list it under paths_ignore instead")
    return value


_NonEmptyStr = Annotated[str, AfterValidator(_validate_non_empty_str)]
_PathPattern = Annotated[str, AfterValidator(_validate_non_empty_str), AfterValidator(_reject_negated_pattern)]
_StrictInt = Annotated[int, BeforeValidator(_reject_bool_for_int)]


class _PolicyBase(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class EnginePolicy(_PolicyBase):
    runner: _NonEmptyStr = "ubuntu-latest"
    non_destructive: bool = True
    templates_dir: _NonEmptyStr | None = None


class StepPolicy(_PolicyBase):
    id: _NonEmptyStr | None = None
    name: str | None = None
    if_: str | None = Field(default=None, alias="if")
    uses: str | None = None
    with_: dict[str, Any] | None = Field(default=None, alias="with")
    run: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    working_directory: str | None = Field(default=None, alias="working-directory")
    shell: str | None = None
    continue_on_error: bool | None = Field(default=None, alias="continue-on-error")
    timeout_minutes: Annotated[int, BeforeValidator(_reject_bool_for_int), Field(ge=1)] | None = Field(
        default=None,
        alias="timeout-minutes",
    )

    @field_validator("env", mode="before")
    @classmethod
    def _coerce_env(cls, val: Any) -> Any:
        return _coerce_scalar_env_dict(val)

    @model_validator(mode="after")
    def _require_uses_or_run(self) -> StepPolicy:
        if not (self.uses and self.uses.strip()) and not (self.run and self.run.strip()):
            raise ValueError("Workflow step must specify 'uses' or 'run'")
        return self

    def to_step_dict(self) -> dict[str, Any]:
        """Serialize step to a plain GitHub Actions step dictionary with canonical aliases."""
        data = self.model_dump(by_alias=True, exclude_none=True, exclude_defaults=False)
        if not data.get("env"):
            data.pop("env", None)
        return data


class CiStepsPolicy(_PolicyBase):
    pre_test: list[StepPolicy] = Field(default_factory=list)
    post_test: list[StepPolicy] = Field(default_factory=list)


class CiPolicy(_PolicyBase):
    include_dependabot: bool = True
    include_k8s: bool | None = None
    default_branch: _NonEmptyStr = "main"
    pin_actions: bool = True
    action_shas: dict[str, str] = Field(default_factory=dict)
    action_versions: dict[str, str] = Field(default_factory=dict)
    permissions: dict[str, str] = Field(default_factory=dict)
    # New workflows are always hardened (least-privilege `permissions`, a `concurrency`
    # group, job timeouts, `persist-credentials: false` on checkout). `harden = true`
    # also adds whichever of these an existing workflow lacks, never replacing set values.
    harden: bool = False
    # `timeout-minutes` for generated jobs (GitHub's own default is 360).
    timeout_minutes: int = Field(default=60, ge=1, le=360)
    runners: dict[str, _NonEmptyStr] = Field(default_factory=dict)
    steps: CiStepsPolicy = Field(default_factory=CiStepsPolicy)
    # Explicit overrides for CI service-container connection URLs
    # (DATABASE_URL, MONGO_URL, MONGODB_URI, REDIS_URL).
    env: dict[str, str] = Field(default_factory=dict)
    # Trigger path filters for push / pull_request. `paths` replaces the inferred
    # monorepo filter; `paths_ignore` skips CI when only matching files change.
    paths: list[_PathPattern] | None = None
    paths_ignore: list[_PathPattern] = Field(default_factory=list, alias="paths-ignore")

    @field_validator("env", mode="before")
    @classmethod
    def _coerce_env(cls, val: Any) -> Any:
        return _coerce_scalar_env_dict(val)

    @field_validator("paths", "paths_ignore", mode="before")
    @classmethod
    def _coerce_path_list(cls, val: Any) -> Any:
        if isinstance(val, str):
            return [val]
        return val

    @field_validator("paths", "paths_ignore")
    @classmethod
    def _validate_path_patterns(cls, val: list[str] | None) -> list[str] | None:
        if val is None:
            return None
        return list(dict.fromkeys(val))

    @property
    def has_path_filters(self) -> bool:
        """Return True when the policy explicitly controls CI trigger path filters."""
        return self.paths is not None or bool(self.paths_ignore)


class JobPolicy(_PolicyBase):
    runner: _NonEmptyStr | None = None
    pre_steps: list[StepPolicy] = Field(default_factory=list)
    post_steps: list[StepPolicy] = Field(default_factory=list)


class ServicesPolicy(_PolicyBase):
    exclude: list[str] = Field(default_factory=list)


class SecretsPolicy(_PolicyBase):
    test: list[str] = Field(default_factory=list)
    deploy: list[str] = Field(default_factory=list)


_LINTER_LANG_ALIASES: dict[str, str] = {
    "c++": "cpp",
    "golang": "go",
    "nodejs": "node",
}


class LintersPolicy(_PolicyBase):
    enabled: bool = True
    python: bool | None = None
    node: bool | None = None
    go: bool | None = None
    rust: bool | None = None
    cpp: bool | None = None

    def is_enabled_for(self, language: str) -> bool:
        """Return whether linting is enabled globally and for the specified language."""
        if not self.enabled:
            return False
        lang_key = str(language).strip().lower()
        lang_key = _LINTER_LANG_ALIASES.get(lang_key, lang_key)
        if lang_key in ("python", "node", "go", "rust", "cpp"):
            lang_override = getattr(self, lang_key)
            if lang_override is False:
                return False
        return True


class K8sResourceSpecPolicy(_PolicyBase):
    cpu: _NonEmptyStr | None = None
    memory: _NonEmptyStr | None = None


class K8sResourcesPolicy(_PolicyBase):
    requests: K8sResourceSpecPolicy = Field(default_factory=K8sResourceSpecPolicy)
    limits: K8sResourceSpecPolicy = Field(default_factory=K8sResourceSpecPolicy)


class K8sProbePolicy(_PolicyBase):
    enabled: bool = True
    type: Literal["httpGet", "tcpSocket", "exec"] | None = None
    path: _NonEmptyStr | None = None
    port: Annotated[int, BeforeValidator(_reject_bool_for_int), Field(ge=1, le=65535)] | None = None
    command: list[str] | None = None
    initial_delay_seconds: Annotated[int, BeforeValidator(_reject_bool_for_int), Field(ge=0)] | None = None
    period_seconds: Annotated[int, BeforeValidator(_reject_bool_for_int), Field(ge=1)] | None = None
    timeout_seconds: Annotated[int, BeforeValidator(_reject_bool_for_int), Field(ge=1)] | None = None
    failure_threshold: Annotated[int, BeforeValidator(_reject_bool_for_int), Field(ge=1)] | None = None


class K8sHpaPolicy(_PolicyBase):
    enabled: bool = False
    min_replicas: _StrictInt = Field(default=2, ge=1)
    max_replicas: _StrictInt = Field(default=10, ge=1)
    target_cpu_utilization: _StrictInt = Field(default=80, ge=1, le=100)

    @model_validator(mode="after")
    def _validate_replica_bounds(self) -> K8sHpaPolicy:
        if self.max_replicas < self.min_replicas:
            raise ValueError(f"max_replicas ({self.max_replicas}) must be >= min_replicas ({self.min_replicas})")
        return self


class KubernetesPolicy(_PolicyBase):
    replicas: _StrictInt = Field(default=2, ge=1)
    namespace: _NonEmptyStr | None = None
    image: _NonEmptyStr | None = None
    image_tag: _NonEmptyStr | None = None

    @field_validator("image_tag")
    @classmethod
    def _validate_image_tag(cls, val: str | None) -> str | None:
        if val is not None and not is_valid_image_tag(val):
            raise ValueError("image_tag must match [A-Za-z0-9_][A-Za-z0-9_.-]{0,127} (OCI tag syntax)")
        return val

    port: Annotated[int, BeforeValidator(_reject_bool_for_int), Field(ge=1, le=65535)] | None = None
    service_type: Literal["ClusterIP", "NodePort", "LoadBalancer"] = "ClusterIP"
    resources: K8sResourcesPolicy = Field(default_factory=K8sResourcesPolicy)
    liveness_probe: K8sProbePolicy = Field(default_factory=K8sProbePolicy)
    readiness_probe: K8sProbePolicy = Field(default_factory=K8sProbePolicy)
    hpa: K8sHpaPolicy = Field(default_factory=K8sHpaPolicy)


class HeurixPolicy(_PolicyBase):
    engine: EnginePolicy = Field(default_factory=EnginePolicy)
    ci: CiPolicy = Field(default_factory=CiPolicy)
    jobs: dict[str, JobPolicy] = Field(default_factory=dict)
    matrix: dict[str, Any] = Field(default_factory=dict)
    overrides: dict[str, Any] = Field(default_factory=dict)
    services: ServicesPolicy = Field(default_factory=ServicesPolicy)
    env: dict[str, str] = Field(default_factory=dict)
    secrets: SecretsPolicy = Field(default_factory=SecretsPolicy)
    linters: LintersPolicy = Field(default_factory=LintersPolicy)
    kubernetes: KubernetesPolicy = Field(default_factory=KubernetesPolicy)

    @field_validator("env", mode="before")
    @classmethod
    def _coerce_env(cls, val: Any) -> Any:
        return _coerce_scalar_env_dict(val)

    @model_validator(mode="before")
    @classmethod
    def _merge_k8s_alias(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data
        normalized = dict(data)
        if "k8s" not in normalized:
            return normalized

        k8s_val = normalized.get("k8s")
        if "kubernetes" not in normalized:
            normalized["kubernetes"] = copy.deepcopy(k8s_val)
        elif isinstance(k8s_val, Mapping) and isinstance(normalized.get("kubernetes"), Mapping):
            normalized["kubernetes"] = _deep_merge_dicts(k8s_val, normalized["kubernetes"])
        return normalized

    @classmethod
    def from_raw(cls, raw_cfg: Mapping[str, Any] | None) -> HeurixPolicy:
        """Zero-exception helper returning a validated HeurixPolicy from raw dict config."""
        policy, _ = parse_heurix_policy(raw_cfg)
        return policy


def _resolve_dict_key(mapping: dict[Any, Any], segment: Any) -> tuple[bool, Any]:
    if segment in mapping:
        return True, segment
    if isinstance(segment, str) and segment in _LOC_KEY_FALLBACKS:
        alt = _LOC_KEY_FALLBACKS[segment]
        if alt in mapping:
            return True, alt
    return False, segment


def _prune_loc(target: Any, loc: tuple[Any, ...]) -> bool:
    """Delete a single invalid leaf entry addressed by Pydantic ValidationError loc."""
    if not loc:
        return False

    cur = target
    for segment in loc[:-1]:
        if isinstance(cur, dict):
            found, resolved_key = _resolve_dict_key(cur, segment)
            if not found:
                return False
            cur = cur[resolved_key]
        elif isinstance(cur, list) and isinstance(segment, int) and 0 <= segment < len(cur):
            cur = cur[segment]
        else:
            return False

    leaf = loc[-1]
    if isinstance(cur, dict):
        found, resolved_key = _resolve_dict_key(cur, leaf)
        if not found:
            return False
        del cur[resolved_key]
        return True
    if isinstance(cur, list) and isinstance(leaf, int) and 0 <= leaf < len(cur):
        del cur[leaf]
        return True
    return False


def _count_nodes(obj: Any) -> int:
    if isinstance(obj, Mapping):
        return 1 + sum(_count_nodes(v) for v in obj.values())
    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        return 1 + sum(_count_nodes(v) for v in obj)
    return 1


def _error_sort_key(err: Mapping[str, Any]) -> tuple[Any, ...]:
    loc = tuple(err.get("loc") or ())
    is_list_leaf = 1 if (loc and isinstance(loc[-1], int)) else 0
    path_key = tuple((-part if isinstance(part, int) else 0, str(part)) for part in loc)
    return (is_list_leaf, -len(loc), path_key)


def parse_heurix_policy(raw_cfg: Mapping[str, Any] | None) -> tuple[HeurixPolicy, list[str]]:
    """
    Validate `.heurix.toml` mapping into a typed `HeurixPolicy`.

    Emits non-fatal warnings for unknown top-level keys (excluding `[k8s]`) and
    iteratively prunes invalid leaf entries so every valid policy section survives.
    """
    if raw_cfg is None:
        return HeurixPolicy(), []
    if not isinstance(raw_cfg, Mapping):
        return HeurixPolicy(), ["Warning: Invalid .heurix.toml root: expected a table; using defaults."]

    warnings: list[str] = []
    for key in raw_cfg:
        if key not in _KNOWN_TOP_LEVEL_KEYS:
            warnings.append(f"Warning: Unknown .heurix.toml section '{key}'; ignoring.")

    candidate: dict[str, Any] = copy.deepcopy(dict(raw_cfg))

    if (
        "k8s" in candidate
        and "kubernetes" in candidate
        and not isinstance(candidate["k8s"], Mapping)
        and isinstance(candidate["kubernetes"], Mapping)
    ):
        warnings.append("Warning: Invalid .heurix.toml field 'k8s': Input should be a valid dictionary; ignoring.")
        candidate.pop("k8s", None)

    max_iterations = max(32, _count_nodes(candidate) + 8)
    for _ in range(max_iterations):
        try:
            policy = HeurixPolicy.model_validate(candidate)
            return policy, warnings
        except ValidationError as exc:
            errors = sorted(exc.errors(), key=_error_sort_key)
            changed = False
            seen_locs: set[tuple[Any, ...]] = set()

            for err in errors:
                loc = tuple(err.get("loc") or ())
                if not loc:
                    continue
                if loc in seen_locs:
                    continue
                seen_locs.add(loc)

                pruned = _prune_loc(candidate, loc)
                display_loc = loc
                if not pruned and loc[0] == "kubernetes":
                    k8s_loc = ("k8s", *loc[1:])
                    pruned = _prune_loc(candidate, k8s_loc)
                    if pruned:
                        display_loc = k8s_loc

                if pruned:
                    field_path = ".".join(str(part) for part in display_loc)
                    msg = str(err.get("msg", "invalid value"))
                    warnings.append(f"Warning: Invalid .heurix.toml field '{field_path}': {msg}; using default.")
                    changed = True

            if not changed:
                warnings.append(
                    f"Warning: Invalid .heurix.toml configuration ({exc.error_count()} errors); using defaults."
                )
                return HeurixPolicy(), warnings

    warnings.append("Warning: Exhausted .heurix.toml validation retries; using defaults.")
    return HeurixPolicy(), warnings


_LANG_KEY_ALIASES: dict[str, str] = {
    "python": "python",
    "python-version": "python",
    "python_version": "python",
    "node": "node",
    "nodejs": "node",
    "node-version": "node",
    "node_version": "node",
    "go": "go",
    "golang": "go",
    "go-version": "go",
    "go_version": "go",
    "rust": "rust",
    "rust-version": "rust",
    "rust_version": "rust",
    "toolchain": "rust",
    "cpp": "cpp",
    "c++": "cpp",
}

_SERVICE_EXCLUDE_ALIASES: dict[str, str] = {
    "postgresql": "postgres",
    "mongo": "mongodb",
}


def normalize_service_name(name: str) -> str:
    """Normalize a backing service name using canonical policy exclusion aliases."""
    cleaned = str(name).strip().lower()
    return _SERVICE_EXCLUDE_ALIASES.get(cleaned, cleaned)


def normalize_string_list(val: Any) -> list[str]:
    """Normalize a TOML scalar or sequence into a deduplicated list of non-empty strings."""
    if isinstance(val, (list, tuple)):
        result: list[str] = []
        for item in val:
            if isinstance(item, bool) or not isinstance(item, (str, int, float)):
                continue
            text = str(item).strip()
            if text and text not in result:
                result.append(text)
        return result

    if isinstance(val, (str, int, float)) and not isinstance(val, bool):
        text = str(val).strip()
        return [text] if text else []

    return []


def apply_language_version_policy(context: ProjectContext, raw_key: str, raw_val: Any) -> None:
    """
    Apply a `.heurix.toml` `[matrix]` or `[overrides]` entry across all matching
    `LanguageContext` and `MonorepoPackage` entries without `str(list)` coercion.
    """
    key = str(raw_key).strip().lower()
    if not key:
        return

    if key == "os":
        os_vals = normalize_string_list(raw_val)
        if len(os_vals) >= 2:
            context.matrix_os = os_vals
            context.add_explain(f"Set OS build matrix: {os_vals} (via .heurix.toml)")
        elif len(os_vals) == 1:
            context.matrix_os = []
            context.runner = os_vals[0]
            context.add_explain(f"Set CI runner to '{context.runner}' (via .heurix.toml)")
        return

    lang_name = _LANG_KEY_ALIASES.get(key, key)
    matching_langs = context.get_languages(lang_name)
    matching_pkgs = [pkg for pkg in context.monorepo_packages if pkg.language.lower() == lang_name]
    if not matching_langs and not matching_pkgs:
        return

    if isinstance(raw_val, list):
        versions = normalize_string_list(raw_val)
        if not versions:
            return
        if len(versions) >= 2:
            latest = versions[-1]
            for lang_ctx in matching_langs:
                lang_ctx.matrix_versions = list(versions)
                lang_ctx.runtime_version = latest
                lang_ctx.version_source = ".heurix.toml"
            for pkg in matching_pkgs:
                pkg.matrix_versions = list(versions)
                pkg.runtime_version = latest
                pkg.version_source = ".heurix.toml"
            context.add_explain(f"Set {lang_name} matrix versions: {versions} (via .heurix.toml)")
        else:
            version_str = versions[0]
            for lang_ctx in matching_langs:
                lang_ctx.runtime_version = version_str
                lang_ctx.version_source = ".heurix.toml"
                lang_ctx.matrix_versions = []
            for pkg in matching_pkgs:
                pkg.runtime_version = version_str
                pkg.version_source = ".heurix.toml"
                pkg.matrix_versions = []
            context.add_explain(f"Overrode {lang_name} version to '{version_str}' (via .heurix.toml)")
        return

    if isinstance(raw_val, (str, int, float)) and not isinstance(raw_val, bool):
        version_str = str(raw_val).strip()
        if not version_str:
            return
        for lang_ctx in matching_langs:
            old_ver = lang_ctx.runtime_version
            lang_ctx.runtime_version = version_str
            lang_ctx.version_source = ".heurix.toml"
            lang_ctx.matrix_versions = []
            context.add_explain(f"Overrode {lang_name} version: {old_ver} -> {version_str} (via .heurix.toml)")
        for pkg in matching_pkgs:
            pkg.runtime_version = version_str
            pkg.version_source = ".heurix.toml"
            pkg.matrix_versions = []


def apply_policy_to_context(
    context: ProjectContext,
    policy: HeurixPolicy,
    raw_config: Mapping[str, Any] | None = None,
) -> None:
    """
    Mutate `ProjectContext` deterministically from validated `HeurixPolicy` rules.

    Runs inside `analyze_repository()` after monorepo reconciliation so `hx scan`,
    `hx generate`, and `hx check` share an identical policy-governed IR.
    """
    # 1. Explicit [engine].runner (applied before [matrix] so single-entry [matrix].os still wins)
    raw_engine = raw_config.get("engine") if isinstance(raw_config, Mapping) else None
    engine_runner_explicit = (
        "runner" in policy.engine.model_fields_set
        or policy.engine.runner != "ubuntu-latest"
        or (
            isinstance(raw_engine, Mapping)
            and isinstance(raw_engine.get("runner"), str)
            and bool(raw_engine["runner"].strip())
            and policy.engine.runner == raw_engine["runner"].strip()
        )
    )
    if engine_runner_explicit:
        context.runner = policy.engine.runner
        context.add_explain(f"Set CI runner to '{context.runner}' (via .heurix.toml)")

    # 2. Apply [matrix] first, then [overrides] second so scalar pins collapse matrix lists
    for raw_key, raw_val in policy.matrix.items():
        apply_language_version_policy(context, str(raw_key), raw_val)

    for raw_key, raw_val in policy.overrides.items():
        apply_language_version_policy(context, str(raw_key), raw_val)

    # 3. Apply [services].exclude with normalized alias mapping
    excluded_services = {
        normalize_service_name(item) for item in policy.services.exclude if isinstance(item, str) and item.strip()
    }
    if excluded_services and context.services:
        kept_services = []
        for svc in context.services:
            if normalize_service_name(svc.name) in excluded_services:
                context.add_explain(f"Excluded service '{svc.name}' via .heurix.toml [services].exclude")
            else:
                kept_services.append(svc)
        context.services = kept_services

    # 4. Apply [linters] toggles across LanguageContext and MonorepoPackage
    for lang_ctx in context.languages:
        if lang_ctx.lint_cmd and not policy.linters.is_enabled_for(lang_ctx.language):
            lang_ctx.lint_cmd = None
            context.add_explain(
                f"Disabled linter for {lang_ctx.language} ({lang_ctx.working_dir}) via .heurix.toml [linters]"
            )
    for pkg in context.monorepo_packages:
        if pkg.lint_cmd and not policy.linters.is_enabled_for(pkg.language):
            pkg.lint_cmd = None
            context.add_explain(f"Disabled linter for {pkg.language} package '{pkg.path}' via .heurix.toml [linters]")

    # 5. Apply [env] overrides while enforcing SEC-02 sensitive keyword redaction
    for raw_key, val in policy.env.items():
        env_key = str(raw_key).strip()
        if not env_key:
            continue
        if is_sensitive_env_key(env_key):
            context.env_vars.pop(env_key, None)
            context.add_explain(
                f"Warning: SEC-02 blocked sensitive key '{env_key}' from .heurix.toml [env]; declare it under [secrets] instead."
            )
            continue
        context.env_vars[env_key] = str(val)

    # 6. Apply [secrets].deploy first, then [secrets].test (SEC-03 test/deploy isolation)
    for raw_secret in policy.secrets.deploy:
        secret_key = str(raw_secret).strip()
        if not secret_key:
            continue
        if secret_key not in context.deployment_secrets:
            context.deployment_secrets.append(secret_key)
        if secret_key in context.test_secrets:
            context.test_secrets = [s for s in context.test_secrets if s != secret_key]
        context.env_vars.pop(secret_key, None)

    deployment_set = set(context.deployment_secrets)
    if deployment_set and context.test_secrets:
        context.test_secrets = [s for s in context.test_secrets if s not in deployment_set]

    for raw_secret in policy.secrets.test:
        secret_key = str(raw_secret).strip()
        if not secret_key:
            continue
        if secret_key in deployment_set or is_deployment_secret_key(secret_key):
            context.add_explain(
                f"Warning: SEC-03 blocked deployment secret '{secret_key}' from .heurix.toml [secrets].test."
            )
            continue
        if secret_key not in context.test_secrets:
            context.test_secrets.append(secret_key)
        context.env_vars.pop(secret_key, None)

    context.sync_required_secrets()
