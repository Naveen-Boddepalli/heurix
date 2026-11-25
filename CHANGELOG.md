# Changelog

All notable changes to Heurix (`hx`) are documented here.

## Unreleased

### Added — workflow security audit
- **`hx check --security` audits every workflow.** It reports `permissions: write-all` and jobs running with the default token, third-party actions and reusable workflows not pinned to a commit SHA, `pull_request_target` and `workflow_run` triggers, checking out pull request code in them, template injection of attacker-controlled values (`${{ github.event.issue.title }}`, commit messages, `github.head_ref`) into scripts, `actions/checkout` keeping the job token, and `secrets: inherit`. Rule IDs match zizmor's, and `# hx: ignore[rule-id]` or `# zizmor: ignore[rule-id]` on a line silences that finding. Heurix's generated workflows have no findings except third-party tags, which `hx pin` clears.
- **`hx check --format json|sarif`.** JSON gives scripts a stable report. SARIF 2.1.0 uploads to GitHub code scanning with `github/codeql-action/upload-sarif`, with security severity scores for security rules. Scan warnings go to stderr so stdout holds only the report.

### Changed
- Heurix's own workflows are pinned to commit SHAs and no longer keep checkout credentials.

### Added — action pinning and workflow lockfiles
- **`hx pin` pins workflow actions to commit SHAs.** It rewrites `uses: actions/checkout@v7` to `uses: actions/checkout@<sha>  # v7` in every `.github/workflows/*.yml`, editing line by line so comments and layout are kept. Refs are resolved with `git ls-remote` (no token, no API rate limit). `--dry-run` previews the changes. A ref that can't be resolved is reported and the command exits with 1. This is Heurix's only command that uses the network.
- **GitHub Actions workflow lockfiles (`.github/workflows/actions.lock`).** `hx check` reports an error when a workflow listed in the lockfile uses an action that has no lock entry, because GitHub fails that run at job start. `hx generate` keeps every existing ref in a locked workflow, even an older one, reuses locked refs for new steps, and lists the new actions to lock with `gh actions-lock`. `hx pin` defers to `gh actions-lock` in repositories with a lockfile.

## 0.4.0 — 2026-11-22

Upgrading: an existing `ci.yml` regenerates exactly as before. To add least-privilege `permissions`, a `concurrency` group, job timeouts and `persist-credentials: false` to it, set `[ci] harden = true` in `.heurix.toml`, run `hx generate`, and review the list of added keys. Give any job you wrote that pushes, comments or deploys with the job token its own `permissions:` block.

### Added — hardened workflows
- **New workflows are hardened by default.** Generated `ci.yml` files now include a `concurrency` group per branch or PR (a new push cancels a superseded pull-request run, but never a run on a pushed branch, so deploys aren't interrupted), `timeout-minutes` on every job (default 60, set with `[ci].timeout_minutes`), and `persist-credentials: false` on checkout, alongside the existing `permissions: contents: read`.
- **`[ci] harden = true` hardens an existing workflow.** It adds whichever of `permissions`, `concurrency`, job `timeout-minutes` and checkout `persist-credentials: false` are missing, and `hx generate` lists each one before writing. Values you already set are never replaced, and jobs you wrote yourself are left alone. Without `harden`, an existing workflow keeps exactly the hardening it has, because adding `permissions: contents: read` can break a job that pushes or deploys with the job token.

### Fixed
- **Crash on unusual `vercel.json`, `firebase.json` or `.firebaserc`.** A file holding valid JSON that isn't an object (an array, a number, `null`), or a non-string project `name` / `default`, made `hx scan`, `hx generate` and `hx check` abort with a traceback. These files are now ignored with a warning, and the repository name is used as the project ID. Invalid JSON in them now prints a warning instead of being skipped silently.
- **`hx generate` undid Dependabot's action bumps.** Heurix configures Dependabot for `github-actions`, but regenerating reset every generated step's `uses:` to Heurix's default, so a bump such as `astral-sh/setup-uv@v5` → `@v10` was reverted with no notice. Generated steps now keep an existing ref that is newer than the default, or that isn't a version tag (a commit SHA keeps its `# v1.2.3` comment, a branch is left alone), and older refs are still upgraded. Refs set in `.heurix.toml` (`[ci].action_versions`, `[ci].action_shas`) always apply.

### Changed
- **Default action versions:** `astral-sh/setup-uv@v10.4.0` (was `v5`; setup-uv no longer publishes floating major tags, so the full tag is used) and `pnpm/action-setup@v6` (was `v4`). Both accept the same inputs Heurix passes.
- The docs listed outdated defaults for `setup-python`, `setup-node` and `setup-go`; they now match what Heurix generates.

## 0.3.1 — 2026-11-20

Upgrading: re-run `hx generate` if a workflow keeps steps with full-line `# @heurix:preserve` markers. Steps that earlier versions overwrote are not restored, so check those steps against your own copy.

### Fixed — `# @heurix:preserve` on workflow steps
- **Preserved steps after a `with:` block were overwritten.** A full-line `# @heurix:preserve` above a step that follows a step ending in a mapping (such as `actions/setup-python` with `with: python-version`) was not recognized, so `hx generate` replaced the step and dropped the directive. Directives are now read from the source lines directly above each step, however the previous step ends.
- **Preserve after a `run: |` block applied to the wrong step.** The directive froze the block-scalar step above it instead of the step it was written for.
- **Adjacent preserved steps gained a duplicate directive on every run.** Two consecutive steps each with a full-line `# @heurix:preserve` got an extra marker above the second one each time `hx generate` ran.
- **A new generated step inserted next to a preserved step could be frozen.** The directive meant for the following step was left above the inserted step, so later runs treated that generated step as preserved and stopped updating it.

### Development
- Pull requests are now gated on `ruff check`, `ruff format --check`, `mypy`, and an 85% test coverage floor. Run them all locally with `make qa`.
- Timing benchmarks are marked `perf` and run in a separate step without coverage tracing, so they no longer fail on CI runners slowed by tracing.

## 0.3.0 — 2026-11-17

### Added
- **CI path filters in `.heurix.toml`.** `[ci].paths` sets which files trigger CI (and replaces the inferred monorepo filter). `[ci].paths_ignore` skips CI when only matching files change, e.g. `["docs/**", "**/*.md"]`. Both apply to `push` and `pull_request`. If a `paths` list also exists, the ignores are folded into it as `!pattern` entries, because GitHub doesn't allow `paths` and `paths-ignore` together. When either key is set, regenerating updates the filters in an existing `ci.yml`.

## 0.2.2 — 2026-11-16

First release since 0.2.0 (0.2.1 was never published), so this also includes the 0.2.1 changes listed further down.

Upgrading: re-run `hx generate`. It now lists any existing value it is about to replace, so review that list. Then run `hx check` to confirm there's no drift.

### Fixed — generated CI that would fail
- **Duplicate backing services.** When a database appeared in your dependencies (`psycopg`, `redis`) *and* in `docker-compose.yml`, the workflow got two containers on the same host port (e.g. `postgres` and `db` on 5432), so the job could not start. Heurix now merges them into one service, keeping your compose image.
- **Compose-only Postgres.** Postgres services without `POSTGRES_PASSWORD` were refused by the official image, and `DATABASE_URL` pointed at a `test_user`/`test_db` that did not exist. Heurix now fills in credentials, and `DATABASE_URL` always matches the service.
- **Compose services without `ports:`** now publish their standard port (5432, 6379, 27017), so tests can reach them on `localhost`.
- **Compose variables:** `${VAR:-default}` resolves to its default; a bare `${VAR}` is skipped instead of being copied literally.
- **Flat-layout Python projects:** tests now run as `python -m pytest` (or `uv run` / `poetry run python -m pytest`), so `from app import ...` works when `app.py` sits next to `tests/`.
- **Monorepo path filters** now include root files (`'*'`) and `.github/workflows/**`, so lockfile, `turbo.json`, and workflow edits still trigger CI.
- **Cargo workspace caching:** member jobs cache the shared `./target` (`. -> target`) instead of a path that never existed.
- psycopg 3 now provisions Postgres; pnpm and Poetry setup steps are now in the right order; re-runs are stable.

### Fixed — security
- Deploy credentials (`VERCEL_*`, `FIREBASE_*`, `[secrets].deploy`) are no longer written to `k8s/secret.yaml`, which the app pod loads via `envFrom`.

### Changed
- **Kubernetes manifests are generated only for containerized repos** (a Dockerfile, or an explicit `[kubernetes]` policy). A detected framework alone no longer produces a Deployment for an image nothing builds. Existing `k8s/` files are left untouched.
- **`hx init`** sets `include_k8s` based on whether `k8s/deployment.yaml` already exists, so creating a policy no longer makes `hx check` fail on missing manifests.

### Added
- **Replacement notices:** `hx generate` lists every hand-edited value it would replace (a managed job's `runs-on`, a generated step's `run:` command) before writing.
- **Key-level preserve:** put `# @heurix:preserve` at the end of a `runs-on`, `services`, `needs`, or `strategy` line to keep your value. Preserve comments also keep their indentation now.
- **`hx check` catches port collisions:** it reports services in one job that bind the same host port, which catches workflows generated by earlier versions.
- **Visible parse warnings:** an unparseable `package.json` or `pyproject.toml` now prints a warning, even with `--no-explain`.
- **Invalid policy fails the gate:** `hx check` exits 1 with an "Invalid Policy" error when `.heurix.toml` cannot be parsed, instead of silently ignoring it.
- The malformed-YAML recommendation no longer mentions a nonexistent `hx generate --force`.

### From 0.2.1 (unreleased)
- `kubernetes.image_tag` policy, falling back to `IMAGE_TAG` / `APP_VERSION`, then `:latest`.
- Service connection URLs (`DATABASE_URL`, `MONGO_URL`, `MONGODB_URI`, `REDIS_URL`) point at the provisioned service containers, with a validated `[ci.env]` override.
- Default action versions: `actions/checkout@v7`, `actions/setup-python@v7.1.0`, `actions/setup-node@v7`, `actions/setup-go@v7`.

## 0.2.0 — 2026-11-14

- Monorepo topology and multi-job CI, Jinja2 templates, `.heurix.toml` policy, interactive prompts, diff viewer, and pre-commit hook.
