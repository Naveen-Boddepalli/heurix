"""
Backing-service reconciliation.

Language detectors infer services from client libraries (e.g. ``psycopg`` ->
``postgres``) while the Docker detector adds services declared in compose files
under the user's own names (e.g. ``db``). Left alone, a repo with both produces
two Postgres containers that both bind host port 5432, so the CI job cannot
start. This pass runs after every detector and:

1. Merges services of the same kind and scope into one entry.
2. Makes sure every Postgres service has credentials, because the official
   image refuses to start without ``POSTGRES_PASSWORD``.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from heurix.core.context import ProjectContext, ServiceRequirement
from heurix.core.indexer import RepoIndexer
from heurix.detectors.python_detector import _extract_pg_credentials

COMPOSE_FILENAMES = frozenset(
    {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
)

_POSTGRES_IMAGES = frozenset(
    {"postgres", "postgresql", "postgis", "pgvector", "timescaledb", "timescaledb-ha"}
)
_REDIS_IMAGES = frozenset({"redis", "redis-stack", "redis-stack-server", "valkey", "keydb"})
_MONGO_IMAGES = frozenset({"mongo", "mongodb-community-server"})

_NAME_KINDS = {
    "postgres": "postgres",
    "postgresql": "postgres",
    "redis": "redis",
    "mongo": "mongodb",
    "mongodb": "mongodb",
}

_PG_ENV_KEYS = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")

_DEFAULT_PORTS = {"postgres": 5432, "redis": 6379, "mongodb": 27017}


def _image_basename(image: str) -> str:
    """Return the repository basename of an image ref, without registry, tag or digest."""
    ref = image.strip().lower().split("@", 1)[0]
    last = ref.rsplit("/", 1)[-1]
    return last.split(":", 1)[0]


def service_kind(svc: ServiceRequirement) -> str | None:
    """Classify a service as 'postgres', 'redis' or 'mongodb', or None if unknown."""
    base = _image_basename(svc.image or "")
    if base in _POSTGRES_IMAGES:
        return "postgres"
    if base in _REDIS_IMAGES:
        return "redis"
    if base in _MONGO_IMAGES:
        return "mongodb"
    return _NAME_KINDS.get(svc.name.strip().lower())


def is_compose_service(svc: ServiceRequirement) -> bool:
    return PurePosixPath((svc.source_file or "").replace("\\", "/")).name in COMPOSE_FILENAMES


def _merge_compose_into(target: ServiceRequirement, compose: ServiceRequirement) -> None:
    """Adopt the compose service's image and explicit env on an inferred service."""
    target.image = compose.image or target.image
    for key, value in compose.env.items():
        target.env[key] = value


def _dedupe_services(context: ProjectContext) -> None:
    """Collapse services that share a kind and a scope into a single entry."""
    services = context.services
    inferred_by_kind: dict[str, list[ServiceRequirement]] = {}
    for svc in services:
        kind = service_kind(svc)
        if kind and not is_compose_service(svc):
            inferred_by_kind.setdefault(kind, []).append(svc)

    kept: list[ServiceRequirement] = []
    seen: dict[tuple[str, str | None], ServiceRequirement] = {}
    for svc in services:
        kind = service_kind(svc)
        if kind is None:
            kept.append(svc)
            continue

        if is_compose_service(svc) and inferred_by_kind.get(kind):
            # The compose file states which image the user runs locally; keep that,
            # but keep the inferred entries, which carry the canonical name and the
            # package scoping used by monorepo jobs.
            names = []
            for target in inferred_by_kind[kind]:
                _merge_compose_into(target, svc)
                names.append(target.name)
            context.add_explain(
                f"Merged compose service '{svc.name}' ({svc.image}) into inferred "
                f"service '{names[0]}' to avoid duplicate {kind} containers"
            )
            continue

        key = (kind, svc.package_path)
        if key in seen:
            context.add_explain(
                f"Dropped duplicate {kind} service '{svc.name}'; CI already runs "
                f"'{seen[key].name}' on the same port"
            )
            continue
        seen[key] = svc
        kept.append(svc)

    context.services = kept


def _ensure_postgres_credentials(context: ProjectContext, indexer: RepoIndexer | None) -> None:
    """Give Postgres services the credentials the official image needs to start."""
    defaults: tuple[str, str, str] | None = None
    for svc in context.services:
        if service_kind(svc) != "postgres":
            continue
        env = svc.env
        if "POSTGRES_PASSWORD_FILE" in env and "POSTGRES_PASSWORD" not in env:
            # Secret files from the local compose setup do not exist on CI runners.
            env.pop("POSTGRES_PASSWORD_FILE")
        if env.get("POSTGRES_PASSWORD") or env.get("POSTGRES_HOST_AUTH_METHOD") == "trust":
            continue
        if "POSTGRES_PASSWORD" in env:
            # The image rejects an empty password just like a missing one.
            env.pop("POSTGRES_PASSWORD")
        if defaults is None:
            defaults = _extract_pg_credentials(context, indexer=indexer)
        for key, value in zip(_PG_ENV_KEYS, defaults, strict=True):
            env.setdefault(key, value)
        context.add_explain(
            f"Added CI credentials to postgres service '{svc.name}' "
            "(POSTGRES_PASSWORD is required for the container to start)"
        )


def _ensure_default_ports(context: ProjectContext) -> None:
    """
    Publish the standard port for known services that declare none.

    Compose services often omit ``ports:`` because containers reach each other
    over the compose network, but on a CI runner tests connect via localhost.
    """
    for svc in context.services:
        kind = service_kind(svc)
        if kind and not svc.ports:
            svc.ports = [_DEFAULT_PORTS[kind]]
            context.add_explain(
                f"Published default port {svc.ports[0]} for {kind} service '{svc.name}' "
                "so tests can reach it on localhost"
            )


def reconcile_services(context: ProjectContext, indexer: RepoIndexer | None = None) -> None:
    """Deduplicate backing services, publish default ports, and fill Postgres credentials."""
    if not context.services:
        return
    _dedupe_services(context)
    _ensure_default_ports(context)
    _ensure_postgres_credentials(context, indexer)


_INTERPOLATION_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-(.*))?\}$|^\$([A-Za-z_][A-Za-z0-9_]*)$")


def resolve_compose_value(value: str) -> str | None:
    """
    Resolve a compose environment value for use on a CI runner.

    ``${VAR:-default}`` and ``${VAR-default}`` resolve to the default. A bare
    ``${VAR}`` or ``$VAR`` cannot be resolved without the developer's shell, so
    it returns None and the caller drops the key.
    """
    m = _INTERPOLATION_RE.match(value.strip())
    if not m:
        return value
    if m.group(2) is not None:
        return m.group(2)
    return None
