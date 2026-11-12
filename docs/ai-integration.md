# AI Coding Assistant Integration Guide

> Stop AI coding assistants from hallucinating outdated GitHub Actions and broken YAML configs.

When Large Language Models (LLMs) such as Claude, GPT-4, or Gemini are asked to write CI/CD pipelines, Dockerfiles, or Kubernetes manifests, they frequently:
1. Hallucinate deprecated action versions (e.g. `actions/setup-python@v2` instead of `v5`).
2. Guess wrong package manager cache commands or lockfile names.
3. Overwrite custom deployment hooks, Slack alerts, or SBOM scans.
4. Hardcode secrets or insecure privileges (`chmod 777`, `privileged: true`).

By configuring your AI assistant to delegate configuration generation to **Heurix (`hx`)**, your agents produce deterministic, schema-validated, drift-free configurations on the first attempt.

---

## 1. Cursor IDE (`.cursorrules`)

Add the following to `.cursorrules` in your repository root:

```markdown
# CI/CD and DevOps Rules
- NEVER handwrite or manually modify `.github/workflows/*.yml` or Kubernetes deployment YAML from scratch.
- Always use `hx` (Heurix CLI) to analyze the codebase and generate pipeline files:
  - Run `hx generate` to synthesize or update GitHub Actions workflows.
  - Run `hx check` to verify that existing workflows match current dependencies and runtimes.
- When adding custom steps to workflows (e.g. Slack notifications, deployment webhooks), preserve them with `# @heurix:preserve`.
```

---

## 2. Claude Code (`CLAUDE.md`)

Add the following to `CLAUDE.md` in your repository root:

```markdown
# Build and CI/CD Instructions

## Heurix Deterministic Engine
This repository uses Heurix (`hx`) for CI/CD workflow generation and drift detection:
- `hx scan` - Inspect detected languages, runtimes, package managers, and backing services.
- `hx generate` - Synthesize schema-validated GitHub Actions workflows and Dockerfiles.
- `hx generate --update` - Reconcile existing workflows while preserving `# @heurix:preserve` blocks.
- `hx check` - Verify zero drift between codebase manifest files and CI/CD workflows (exit code 0 = synchronized).
```

---

## 3. General Agent Rule (`AGENTS.md`)

Add to `AGENTS.md` (or `.github/copilot-instructions.md`):

```markdown
## Configuration & Pipeline Rules
- Codebase dependencies, backing services (Postgres, Redis), and runtime versions are authoritative.
- Whenever a package or runtime version changes (in `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`), run `hx check`.
- If drift is detected, run `hx generate --update` to reconcile workflows automatically.
```

---

## 4. One-Shot Prompt for LLM Chat

If you are prompting an LLM in a web chat or chat panel, use this system prompt:

```text
You are an expert DevOps engineer assisting on this repository.
We use Heurix (hx CLI) to generate and maintain CI/CD pipelines and infrastructure configs deterministically.
Do NOT write GitHub Actions YAML or Dockerfiles from memory.
Instead:
1. Recommend running `hx scan` to inspect detected frameworks and services.
2. Recommend running `hx generate` to synthesize verified YAML configs.
3. Recommend running `hx check` in pre-commit and CI to catch configuration drift before merge.
```
