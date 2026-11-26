"""
Non-Destructive Smart Merge and AST Round-Trip Preservation.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterable
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import FoldedScalarString, LiteralScalarString

IDENTIFIER_KEYS = ("name", "package-ecosystem", "containerPort", "port", "id")
PROBE_HANDLER_KEYS = frozenset({"httpGet", "tcpSocket", "exec", "grpc"})
PRESERVE_MARKERS = ("@heurix:preserve", "@autoyaml:preserve")


class YamlSyntaxError(Exception):
    """Raised when existing or synthesized YAML content contains invalid syntax."""


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _is_comment_line(line: str) -> bool:
    return line.strip().startswith("#")


def _line_has_preserve_marker(line: str) -> bool:
    hash_at = line.find("#")
    return hash_at >= 0 and any(m in line[hash_at:] for m in PRESERVE_MARKERS)


def _comment_block_start(raw_lines: list[str], line_no: int, max_col: int) -> int:
    """First line of the comment/blank block directly above `line_no` (comments no deeper than `max_col`)."""
    k = line_no - 1
    while 0 <= k < len(raw_lines):
        line = raw_lines[k]
        if not line.strip() or (_is_comment_line(line) and _line_indent(line) <= max_col):
            k -= 1
            continue
        break
    return k + 1


# Step names Heurix gives the test steps of a generated job: `Run tests (python)`, `Run E2E tests (playwright)`.
_GENERATED_TEST_STEP_RE = re.compile(r"^run (?:e2e )?tests \(.+\)$")


def _is_generated_job_id(job_id: Any) -> bool:
    """True for the job IDs Heurix gives test jobs: `test`, `test-<language|package>`, `test-e2e`."""
    jid = str(job_id)
    return jid == "test" or jid.startswith("test-")


def _job_steps(job: Any) -> list[Any]:
    steps = job.get("steps") if isinstance(job, dict) else None
    return list(steps) if isinstance(steps, (list, CommentedSeq)) else []


def _generated_test_keys(job: Any) -> frozenset[str]:
    """Names of the steps that mark `job` as a Heurix test job and say what it tests."""
    names = (_normalize_step_name(step) for step in _job_steps(job))
    return frozenset(n for n in names if n is not None and _GENERATED_TEST_STEP_RE.match(n))


def _has_generated_checkout(job: Any) -> bool:
    return any(
        _normalize_step_uses(step) == "actions/checkout" and _normalize_step_name(step) == "checkout repository"
        for step in _job_steps(job)
    )


def _job_working_dir(job: Any) -> str:
    defaults = job.get("defaults") if isinstance(job, dict) else None
    run = defaults.get("run") if isinstance(defaults, dict) else None
    wd = run.get("working-directory") if isinstance(run, dict) else None
    if wd is None:
        return "."
    return str(wd).strip().strip("/") or "."


def _exact_step_matches(existing_steps: list[Any], new_steps: list[Any]) -> int:
    """Count existing steps whose (uses + name) or (name + run) identity also appears in `new_steps`."""

    def _ids(step: Any) -> set[tuple[str, str, str]]:
        uses, name, run = _normalize_step_uses(step), _normalize_step_name(step), _normalize_step_run(step)
        ids: set[tuple[str, str, str]] = set()
        if uses is not None and name is not None:
            ids.add(("uses", uses, name))
        if name is not None and run is not None:
            ids.add(("run", name, run))
        return ids

    new_ids: set[tuple[str, str, str]] = set()
    for step in new_steps:
        new_ids |= _ids(step)
    return sum(1 for step in existing_steps if _ids(step) & new_ids)


def _normalize_step_uses(step: Any) -> str | None:
    """Return normalized action repository/path (without @ref) for a workflow step."""
    if not isinstance(step, (dict, CommentedMap)):
        return None
    uses = step.get("uses")
    if uses is None:
        return None
    val = str(uses).strip()
    if not val:
        return None
    return val.split("@", 1)[0].strip().lower()


_SHA40_REF_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_VERSION_REF_RE = re.compile(r"^v?(\d+(?:\.\d+)*)$")


def _version_key(ref: str) -> tuple[int, ...] | None:
    """Parse `v7`, `v7.1.0` or `7.1` into a comparable tuple; None for branches, SHAs and other refs."""
    match = _VERSION_REF_RE.match(ref)
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def _reconcile_action_ref(existing_uses: Any, new_uses: Any, keep_existing: bool = False) -> str | None:
    """Pick the `uses:` value for a generated step that replaces an existing step using the same action.

    Never moves an action backwards, so bumps made by Dependabot or by hand survive regeneration:
    - a commit SHA in the synthesized value comes from `[ci].action_shas` policy and always wins;
    - otherwise an existing commit SHA, branch or other non-version ref is the user's choice and is kept;
    - between two version tags the newer one is used, unless `keep_existing` (the workflow is in
      a lockfile, where any changed ref fails the run until the lock is updated) keeps the existing one.
    Returns None when the synthesized value should be used unchanged.
    """
    if not isinstance(existing_uses, str) or not isinstance(new_uses, str):
        return None
    if "@" not in existing_uses or "@" not in new_uses:
        return None
    ex_action, ex_ref = (part.strip() for part in existing_uses.split("@", 1))
    new_action, new_ref = (part.strip() for part in new_uses.split("@", 1))
    if ex_action.lower() != new_action.lower() or not ex_ref or ex_ref == new_ref:
        return None
    if _SHA40_REF_RE.match(new_ref):
        return None
    if keep_existing:
        return f"{new_action}@{ex_ref}"
    ex_key, new_key = _version_key(ex_ref), _version_key(new_ref)
    if ex_key is not None and new_key is not None:
        return f"{new_action}@{ex_ref}" if ex_key > new_key else None
    return f"{new_action}@{ex_ref}"


def _normalize_step_name(step: Any) -> str | None:
    """Return normalized lowercase name for a workflow step."""
    if not isinstance(step, (dict, CommentedMap)):
        return None
    name = step.get("name")
    if name is None:
        return None
    val = str(name).strip().lower()
    return val if val else None


def _normalize_step_run(step: Any) -> str | None:
    """Return whitespace-normalized run command for a workflow step."""
    if not isinstance(step, (dict, CommentedMap)):
        return None
    run = step.get("run")
    if run is None:
        return None
    val = " ".join(str(run).split())
    return val if val else None


_HPA_METRIC_SUBKEYS = ("resource", "pods", "object", "external", "containerResource")


def _extract_hpa_metric_key(item: Any) -> tuple[str, str] | None:
    """Extract (type, metric_name) identity for Kubernetes HPA v2 spec.metrics items."""
    if not isinstance(item, (dict, CommentedMap)) or "type" not in item:
        return None
    metric_type = item.get("type")
    if metric_type is None:
        return None
    for subkey in _HPA_METRIC_SUBKEYS:
        submetric = item.get(subkey)
        if isinstance(submetric, (dict, CommentedMap)):
            metric_name = submetric.get("name")
            if metric_name is None and isinstance(submetric.get("metric"), (dict, CommentedMap)):
                metric_name = submetric["metric"].get("name")
            if metric_name is not None and str(metric_name).strip():
                return (str(metric_type), str(metric_name))
    return None


def _get_entity_identifier(item: Any) -> tuple[str, Any] | None:
    """Extract the primary identity key/value pair from a YAML mapping sequence item."""
    if isinstance(item, (dict, CommentedMap)):
        hpa_key = _extract_hpa_metric_key(item)
        if hpa_key is not None:
            return ("__hpa_metric__", hpa_key)
        for key in IDENTIFIER_KEYS:
            if key in item:
                return (key, item[key])
    return None


def _sequence_items_match(ex_item: Any, new_item: Any, ident_key: str, ident_val: Any) -> bool:
    """Return True if an existing sequence mapping represents the same entity as new_item."""
    if ident_key == "__hpa_metric__":
        return _extract_hpa_metric_key(ex_item) == ident_val

    if not isinstance(ex_item, (dict, CommentedMap)) or ex_item.get(ident_key) != ident_val:
        return False

    # Disambiguate Dependabot entries targeting the same ecosystem in different directories
    if ident_key == "package-ecosystem":
        for dir_key in ("directory", "directories"):
            if dir_key in ex_item and dir_key in new_item:
                if ex_item.get(dir_key) != new_item.get(dir_key):
                    return False

    # Disambiguate Kubernetes port definitions sharing a port number on distinct protocols
    if ident_key in ("port", "containerPort"):
        if "protocol" in ex_item and "protocol" in new_item:
            if ex_item.get("protocol") != new_item.get("protocol"):
                return False

    return True


def deep_merge_nodes(existing: Any, new: Any) -> Any:
    """
    Recursively merge 'new' into 'existing' in-place.
    Precedence: existing user-defined values and attached comments are preserved.
    Missing keys and unmatched sequence entities are inserted.
    """
    if isinstance(existing, (dict, CommentedMap)) and isinstance(new, (dict, CommentedMap)):
        has_probe_handler = any(pk in existing for pk in PROBE_HANDLER_KEYS)
        for k, v in new.items():
            if k not in existing:
                if has_probe_handler and k in PROBE_HANDLER_KEYS:
                    continue
                existing[k] = v
            elif existing[k] is None and isinstance(v, (dict, CommentedMap, list, CommentedSeq)):
                existing[k] = v
            else:
                deep_merge_nodes(existing[k], v)
        return existing

    if isinstance(existing, (list, CommentedSeq)) and isinstance(new, (list, CommentedSeq)):
        for new_item in new:
            ident = _get_entity_identifier(new_item)
            if ident is not None:
                ident_key, ident_val = ident
                matched_target = None
                for ex_item in existing:
                    if _sequence_items_match(ex_item, new_item, ident_key, ident_val):
                        matched_target = ex_item
                        break
                if matched_target is not None:
                    deep_merge_nodes(matched_target, new_item)
                else:
                    existing.append(new_item)
            else:
                if new_item not in existing:
                    existing.append(new_item)
        return existing

    # Scalar or mismatched types: preserve existing user value
    return existing


def _get_doc_identity(doc: Any) -> tuple[str | None, str | None] | None:
    """Extract (kind, metadata.name) identity for Kubernetes multi-document correlation."""
    if not isinstance(doc, (dict, CommentedMap)):
        return None
    kind = doc.get("kind")
    metadata = doc.get("metadata")
    name = metadata.get("name") if isinstance(metadata, (dict, CommentedMap)) else None
    if kind is None and name is None:
        return None
    return (
        str(kind) if kind is not None else None,
        str(name) if name is not None else None,
    )


class SmartMerger:
    """
    Round-trip AST merger that preserves comments, custom jobs, and
    # @heurix:preserve / # @autoyaml:preserve directives.
    """

    def __init__(
        self,
        authoritative_trigger_paths: bool = False,
        policy_pinned_actions: Iterable[str] = (),
        harden: bool = False,
    ):
        # When True (`.heurix.toml` sets [ci].paths / paths_ignore), the generated
        # push/pull_request path filters replace whatever the existing file has.
        self.authoritative_trigger_paths = authoritative_trigger_paths
        # Actions whose ref `.heurix.toml` sets ([ci].action_versions / action_shas). Their generated
        # ref always wins; every other action keeps an existing ref that is newer or user-chosen.
        self.policy_pinned_actions = frozenset(a.strip().lower() for a in policy_pinned_actions)
        # `[ci] harden = true`: add the hardening keys an existing workflow lacks (top-level
        # `permissions` / `concurrency`, job `timeout-minutes`, checkout `persist-credentials`).
        # Without it, an existing workflow keeps exactly the hardening it already has.
        self.harden = harden
        # Set per file by the caller. None: the workflow isn't in actions.lock. Otherwise it is, and
        # this maps each locked action (lowercased) to its locked ref: existing refs are kept exactly
        # (`gh actions-lock --relock` and Dependabot move them) and new steps reuse a locked ref.
        self.locked_action_refs: dict[str, str] | None = None
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.indent(mapping=2, sequence=4, offset=2)
        # Match the template renderer's width so merged output never re-wraps long scalars.
        self.yaml.width = 4096
        # Human-readable notes about existing values the last merge replaced.
        self.replaced: list[str] = []
        # Hardening keys the last merge added to an existing workflow (only with `harden`).
        self.hardened: list[str] = []
        # Generated jobs the last merge renamed or removed, and `needs:` entries updated to match.
        self.retired: list[str] = []

    def merge_yaml(self, existing_content: str, new_content: str) -> str:
        """
        Merges new_content into existing_content non-destructively.
        Raises YamlSyntaxError if existing_content cannot be parsed.
        """
        self.replaced = []
        self.hardened = []
        self.retired = []
        if not existing_content.strip():
            return new_content

        try:
            existing_docs = [d for d in self.yaml.load_all(existing_content) if d is not None]
        except Exception as e:
            raise YamlSyntaxError(f"Existing YAML has invalid syntax and cannot be safely merged: {e}") from e

        try:
            new_docs = [d for d in self.yaml.load_all(new_content) if d is not None]
        except Exception as e:
            raise YamlSyntaxError(f"Synthesized YAML has invalid syntax and cannot be merged: {e}") from e

        if not existing_docs or not new_docs:
            return new_content

        # Multi-document YAML path
        if len(existing_docs) > 1 or len(new_docs) > 1:
            merged_docs = self._merge_multidoc(existing_docs, new_docs)
            stream = io.StringIO()
            self.yaml.dump_all(merged_docs, stream)
            return stream.getvalue()

        # Single-document YAML path
        existing_doc = existing_docs[0]
        new_doc = new_docs[0]

        if not isinstance(existing_doc, (dict, CommentedMap)) or not isinstance(new_doc, (dict, CommentedMap)):
            return new_content

        # Specialized merger for GitHub Actions workflows
        if "jobs" in new_doc and "jobs" in existing_doc:
            merged_doc = self._merge_github_workflow(existing_doc, new_doc, existing_content)
        else:
            merged_doc = deep_merge_nodes(existing_doc, new_doc)

        stream = io.StringIO()
        self.yaml.dump(merged_doc, stream)
        return stream.getvalue()

    def _merge_multidoc(self, existing_docs: list[Any], new_docs: list[Any]) -> list[Any]:
        """
        Merge multi-document YAML streams by correlating documents on (kind, metadata.name).
        Existing unmatched documents are preserved; new unmatched documents are appended.
        """
        merged_docs: list[Any] = list(existing_docs)
        matched_existing_indices: set[int] = set()

        for new_doc in new_docs:
            new_ident = _get_doc_identity(new_doc)
            matched_idx: int | None = None

            if new_ident is not None:
                for idx, ex_doc in enumerate(merged_docs):
                    if idx in matched_existing_indices:
                        continue
                    if _get_doc_identity(ex_doc) == new_ident:
                        matched_idx = idx
                        break

            if matched_idx is not None:
                matched_existing_indices.add(matched_idx)
                ex_doc = merged_docs[matched_idx]
                if isinstance(ex_doc, (dict, CommentedMap)) and isinstance(new_doc, (dict, CommentedMap)):
                    merged_docs[matched_idx] = deep_merge_nodes(ex_doc, new_doc)
            else:
                if new_ident is None and new_doc in merged_docs:
                    continue
                merged_docs.append(new_doc)

        return merged_docs

    def _sync_policy_trigger_paths(self, trigger: str, ex_trigger: Any, new_trigger: Any) -> None:
        """Make an existing trigger's `paths` / `paths-ignore` match the policy-driven output."""
        for key in ("paths", "paths-ignore"):
            new_val = new_trigger.get(key)
            if key not in ex_trigger and new_val is None:
                continue
            old_val = ex_trigger.get(key)
            old_plain = list(old_val) if isinstance(old_val, (list, CommentedSeq)) else old_val
            new_plain = list(new_val) if isinstance(new_val, (list, CommentedSeq)) else new_val
            if old_plain == new_plain:
                continue
            if key in ex_trigger:
                self.replaced.append(f"on.{trigger}.{key}: {old_plain} -> {new_plain}")
            if new_val is None:
                del ex_trigger[key]
            else:
                ex_trigger[key] = new_val

    def _merge_github_workflow(
        self,
        existing: dict[Any, Any],
        new: dict[Any, Any],
        raw_existing: str,
    ) -> dict[Any, Any]:
        result = existing.copy()
        if self.locked_action_refs:
            self._prefer_locked_refs(new, self.locked_action_refs)

        # Update metadata if needed, but preserve user triggers if customized
        if "name" in new and "name" not in result:
            result["name"] = new["name"]

        # Synchronize monorepo path filters on mapping-style push/pull_request triggers
        existing_on = result.get("on")
        new_on = new.get("on")
        if isinstance(existing_on, (dict, CommentedMap)) and isinstance(new_on, (dict, CommentedMap)):
            for trigger in ("push", "pull_request"):
                ex_trigger = existing_on.get(trigger)
                new_trigger = new_on.get(trigger)
                if (
                    self.authoritative_trigger_paths
                    and isinstance(ex_trigger, (dict, CommentedMap))
                    and isinstance(new_trigger, (dict, CommentedMap))
                ):
                    self._sync_policy_trigger_paths(str(trigger), ex_trigger, new_trigger)
                elif (
                    isinstance(ex_trigger, (dict, CommentedMap))
                    and isinstance(new_trigger, (dict, CommentedMap))
                    and "paths" in new_trigger
                ):
                    existing_paths = ex_trigger.get("paths")
                    if (
                        "paths" not in ex_trigger
                        or existing_paths is None
                        or (isinstance(existing_paths, (list, CommentedSeq)) and list(existing_paths) == ["**"])
                    ):
                        ex_trigger["paths"] = new_trigger["paths"]

        if self.harden:
            for key in ("permissions", "concurrency"):
                if key in new and key not in result:
                    before = "on" if "on" in result else "jobs"
                    self._insert_near(result, key, new[key], before=before)
                    self.hardened.append(key)

        # Preserve custom jobs
        existing_jobs = result.get("jobs", CommentedMap())
        new_jobs = new.get("jobs", CommentedMap())

        merged_jobs = CommentedMap()
        renamed, removed = self._retire_generated_jobs(existing_jobs, new_jobs, raw_existing)

        # Add all new jobs
        for job_id, job_val in new_jobs.items():
            source_id = job_id if job_id in existing_jobs else renamed.get(job_id)
            if source_id is not None:
                # Merge the managed job (or the job it was generated as before a rename)
                merged_jobs[job_id] = self._merge_job(
                    existing_jobs[source_id], job_val, raw_existing, job_id=str(job_id)
                )
            else:
                merged_jobs[job_id] = job_val

        # Preserve custom user jobs (e.g. deploy, slack_notify)
        retired_ids = set(renamed.values()) | removed
        for job_id, job_val in existing_jobs.items():
            if job_id not in merged_jobs and job_id not in retired_ids:
                merged_jobs[job_id] = job_val

        self._redirect_needs(merged_jobs, {old: new for new, old in renamed.items()}, removed)
        result["jobs"] = merged_jobs
        return result

    @staticmethod
    def _job_preserve_markers(jobs: Any, raw_lines: list[str]) -> dict[str, tuple[bool, bool]] | None:
        """
        Per job ID: (marked on the job itself, marked anywhere in the job).

        The job itself is marked by a preserve directive on its key line or in the comment block
        directly above it. "Anywhere" adds directives on its keys and steps. Returns None when
        line information is unavailable.
        """
        lc = getattr(jobs, "lc", None)
        keys = list(jobs.keys()) if isinstance(jobs, dict) else []
        if lc is None or not raw_lines or not keys:
            return None
        try:
            positions = [lc.key(k) for k in keys]
        except Exception:
            return None

        above_start = [_comment_block_start(raw_lines, line_no, col) for line_no, col in positions]
        markers: dict[str, tuple[bool, bool]] = {}
        for i, (key, (line_no, col)) in enumerate(zip(keys, positions, strict=True)):
            if i + 1 < len(positions):
                end = above_start[i + 1]
            else:
                # Last job: its lines run until a line left of or level with its key.
                end = line_no + 1
                while end < len(raw_lines):
                    line = raw_lines[end]
                    if line.strip() and _line_indent(line) <= col and not _is_comment_line(line):
                        break
                    if _is_comment_line(line) and _line_indent(line) < col:
                        break
                    end += 1
            own = any(_line_has_preserve_marker(raw_lines[k]) for k in range(above_start[i], line_no + 1))
            anywhere = own or any(
                _line_has_preserve_marker(raw_lines[k]) for k in range(line_no + 1, min(end, len(raw_lines)))
            )
            markers[str(key)] = (own, anywhere)
        return markers

    def _retire_generated_jobs(
        self, existing_jobs: Any, new_jobs: Any, raw_existing: str
    ) -> tuple[dict[Any, Any], set[Any]]:
        """
        Find existing jobs Heurix generated under an ID it no longer produces.

        Job IDs follow the repository's shape: one root language gives `test`, several give
        `test-<language>`, monorepo packages give `test-<package>`. When that shape changes, the old
        job would otherwise be kept as if the user wrote it and run the same tests twice.

        An existing job counts as generated when its ID has that form and it has Heurix's
        `Checkout repository` step and a `Run tests (<language>)` / `Run E2E tests (<runner>)` step.
        Such a job is:
        - renamed: merged into the new job that tests the same thing, so edits and preserved steps
          or keys carry over (returned as {new_id: old_id});
        - removed: when nothing it tests is generated any more, or its package directory no longer
          has a job (returned in the set).
        A job with a preserve directive on or above its key is left as it is, and a job with one
        anywhere inside it is never removed. Jobs that don't look generated are custom and kept.
        """
        orphans = [jid for jid in existing_jobs if jid not in new_jobs and _is_generated_job_id(jid)]
        if not orphans:
            return {}, set()
        markers = self._job_preserve_markers(existing_jobs, raw_existing.splitlines())
        if markers is None:
            return {}, set()

        orphan_keys: dict[Any, frozenset[str]] = {}
        for jid in orphans:
            job = existing_jobs[jid]
            own_marker, _ = markers.get(str(jid), (True, True))
            if own_marker or not isinstance(job, dict) or not _has_generated_checkout(job):
                continue
            keys = _generated_test_keys(job)
            if keys:
                orphan_keys[jid] = keys
        if not orphan_keys:
            return {}, set()

        new_keys = {jid: _generated_test_keys(job) for jid, job in new_jobs.items() if isinstance(job, dict)}
        candidates = [jid for jid in new_keys if jid not in existing_jobs]

        scored: list[tuple[tuple[int, int, int], int, int, Any, Any]] = []
        for o_idx, old_id in enumerate(orphan_keys):
            old_job = existing_jobs[old_id]
            for c_idx, new_id in enumerate(candidates):
                shared = orphan_keys[old_id] & new_keys[new_id]
                if not shared:
                    continue
                new_job = new_jobs[new_id]
                score = (
                    len(shared),
                    _exact_step_matches(_job_steps(old_job), _job_steps(new_job)),
                    int(_job_working_dir(old_job) == _job_working_dir(new_job)),
                )
                scored.append((score, o_idx, c_idx, old_id, new_id))
        scored.sort(key=lambda item: (tuple(-s for s in item[0]), item[1], item[2]))

        renamed: dict[Any, Any] = {}
        for _, _, _, old_id, new_id in scored:
            if old_id in renamed.values() or new_id in renamed:
                continue
            renamed[new_id] = old_id
            self.retired.append(f"jobs.{old_id}: renamed to jobs.{new_id} (your changes to it are carried over)")

        produced_keys: set[str] = set().union(*new_keys.values()) if new_keys else set()
        produced_dirs = {_job_working_dir(job) for job in new_jobs.values() if isinstance(job, dict)}
        removed: set[Any] = set()
        for old_id, keys in orphan_keys.items():
            if old_id in renamed.values() or markers.get(str(old_id), (True, True))[1]:
                continue
            old_dir = _job_working_dir(existing_jobs[old_id])
            if not (keys & produced_keys) or (old_dir != "." and old_dir not in produced_dirs):
                removed.add(old_id)
                self.retired.append(f"jobs.{old_id}: removed (Heurix no longer generates this job)")
        return renamed, removed

    def _redirect_needs(self, jobs: Any, renamed: dict[Any, Any], removed: set[Any]) -> None:
        """Point `needs:` at renamed jobs and drop removed ones, so the workflow stays valid."""
        if not renamed and not removed:
            return
        for job_id, job in jobs.items():
            if not isinstance(job, dict) or "needs" not in job or self._key_has_inline_preserve(job, "needs"):
                continue
            needs = job["needs"]
            if isinstance(needs, (list, CommentedSeq)):
                updated: list[Any] = []
                for dep in needs:
                    target = renamed.get(dep, None if dep in removed else dep)
                    if target is not None and target not in updated:
                        updated.append(target)
                if updated == list(needs):
                    continue
                self.retired.append(f"jobs.{job_id}.needs: {list(needs)} -> {updated}")
                if updated:
                    needs[:] = updated
                else:
                    del job["needs"]
            elif needs in renamed:
                self.retired.append(f"jobs.{job_id}.needs: '{needs}' -> '{renamed[needs]}'")
                job["needs"] = renamed[needs]
            elif needs in removed:
                self.retired.append(f"jobs.{job_id}.needs: '{needs}' removed")
                del job["needs"]

    @staticmethod
    def _classify_preserved_steps(seq: Any, raw_lines: list[str]) -> list[tuple[bool, bool]] | None:
        """
        Read preserve directives from the source text, per step: (preserved, internal).

        `internal` means the directive sits inside the step's own lines (e.g. inline on
        `- name: X  # @heurix:preserve`) and travels with the step object. Otherwise it is
        a full-line comment directly above the step. ruamel parks that comment at the tail
        of the previous step, at a depth that depends on how that step ends (plain scalar,
        `with:` mapping, `run: |` block), so the source lines are the reliable signal.

        Returns None when line information is unavailable.
        """
        lc = getattr(seq, "lc", None)
        if lc is None or not raw_lines or not len(seq):
            return None
        try:
            positions = [lc.item(i) for i in range(len(seq))]
        except Exception:
            return None

        _indent, _is_comment, _has_marker = _line_indent, _is_comment_line, _line_has_preserve_marker

        # Comment block directly above each step: comment/blank lines no deeper than the
        # step's content column (deeper lines are the previous step's block scalar body).
        above_start: list[int] = []
        above_marker: list[bool] = []
        for line_no, content_col in positions:
            start = _comment_block_start(raw_lines, line_no, content_col)
            above_start.append(start)
            above_marker.append(any(_has_marker(raw_lines[k]) for k in range(start, min(line_no, len(raw_lines)))))

        result: list[tuple[bool, bool]] = []
        for i, (line_no, content_col) in enumerate(positions):
            if i + 1 < len(positions):
                end = above_start[i + 1]
            else:
                # Last step: its lines run until a non-comment line at or left of the dash.
                dash_col = max(content_col - 2, 0)
                end = line_no + 1
                while end < len(raw_lines):
                    line = raw_lines[end]
                    if line.strip() and not _is_comment(line) and _indent(line) <= dash_col:
                        break
                    if _is_comment(line) and _indent(line) < dash_col:
                        break
                    end += 1
            internal = any(_has_marker(raw_lines[k]) for k in range(line_no, min(end, len(raw_lines))))
            result.append((above_marker[i] or internal, internal))
        return result

    def _prefer_locked_refs(self, new_doc: Any, locked: dict[str, str]) -> None:
        """Point generated steps at the ref actions.lock already pins for the same action.

        Avoids lockfile churn (a new job's checkout reuses the locked `v7.0.1` instead of `v7`).
        Policy-pinned actions keep their configured ref.
        """
        jobs = new_doc.get("jobs") if isinstance(new_doc, dict) else None
        if not isinstance(jobs, dict):
            return
        for job in jobs.values():
            steps = job.get("steps") if isinstance(job, dict) else None
            if not isinstance(steps, list):
                continue
            for step in steps:
                action = _normalize_step_uses(step)
                if action is None or action in self.policy_pinned_actions or action not in locked:
                    continue
                current = str(step["uses"]).split("@", 1)
                if len(current) == 2 and not _SHA40_REF_RE.match(current[1].strip()):
                    step["uses"] = f"{current[0].strip()}@{locked[action]}"

    @staticmethod
    def _insert_near(
        mapping: Any, key: str, value: Any, *, before: str | None = None, after: str | None = None
    ) -> None:
        """Insert `key` just before `before` or just after `after`, appending when neither key exists."""
        keys = list(mapping.keys())
        if before is not None and before in keys:
            pos = keys.index(before)
        elif after is not None and after in keys:
            pos = keys.index(after) + 1
        else:
            pos = len(keys)
        if isinstance(mapping, CommentedMap):
            mapping.insert(pos, key, value)
        else:
            mapping[key] = value

    def _reconcile_checkout_credentials(self, existing_step: Any, new_step: Any, job_id: str) -> Any:
        """Settle `persist-credentials` on a generated checkout step that replaces an existing one.

        An explicit value in the existing step is kept (a job that pushes needs `true`). Otherwise the
        generated `false` is added only with `harden`, so an existing workflow doesn't change silently.
        """
        if _normalize_step_uses(new_step) != "actions/checkout":
            return new_step
        new_with = new_step.get("with")
        if not isinstance(new_with, dict) or "persist-credentials" not in new_with:
            return new_step
        ex_with = existing_step.get("with") if isinstance(existing_step, dict) else None
        if isinstance(ex_with, dict) and "persist-credentials" in ex_with:
            kept = ex_with["persist-credentials"]
            if new_with["persist-credentials"] == kept:
                return new_step
            new_step, new_with = new_step.copy(), new_with.copy()
            new_with["persist-credentials"] = kept
            new_step["with"] = new_with
            return new_step
        if self.harden:
            label = str(new_step.get("name") or "actions/checkout")
            self.hardened.append(f"jobs.{job_id}.steps['{label}'].with.persist-credentials")
            return new_step
        new_step, new_with = new_step.copy(), new_with.copy()
        del new_with["persist-credentials"]
        if new_with:
            new_step["with"] = new_with
        else:
            del new_step["with"]
        return new_step

    @staticmethod
    def _carry_uses_eol_comment(existing_step: Any, new_step: Any) -> None:
        """Copy the inline comment on an existing `uses:` line (e.g. `# v10` after a SHA) to `new_step`."""
        if not isinstance(existing_step, CommentedMap) or not isinstance(new_step, CommentedMap):
            return
        entry = existing_step.ca.items.get("uses")
        token = entry[2] if entry and len(entry) > 2 else None
        value = getattr(token, "value", None)
        if not isinstance(value, str) or value.startswith("\n"):
            return
        first_line = value.split("\n", 1)[0].strip()
        if first_line.startswith("#") and not any(m in first_line for m in PRESERVE_MARKERS):
            new_step.ca.items.pop("uses", None)
            new_step.yaml_add_eol_comment(first_line, "uses")

    @staticmethod
    def _strip_parked_next_step_marker(step: Any) -> None:
        """
        Remove a full-line preserve directive that ruamel parked at the tail of `step`.

        That line was written above the *next* step. Left in place it is emitted again
        after this step wherever it lands, duplicating the re-attached directive or
        freezing whichever step follows it. The first line of a token on a plain scalar
        is an inline comment on that key and is kept.
        """
        node: Any = step
        while isinstance(node, (CommentedMap, CommentedSeq)) and len(node):
            if isinstance(node, CommentedMap):
                last_key: Any = list(node.keys())[-1]
            else:
                last_key = len(node) - 1
            tokens = node.ca.items.get(last_key) if node.ca and node.ca.items else None
            if tokens:
                value = node[last_key]
                first_line_inline = not isinstance(value, (LiteralScalarString, FoldedScalarString))
                for t_idx, token in enumerate(tokens):
                    val = getattr(token, "value", None)
                    if not val or not any(m in val for m in PRESERVE_MARKERS):
                        continue
                    lines = val.split("\n")
                    kept = [
                        line
                        for n, line in enumerate(lines)
                        if (n == 0 and first_line_inline and not val.startswith("\n"))
                        or not (line.strip().startswith("#") and any(m in line for m in PRESERVE_MARKERS))
                    ]
                    new_val = "\n".join(kept)
                    if not new_val.strip():
                        tokens[t_idx] = None
                    else:
                        token.value = new_val
            node = node[last_key]

    def _match_steps(self, existing_steps: list[Any], new_steps: list[Any]) -> tuple[dict[int, int], dict[int, int]]:
        """
        Match existing workflow steps to synthesized new steps 1-to-1
        by compound identity, uses action base, step name, or run command.
        """
        ex_sig = [(_normalize_step_uses(s), _normalize_step_name(s), _normalize_step_run(s)) for s in existing_steps]
        new_sig = [(_normalize_step_uses(s), _normalize_step_name(s), _normalize_step_run(s)) for s in new_steps]

        ex_to_new: dict[int, int] = {}
        new_to_ex: dict[int, int] = {}

        def _run_pass(predicate: Any) -> None:
            for i, es in enumerate(ex_sig):
                if i in ex_to_new:
                    continue
                for j, ns in enumerate(new_sig):
                    if j in new_to_ex:
                        continue
                    if predicate(es, ns):
                        ex_to_new[i] = j
                        new_to_ex[j] = i
                        break

        # Pass 1: exact compound identity (uses + name, or name + run)
        _run_pass(
            lambda e, n: (
                (e[0] is not None and e[0] == n[0] and e[1] is not None and e[1] == n[1])
                or (e[1] is not None and e[1] == n[1] and e[2] is not None and e[2] == n[2])
            )
        )
        # Pass 2: action repository match (handles @v3 -> @v4 and label changes)
        _run_pass(lambda e, n: e[0] is not None and e[0] == n[0])
        # Pass 3: step name match
        _run_pass(lambda e, n: e[1] is not None and e[1] == n[1])
        # Pass 4: run command match
        _run_pass(lambda e, n: e[2] is not None and e[2] == n[2])

        return ex_to_new, new_to_ex

    @staticmethod
    def _key_has_inline_preserve(mapping: Any, key: str) -> bool:
        """True if `key: value  # @heurix:preserve` marks this key on its own line."""
        ca = getattr(mapping, "ca", None)
        tokens = ca.items.get(key) if ca is not None else None
        if not tokens or len(tokens) < 3 or tokens[2] is None:
            return False
        # ruamel folds following full-line comments into the same token; only the
        # first line is the inline comment on this key.
        inline = str(getattr(tokens[2], "value", "")).split("\n", 1)[0]
        return any(m in inline for m in PRESERVE_MARKERS)

    @staticmethod
    def _plain(value: Any) -> Any:
        """Convert ruamel containers to plain Python values for comparison."""
        if isinstance(value, dict):
            return {str(k): SmartMerger._plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [SmartMerger._plain(v) for v in value]
        return value

    def _sync_key(self, merged_job: Any, existing_job: Any, new_job: Any, key: str, job_id: str) -> None:
        """Take `key` from the synthesized job unless the user marked it preserved."""
        if key in existing_job and self._key_has_inline_preserve(existing_job, key):
            return
        if key in new_job:
            old_val = existing_job.get(key)
            new_val = new_job[key]
            if (
                key in existing_job
                and not isinstance(old_val, (dict, list))
                and self._plain(old_val) != self._plain(new_val)
            ):
                self.replaced.append(f"jobs.{job_id}.{key}: '{old_val}' -> '{new_val}'")
            merged_job[key] = new_val
        elif key == "services":
            merged_job.pop(key, None)

    def _merge_job(self, existing_job: Any, new_job: Any, raw_existing: str, job_id: str = "") -> Any:
        if not isinstance(existing_job, dict) or not isinstance(new_job, dict):
            return new_job

        merged_job = existing_job.copy()
        # Update runs-on, services, defaults, needs, and strategy from new_job.
        # A trailing `# @heurix:preserve` on the key line keeps the user's value.
        self._sync_key(merged_job, existing_job, new_job, "runs-on", job_id)
        if self.harden and "timeout-minutes" in new_job and "timeout-minutes" not in merged_job:
            self._insert_near(merged_job, "timeout-minutes", new_job["timeout-minutes"], after="runs-on")
            self.hardened.append(f"jobs.{job_id}.timeout-minutes")
        self._sync_key(merged_job, existing_job, new_job, "services", job_id)

        if "defaults" in new_job:
            new_defaults = new_job["defaults"]
            ex_defaults = merged_job.get("defaults")
            if isinstance(ex_defaults, (dict, CommentedMap)) and isinstance(new_defaults, (dict, CommentedMap)):
                merged_defaults = ex_defaults.copy()
                for k, v in new_defaults.items():
                    if (
                        k == "run"
                        and isinstance(merged_defaults.get("run"), (dict, CommentedMap))
                        and isinstance(v, (dict, CommentedMap))
                    ):
                        merged_run = merged_defaults["run"].copy()
                        merged_run.update(v)
                        merged_defaults["run"] = merged_run
                    else:
                        merged_defaults[k] = v
                merged_job["defaults"] = merged_defaults
            else:
                merged_job["defaults"] = new_defaults
        else:
            ex_defaults = merged_job.get("defaults")
            if isinstance(ex_defaults, (dict, CommentedMap)) and isinstance(
                ex_defaults.get("run"), (dict, CommentedMap)
            ):
                ex_run = ex_defaults["run"]
                if "working-directory" in ex_run:
                    merged_defaults = ex_defaults.copy()
                    merged_run = ex_run.copy()
                    merged_run.pop("working-directory", None)
                    if merged_run:
                        merged_defaults["run"] = merged_run
                    else:
                        merged_defaults.pop("run", None)
                    if merged_defaults:
                        merged_job["defaults"] = merged_defaults
                    else:
                        merged_job.pop("defaults", None)

        if "needs" in new_job and not self._key_has_inline_preserve(existing_job, "needs"):
            merged_job["needs"] = new_job["needs"]

        if self._key_has_inline_preserve(existing_job, "strategy"):
            pass
        elif "strategy" in new_job:
            new_strat = new_job["strategy"]
            ex_strat = merged_job.get("strategy")
            if isinstance(ex_strat, (dict, CommentedMap)) and isinstance(new_strat, (dict, CommentedMap)):
                merged_strat = ex_strat.copy()
                for k, v in new_strat.items():
                    merged_strat[k] = v
                merged_job["strategy"] = merged_strat
            else:
                merged_job["strategy"] = new_strat
        else:
            merged_job.pop("strategy", None)

        # Steps merging
        if "steps" not in new_job and "steps" not in existing_job:
            return merged_job

        new_steps = list(new_job.get("steps") or [])
        existing_steps = list(existing_job.get("steps") or [])
        existing_seq = existing_job.get("steps")

        raw_lines = raw_existing.splitlines()
        classified = self._classify_preserved_steps(existing_seq, raw_lines) if existing_steps else None
        if classified is not None and len(classified) == len(existing_steps):
            ex_preserved = [preserved for preserved, _ in classified]
            ex_internal = [internal for _, internal in classified]
        else:
            # No source positions to read directives from: keep every existing step as written
            # rather than risk overwriting one the user preserved.
            ex_preserved = [True] * len(existing_steps)
            ex_internal = [True] * len(existing_steps)

        ex_to_new, new_to_ex = self._match_steps(existing_steps, new_steps)

        # Anchor unmatched existing steps (both @preserve and unmanaged) relative to the next matched step
        anchored_before: dict[int, list[int]] = {j: [] for j in range(len(new_steps))}
        trailing_existing: list[int] = []

        for idx in range(len(existing_steps)):
            if idx in ex_to_new:
                continue
            next_new_idx: int | None = None
            for k in range(idx + 1, len(existing_steps)):
                if k in ex_to_new:
                    next_new_idx = ex_to_new[k]
                    break
            if next_new_idx is not None:
                anchored_before[next_new_idx].append(idx)
            else:
                trailing_existing.append(idx)

        final_steps = CommentedSeq()
        preserve_comment_indices: list[int] = []

        def _append_existing(ex_idx: int) -> None:
            step = existing_steps[ex_idx]
            if ex_idx < len(existing_steps) - 1:
                # The directive above the next step is re-attached below if that step is kept.
                self._strip_parked_next_step_marker(step)
            pos = len(final_steps)
            final_steps.append(step)
            if ex_preserved[ex_idx] and not ex_internal[ex_idx]:
                preserve_comment_indices.append(pos)

        for j, new_step in enumerate(new_steps):
            for ex_idx in anchored_before[j]:
                _append_existing(ex_idx)

            if j in new_to_ex and ex_preserved[new_to_ex[j]]:
                # Preserve existing customized step rather than overwriting with synthesized step
                _append_existing(new_to_ex[j])
            else:
                if j in new_to_ex:
                    existing_step = existing_steps[new_to_ex[j]]
                    old_run = _normalize_step_run(existing_step)
                    new_run = _normalize_step_run(new_step)
                    if old_run and new_run and old_run != new_run:
                        label = str(new_step.get("name") or new_run)
                        self.replaced.append(f"jobs.{job_id}.steps['{label}'].run: '{old_run}' -> '{new_run}'")
                    if _normalize_step_uses(new_step) not in self.policy_pinned_actions:
                        kept_uses = _reconcile_action_ref(
                            existing_step.get("uses"), new_step.get("uses"), self.locked_action_refs is not None
                        )
                        if kept_uses is not None:
                            new_step = new_step.copy()
                            new_step["uses"] = kept_uses
                            self._carry_uses_eol_comment(existing_step, new_step)
                    new_step = self._reconcile_checkout_credentials(existing_step, new_step, job_id)
                final_steps.append(new_step)

        for ex_idx in trailing_existing:
            _append_existing(ex_idx)

        # Re-attach the directive at the step's own indentation (the "- " column);
        # without `indent` ruamel writes it at column 0.
        dash_col = 0
        step_lc = getattr(existing_seq, "lc", None)
        if step_lc is not None and existing_steps:
            try:
                line_no, content_col = step_lc.item(0)
                dash = raw_lines[line_no].rfind("-", 0, content_col + 1)
                dash_col = dash if dash >= 0 else max(content_col - 2, 0)
            except Exception:
                dash_col = 0
        for pos in preserve_comment_indices:
            final_steps.yaml_set_comment_before_after_key(pos, before="@heurix:preserve", indent=dash_col)

        merged_job["steps"] = final_steps
        return merged_job
