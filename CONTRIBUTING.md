# Contributing to Heurix

Thanks for helping out. Bug reports, fixes, new detectors and doc improvements are all welcome. For anything bigger than a small fix, open an issue first so we can agree on the approach before you spend time on it.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report security issues privately as described in [SECURITY.md](SECURITY.md), not in a public issue.

## Development setup

You need Python 3.10 or newer. For the docs site you also need Node.js (CI uses 24) and pnpm 10.

```bash
git clone https://github.com/Naveen-Boddepalli/heurix.git
cd heurix
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,build]'
```

`hx` and `heurix` now run your working copy.

## Tests and quality gates

CI runs the same checks as `make qa`, on Python 3.10, 3.11 and 3.12. Run it before you open a pull request:

```bash
make qa
```

That covers:

| Command | What it checks |
|---------|----------------|
| `make lint` | `ruff check .` |
| `ruff format --check .` | Formatting (run `make format` to fix it) |
| `make typecheck` | `mypy` |
| `make cov` | The test suite with branch coverage; fails below 85% |
| `make perf` | Timing benchmarks (marked `perf`), run without coverage tracing |

While you work, `make test` runs the whole suite, and `.venv/bin/pytest tests/test_security.py -k injection` runs part of it.

CI also runs Heurix on its own workflows. Run it locally with:

```bash
make check   # hx check --security
```

## Docs and the website

Guides live in `docs/`, and the site (docs reader and in-browser playground) is in `site/`:

```bash
pnpm --dir site install
make site-dev     # dev server on http://localhost:5173
make site-build   # syncs docs and llms.txt, type-checks and builds site/dist
```

The playground runs a TypeScript port of the heuristics in `site/src/engine/`. If you change what Heurix generates, check whether the playground needs the same change.

## Pull requests

- Keep each pull request to one change, and add or update tests for it. A bug fix should come with a test that fails without it.
- Add a line under `## Unreleased` in [CHANGELOG.md](CHANGELOG.md) for anything a user would notice.
- Update the relevant page in `docs/` when you change a command, flag or `.heurix.toml` key.
- Generated output must stay deterministic: the same repository has to produce the same files every time, with no network calls (`hx pin` is the one exception).
- Commit messages follow the existing style: `feat(check): ...`, `fix(merger): ...`, `docs: ...`, `test: ...`, `ci: ...`.

## Adding a detector

Detectors live in `src/heurix/detectors/`. Each one subclasses `BaseDetector` (`base.py`): `detect()` is a quick check against the shared `RepoIndexer`, and `analyze()` records what it found in the `ProjectContext` (`src/heurix/core/context.py`). Register a new detector in `ALL_DETECTORS` in `detectors/__init__.py`. Synthesizers in `src/heurix/synthesizers/` turn that context into YAML. [docs/architecture.md](docs/architecture.md) describes the layers, and [docs/heuristics.md](docs/heuristics.md) lists what each detector reads, so add your detector's signals there too.
