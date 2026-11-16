# Non-Destructive Smart Merge (`ruamel.yaml`)

Infrastructure generators fail when regenerating files overwrites manual edits—such as custom deployment steps, Slack notifications, or modified triggers. Heurix solves this with AST round-trip merging via `ruamel.yaml`.

## How `SmartMerger` works

1. **AST Preservation:** Existing YAML files are parsed into `CommentedMap` and `CommentedSeq` AST structures that retain formatting, quotes, and inline comments.
2. **Custom Jobs Retained:** In `.github/workflows/ci.yml`, any custom job you added (such as `slack_notify` or `security_scan`) that is not managed by Heurix is automatically preserved in `jobs:`.
3. **Managed Job Step Merging:** Inside managed jobs (like `test`), Heurix updates generated steps (e.g., updating Python from `3.11` to `3.12` or adding `setup-uv`) while retaining user-authored steps tagged with `# @heurix:preserve`.
4. **Comment Directives:** Place `# @heurix:preserve` (or `# @autoyaml:preserve`) directly above or inline on any step to guarantee it survives every `hx generate` run:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      # @heurix:preserve
      - name: Send Slack notification on failure
        if: failure()
        uses: slackapi/slack-github-action@v1
```

5. **Job-Level Keys:** Heurix owns `runs-on`, `services`, `needs`, and `strategy` in managed jobs. To keep your own value, put the directive at the end of that key's line:

```yaml
jobs:
  test:
    runs-on: ubuntu-24.04  # @heurix:preserve pinned by SRE
    strategy:  # @heurix:preserve
      matrix:
        python-version: ['3.11', '3.12']
```

6. **Replacement Notices:** When a merge would replace a value you edited by hand (a `runs-on` runner or a generated step's `run:` command) without a preserve directive, `hx generate` lists each replaced value before writing, so edits are never lost silently.

## Disabling Smart Merge

If you ever want a clean rewrite of synthesized targets in `.heurix.toml`, set `non_destructive = false` under `[engine]`:

```toml
[engine]
non_destructive = false
```
