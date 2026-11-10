"""
Non-Destructive Smart Merge and AST Round-Trip Preservation.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional, Set, Tuple
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

IDENTIFIER_KEYS = ("name", "package-ecosystem", "containerPort", "port", "id")
PROBE_HANDLER_KEYS = frozenset({"httpGet", "tcpSocket", "exec", "grpc"})
PRESERVE_MARKERS = ("@heurix:preserve", "@autoyaml:preserve")


class YamlSyntaxError(Exception):
    """Raised when existing or synthesized YAML content contains invalid syntax."""


def _normalize_step_uses(step: Any) -> Optional[str]:
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


def _normalize_step_name(step: Any) -> Optional[str]:
    """Return normalized lowercase name for a workflow step."""
    if not isinstance(step, (dict, CommentedMap)):
        return None
    name = step.get("name")
    if name is None:
        return None
    val = str(name).strip().lower()
    return val if val else None


def _normalize_step_run(step: Any) -> Optional[str]:
    """Return whitespace-normalized run command for a workflow step."""
    if not isinstance(step, (dict, CommentedMap)):
        return None
    run = step.get("run")
    if run is None:
        return None
    val = " ".join(str(run).split())
    return val if val else None


def _get_entity_identifier(item: Any) -> Optional[Tuple[str, Any]]:
    """Extract the primary identity key/value pair from a YAML mapping sequence item."""
    if isinstance(item, (dict, CommentedMap)):
        for key in IDENTIFIER_KEYS:
            if key in item:
                return (key, item[key])
    return None


def _sequence_items_match(
    ex_item: Any, new_item: Any, ident_key: str, ident_val: Any
) -> bool:
    """Return True if an existing sequence mapping represents the same entity as new_item."""
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
            elif existing[k] is None and isinstance(
                v, (dict, CommentedMap, list, CommentedSeq)
            ):
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


def _get_doc_identity(doc: Any) -> Optional[Tuple[Optional[str], Optional[str]]]:
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

    def __init__(self):
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.indent(mapping=2, sequence=4, offset=2)

    def merge_yaml(self, existing_content: str, new_content: str) -> str:
        """
        Merges new_content into existing_content non-destructively.
        Raises YamlSyntaxError if existing_content cannot be parsed.
        """
        if not existing_content.strip():
            return new_content

        try:
            existing_docs = [d for d in self.yaml.load_all(existing_content) if d is not None]
        except Exception as e:
            raise YamlSyntaxError(
                f"Existing YAML has invalid syntax and cannot be safely merged: {e}"
            ) from e

        try:
            new_docs = [d for d in self.yaml.load_all(new_content) if d is not None]
        except Exception as e:
            raise YamlSyntaxError(
                f"Synthesized YAML has invalid syntax and cannot be merged: {e}"
            ) from e

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

    def _merge_multidoc(self, existing_docs: List[Any], new_docs: List[Any]) -> List[Any]:
        """
        Merge multi-document YAML streams by correlating documents on (kind, metadata.name).
        Existing unmatched documents are preserved; new unmatched documents are appended.
        """
        merged_docs: List[Any] = list(existing_docs)
        matched_existing_indices: Set[int] = set()

        for new_doc in new_docs:
            new_ident = _get_doc_identity(new_doc)
            matched_idx: Optional[int] = None

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

    @staticmethod
    def _collect_comment_values(token: Any, require_newline_marker: bool = False) -> List[str]:
        """Extract string values from a ruamel.yaml comment token or token list."""
        values: List[str] = []
        items = token if isinstance(token, list) else [token]
        for t in items:
            val = getattr(t, "value", None)
            if val is None:
                continue
            if require_newline_marker:
                if any(m in val for m in PRESERVE_MARKERS) and val.startswith("\n"):
                    values.append(val)
            else:
                values.append(val)
        return values

    def _has_internal_preserve_comment(self, seq: Any, idx: int, item: Any) -> bool:
        """Check whether preserve directive comments are attached directly inside a step mapping."""
        comment_blobs: List[str] = []
        if hasattr(item, "ca") and item.ca:
            if item.ca.comment:
                for token in item.ca.comment:
                    if token:
                        comment_blobs.extend(self._collect_comment_values(token))
            if item.ca.items:
                keys = list(item.keys()) if hasattr(item, "keys") else []
                for k, key_tokens in item.ca.items.items():
                    is_last_key = (k == keys[-1]) if keys else False
                    for token in key_tokens:
                        if not token:
                            continue
                        for val in self._collect_comment_values(token):
                            # Trailing comment with leading newline on non-final step belongs to next item
                            if is_last_key and hasattr(seq, "__len__") and idx < len(seq) - 1 and val.startswith("\n"):
                                continue
                            comment_blobs.append(val)

        combined = "\n".join(comment_blobs)
        return any(m in combined for m in PRESERVE_MARKERS)

    def _has_preserve_comment(self, seq: Any, idx: int, item: Any) -> bool:
        """Check ruamel.yaml comment attributes on sequence index and mapping keys."""
        comment_blobs: List[str] = []

        # Sequence comments for first item (comments placed above first list item)
        if idx == 0 and hasattr(seq, "ca") and seq.ca and seq.ca.comment:
            for token in seq.ca.comment:
                if token:
                    comment_blobs.extend(self._collect_comment_values(token))

        # 1. Check sequence item comments attached to index
        if hasattr(seq, "ca") and seq.ca and seq.ca.items and idx in seq.ca.items:
            for token in seq.ca.items[idx]:
                if token:
                    comment_blobs.extend(self._collect_comment_values(token))

        # 2. Check previous item trailing comment (ruamel attaches comments written above item to prev item ca)
        if idx > 0 and hasattr(seq, "__getitem__"):
            prev_item = seq[idx - 1]
            if hasattr(prev_item, "ca") and prev_item.ca and prev_item.ca.items:
                keys = list(prev_item.keys()) if hasattr(prev_item, "keys") else []
                if keys:
                    tokens = prev_item.ca.items.get(keys[-1])
                    if tokens:
                        for token in tokens:
                            if token:
                                comment_blobs.extend(
                                    self._collect_comment_values(token, require_newline_marker=True)
                                )

        if any(m in "\n".join(comment_blobs) for m in PRESERVE_MARKERS):
            return True

        # 3. Check mapping internal comments (pre-comments on keys, inline comments)
        return self._has_internal_preserve_comment(seq, idx, item)

    def _match_steps(
        self, existing_steps: List[Any], new_steps: List[Any]
    ) -> Tuple[Dict[int, int], Dict[int, int]]:
        """
        Match existing workflow steps to synthesized new steps 1-to-1
        by compound identity, uses action base, step name, or run command.
        """
        ex_sig = [
            (_normalize_step_uses(s), _normalize_step_name(s), _normalize_step_run(s))
            for s in existing_steps
        ]
        new_sig = [
            (_normalize_step_uses(s), _normalize_step_name(s), _normalize_step_run(s))
            for s in new_steps
        ]

        ex_to_new: Dict[int, int] = {}
        new_to_ex: Dict[int, int] = {}

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
            lambda e, n: (e[0] is not None and e[0] == n[0] and e[1] is not None and e[1] == n[1])
            or (e[1] is not None and e[1] == n[1] and e[2] is not None and e[2] == n[2])
        )
        # Pass 2: action repository match (handles @v3 -> @v4 and label changes)
        _run_pass(lambda e, n: e[0] is not None and e[0] == n[0])
        # Pass 3: step name match
        _run_pass(lambda e, n: e[1] is not None and e[1] == n[1])
        # Pass 4: run command match
        _run_pass(lambda e, n: e[2] is not None and e[2] == n[2])

        return ex_to_new, new_to_ex

    def _merge_job(self, existing_job: Any, new_job: Any, raw_existing: str = "") -> Any:
        if not isinstance(existing_job, dict) or not isinstance(new_job, dict):
            return new_job

        merged_job = existing_job.copy()
        # Update runs-on, services from new_job
        if "runs-on" in new_job:
            merged_job["runs-on"] = new_job["runs-on"]
        if "services" in new_job:
            merged_job["services"] = new_job["services"]

        # Steps merging
        if "steps" not in new_job and "steps" not in existing_job:
            return merged_job

        new_steps = list(new_job.get("steps") or [])
        existing_steps = list(existing_job.get("steps") or [])
        existing_seq = existing_job.get("steps")

        ex_preserved = [
            self._has_preserve_comment(existing_seq, idx, step)
            for idx, step in enumerate(existing_steps)
        ]

        ex_to_new, new_to_ex = self._match_steps(existing_steps, new_steps)

        # Anchor unmatched existing steps (both @preserve and unmanaged) relative to the next matched step
        anchored_before: Dict[int, List[int]] = {j: [] for j in range(len(new_steps))}
        trailing_existing: List[int] = []

        for idx in range(len(existing_steps)):
            if idx in ex_to_new:
                continue
            next_new_idx: Optional[int] = None
            for k in range(idx + 1, len(existing_steps)):
                if k in ex_to_new:
                    next_new_idx = ex_to_new[k]
                    break
            if next_new_idx is not None:
                anchored_before[next_new_idx].append(idx)
            else:
                trailing_existing.append(idx)

        final_steps = CommentedSeq()
        preserve_comment_indices: List[int] = []

        def _append_existing(ex_idx: int) -> None:
            step = existing_steps[ex_idx]
            pos = len(final_steps)
            final_steps.append(step)
            if ex_preserved[ex_idx] and not self._has_internal_preserve_comment(existing_seq, ex_idx, step):
                preserve_comment_indices.append(pos)

        for j, new_step in enumerate(new_steps):
            for ex_idx in anchored_before[j]:
                _append_existing(ex_idx)

            if j in new_to_ex and ex_preserved[new_to_ex[j]]:
                # Preserve existing customized step rather than overwriting with synthesized step
                _append_existing(new_to_ex[j])
            else:
                final_steps.append(new_step)

        for ex_idx in trailing_existing:
            _append_existing(ex_idx)

        for pos in preserve_comment_indices:
            final_steps.yaml_set_comment_before_after_key(pos, before="@heurix:preserve")

        merged_job["steps"] = final_steps
        return merged_job
