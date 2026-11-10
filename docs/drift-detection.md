# Continuous Drift Detection (`hx check`)

As repositories evolve—new database packages added to `pyproject.toml`, Node version bumped in `.nvmrc`, or `uv.lock` adopted—CI workflows quickly drift out of sync. `hx check` detects drift deterministically in milliseconds.

## What `hx check` verifies

1. **Missing synthesized files:** Reports `WARNING` if expected files (`.github/workflows/ci.yml`, `.github/dependabot.yml`) do not exist.
2. **Malformed YAML:** Reports `ERROR` if an existing YAML target fails to parse cleanly.
3. **Missing backing services:** Checks whether services required by dependencies or `docker-compose.yml` (such as `postgres` or `redis`) are missing from `.github/workflows/ci.yml`'s `services:` block.
4. **Runtime version mismatch:** Verifies pinned versions from `.python-version`, `.nvmrc`, `rust-toolchain.toml`, or `go.mod` appear in the workflow.
5. **Package manager alignment:** Checks whether lockfile changes (like switching to `uv.lock`) are reflected in setup actions (such as `astral-sh/setup-uv`).

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
- name: Check CI/CD drift
  run: hx check
```
