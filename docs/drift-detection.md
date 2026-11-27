# Continuous Drift Detection (`hx check`)

As repositories evolve—new database packages added to `pyproject.toml`, Node version bumped in `.nvmrc`, or `uv.lock` adopted—CI workflows quickly drift out of sync. `hx check` detects drift deterministically in milliseconds.

## What `hx check` verifies

1. **Missing synthesized files:** Reports `WARNING` if expected files (`.github/workflows/ci.yml`, `.github/dependabot.yml`) do not exist.
2. **Malformed YAML:** Reports `ERROR` if an existing YAML target fails to parse cleanly.
3. **Missing backing services:** Checks whether services required by dependencies or `docker-compose.yml` (such as `postgres` or `redis`) are missing from `.github/workflows/ci.yml`'s `services:` block.
4. **Runtime version mismatch:** Verifies pinned versions from `.python-version`, `.nvmrc`, `rust-toolchain.toml`, or `go.mod` appear in the workflow.
5. **Package manager alignment:** Checks whether lockfile changes (like switching to `uv.lock`) are reflected in setup actions (such as `astral-sh/setup-uv`).
6. **Workflow lockfile coverage:** If the repository has a GitHub Actions lockfile (`.github/workflows/actions.lock`, written by `gh actions-lock`), reports `ERROR` for each workflow listed in it that uses an action with no lock entry. GitHub fails those runs at job start, so the fix is to run `gh actions-lock` and commit the lockfile. A lockfile that can't be read (invalid YAML, or a newer format without a `workflows` map) is reported as a `WARNING`. Workflows not listed in the lockfile aren't checked.

## Exit codes & automation

`hx check` exits with status `0` when zero drift is found, and `1` when any finding is reported.

### Git pre-commit hook

Add a lightweight hook in `.git/hooks/pre-commit` or `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: heurix-drift-check
        name: Heurix CI/CD Drift Check
        entry: hx check
        language: system
        pass_filenames: false
```

### CI pipeline guard

```yaml
- name: Check CI/CD drift and workflow security
  run: hx check --security
```

### GitHub Action

The repository is also a composite GitHub Action that installs Heurix and runs `hx check`. It needs `python3` 3.10 or newer on the runner (GitHub's Ubuntu and macOS runners have it; elsewhere add `actions/setup-python` first) and doesn't support Windows runners. Pin it to a release's commit SHA, as `hx check --security` recommends for any third-party action:

```yaml
- uses: actions/checkout@v7
  with:
    persist-credentials: false
- uses: Naveen-Boddepalli/heurix@<commit-sha>  # vX.Y.Z
  with:
    security: true
```

The action installs the Heurix version at the ref you pin, unless you set `version`.

| Input | Default | Description |
|-------|---------|-------------|
| `path` | `.` | Root directory of the repository to check. |
| `security` | `true` | Also run the security audit (`--security`). |
| `format` | `text` | `text`, `json` or `sarif`. |
| `output-file` | (log) | Write the report to this file instead of the job log. |
| `fail-on-findings` | `true` | Set to `false` to let later steps run (for example a SARIF upload) and read the `exit-code` output instead. Invalid input still fails the step. |
| `version` | (action ref) | Install this Heurix version from PyPI instead, e.g. `0.4.0`. |

The `exit-code` output is `0` with no findings, `1` with findings, and `2` for invalid input.

## Security audit (`hx check --security`)

`--security` also audits every workflow in `.github/workflows/`, including ones Heurix didn't generate. Rule IDs match the equivalent [zizmor](https://docs.zizmor.sh/) audits, so you can look a finding up, and silence it, the same way in both tools.

| Rule | Severity | Flags |
|------|----------|-------|
| `excessive-permissions` | ERROR / WARNING | `permissions: write-all` (error), or no `permissions` block, so jobs run with the repository's default token (warning). |
| `unpinned-uses` | WARNING | A third-party action or reusable workflow on a tag or branch instead of a commit SHA. Actions from `actions/`, `github/` and `dependabot/` may use tags. Workflows covered by `.github/workflows/actions.lock` are skipped, because the lockfile pins them. Fix with `hx pin`. |
| `dangerous-triggers` | WARNING | `pull_request_target` or `workflow_run`, which run with secrets and a write token on events outside contributors can trigger. |
| `untrusted-checkout` | ERROR | `actions/checkout` of the pull request's own code inside one of those workflows. |
| `template-injection` | ERROR | An attacker-controlled value such as `${{ github.event.issue.title }}`, a commit message or `github.head_ref` expanded into a `run:` script or an `actions/github-script` script. Pass it through `env:` instead. |
| `artipacked` | WARNING | `actions/checkout` without `persist-credentials: false`, which leaves the job token in `.git/config`. |
| `secrets-inherit` | WARNING | A reusable workflow call with `secrets: inherit`. |

To accept a finding, add `# hx: ignore[<rule-id>]` (or zizmor's `# zizmor: ignore[<rule-id>]`) to the flagged line. Separate several rule IDs with commas.

Workflows Heurix generates have no findings except `unpinned-uses` for third-party actions such as `astral-sh/setup-uv`, which `hx pin` clears. `dtolnay/rust-toolchain` is the exception, because its ref selects the toolchain, so pin it by hand with a `toolchain:` input.

## Machine-readable reports

`--format json` prints a report on stdout, and scan warnings go to stderr:

```json
{
  "tool": "heurix",
  "version": "0.4.0",
  "summary": { "total": 1, "errors": 0, "warnings": 1 },
  "findings": [
    {
      "rule_id": "unpinned-uses",
      "severity": "WARNING",
      "file": ".github/workflows/release.yml",
      "line": 18,
      "issue": "jobs.release.steps[2] uses softprops/action-gh-release@v3, a tag or branch its owner can move to different code.",
      "recommendation": "Pin it to a commit SHA with 'hx pin', or lock the workflow with 'gh actions-lock'."
    }
  ]
}
```

`rule_id` is `drift` for drift findings, `lockfile` for lockfile findings, or one of the security rules above. `line` is `null` when a finding is about a whole file.

`--format sarif` prints SARIF 2.1.0, which GitHub code scanning shows as alerts on pull requests and in the Security tab. Security rules carry a `security-severity` score, so code scanning ranks them. Upload it from a workflow (code scanning on private repositories needs GitHub Code Security):

```yaml
name: Heurix audit
on: [push, pull_request]
permissions:
  contents: read
jobs:
  audit:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write  # upload SARIF
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - run: pipx install heurix
      # hx check exits 1 when it finds something; still upload the report.
      - run: hx check --security --format sarif > heurix.sarif || true
      - uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: heurix.sarif
```

With the GitHub Action, replace the `pipx install` and `hx check` steps with:

```yaml
      - uses: Naveen-Boddepalli/heurix@<commit-sha>  # vX.Y.Z
        with:
          format: sarif
          output-file: heurix.sarif
          fail-on-findings: false
```
