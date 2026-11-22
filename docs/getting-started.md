# Getting started

Heurix (`hx`) is a deterministic codebase scanner and automated YAML synthesizer. It inspects your repository's files, lockfiles, runtime pins, Dockerfiles, and dependencies in milliseconds—without network calls or LLM hallucinations—and synthesizes production-ready GitHub Actions workflows, Dependabot maintenance files, and Kubernetes manifests.

## Install

Install with `pipx` (recommended for isolated global CLI usage) or `pip`:

```bash
pipx install heurix
# or
pip install heurix
```

Or install via the standalone shell script:

```bash
curl -fsSL https://raw.githubusercontent.com/Naveen-Boddepalli/heurix/main/install.sh | bash
```

Or run directly via Docker without installing Python:

```bash
docker run --rm -v "$(pwd):/workspace" ghcr.io/naveen-boddepalli/heurix:latest generate --dry-run
```

Requires Python `>= 3.10` when installed from PyPI.

## First scan

Inspect what Heurix infers about your project before writing any files:

```bash
hx scan
```

This prints the strongly-typed `ProjectContext` Intermediate Representation (IR) as JSON, including detected languages, pinned versions, package managers, backing services, container configurations, cloud deployment targets, required secrets, and the human-readable `explain_log`.

## Synthesize configurations

Run a dry-run preview first to see the reasoning tree and generated files:

```bash
hx generate --dry-run
```

Preview a colorized terminal diff against existing files:

```bash
hx generate --diff
```

Generate and merge configurations interactively (or pass `--yes` for non-interactive CI/automation):

```bash
hx generate
# or
hx generate --yes
```

## Policy overrides (`.heurix.toml`)

Heurix works with zero configuration by default. To enforce team-wide overrides (such as always running on `ubuntu-24.04-arm` or skipping Kubernetes generation), initialize a `.heurix.toml` file:

```bash
hx init
```

Example `.heurix.toml`:

```toml
[engine]
runner = "ubuntu-latest"
non_destructive = true

[ci]
include_dependabot = true
include_k8s = true

[overrides]
# python = "3.12"
# node = "20.x"
```

### CI path filters

By default, monorepos get a `paths:` filter covering root files, `.github/workflows/**`, and each package, and single-package repos run CI on every change. You can control this in `[ci]`:

```toml
[ci]
paths_ignore = ["docs/**", "**/*.md"]  # skip CI when only these files change
# paths = ["src/**", "tests/**"]       # run CI only when these files change
```

- `paths` replaces the inferred monorepo filter. Set `paths = []` to turn filtering off.
- `paths_ignore` is emitted as `paths-ignore`. GitHub does not allow `paths` and `paths-ignore` on the same event, so when a `paths` list also exists (yours or the monorepo one), the ignores are added to it as `!pattern` entries.
- Patterns must not start with `!`. Put exclusions in `paths_ignore`.
- When either key is set, `hx generate` overwrites the trigger filters in an existing `ci.yml` and lists the old values it replaced.

### Hardening existing workflows

New workflows are generated hardened: least-privilege `permissions`, a `concurrency` group, job timeouts, and `persist-credentials: false` on checkout. A workflow that already exists keeps the hardening it has, because adding `permissions: contents: read` can break a job that pushes, comments, or deploys with the job token. To add what's missing:

```toml
[ci]
harden = true
timeout_minutes = 30   # optional; default 60, GitHub's own default is 360
```

- `hx generate` lists every key it adds before writing.
- Only missing keys are added. A `permissions`, `concurrency`, `timeout-minutes`, or `persist-credentials` you already set is kept, so a checkout with `persist-credentials: true` keeps working.
- Jobs you wrote yourself are left alone. If one of them needs write access, give it its own `permissions:` block, which overrides the workflow-level one for that job.

### Pinning actions to commit SHAs

Tags such as `@v7` can be moved to different code. To pin every action to the commit its tag points at now, run:

```bash
hx pin --dry-run   # preview
hx pin
```

Each `uses: actions/checkout@v7` becomes `uses: actions/checkout@<sha>  # v7`, and Dependabot keeps the pins updated. If your repository uses a GitHub Actions lockfile (`.github/workflows/actions.lock`), use `gh actions-lock` instead. In that case `hx generate` keeps the locked refs, reuses them for new steps, and lists any new action that needs `gh actions-lock` before the workflow can run. `hx check` reports the same gap as an error.

## Preserving custom YAML edits

Whenever Heurix updates an existing `.github/workflows/ci.yml`, it uses `ruamel.yaml` round-trip AST merging rather than overwriting the file. Custom jobs (such as Slack notifications or deployment hooks) and any step marked with `# @heurix:preserve` are left untouched:

```yaml
      - name: Notify team on failure # @heurix:preserve
        if: failure()
        uses: slackapi/slack-github-action@v1
```
