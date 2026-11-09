# Contributing

Thank you for helping to improve mcp-capability-router. This guide explains how to set
up a development environment, which checks a change must pass, and how to keep the
documentation, examples, and Agent Skills accurate.

## Development setup

You need Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/smuniharish/mcp-capabilty-router.git
cd mcp-capabilty-router
uv sync --all-extras --all-groups
```

`uv sync` creates a virtual environment and installs the package in editable mode.
The default `dev` group includes tests, lint, and types. Use `--all-extras --all-groups`
for documentation, examples, telemetry, Redis, auditing, and packaging checks.

## Project layout

| Path | Contents |
| --- | --- |
| `src/mcp_capability_router/` | The package. Core public names are exported from `mcp_capability_router`; optional telemetry and contract suites live in the public `otel` and `testing` modules. Implementation details live in `_internal`. |
| `tests/unit/`, `tests/integration/` | Tests of each module, of real FastMCP servers, and of the examples. |
| `tests/property/` | Property-based and stateful tests written with Hypothesis. |
| `examples/` | Runnable examples, with their expected output in `examples/output/`. |
| `docs/` | The documentation site, built with Zensical. |
| `benchmarks/` | Benchmarks of retrieval, refresh, and execution. |
| `scripts/` | Tooling for examples, documentation, diagrams, and distributions. |
| `mcp-capability-router-skills/` | Integration and extension Agent Skills, templates, and evaluations. |

## Checks

Continuous integration runs the following checks. Run them before opening a pull
request:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyrefly check
uv run pytest --cov
uv run python scripts/run_examples.py
uv run python scripts/check_docs.py
uv run python scripts/render_diagrams.py --check
uv run zensical build --strict
uv run python scripts/check_site_links.py
```

- Tests treat warnings as errors, and coverage must stay at 100% of lines and
  branches. Exclude code from coverage only when it cannot run, such as the body of
  an abstract method.
- Continuous integration runs the Hypothesis tests with more examples. Use the same
  profile locally with `HYPOTHESIS_PROFILE=ci`.
- Examples that need a model, embeddings, PostgreSQL, Redis, or Node.js run only when their
  environment variable is set; see [`.env.example`](.env.example). The test suite
  runs the model-based examples with scripted models.
- After changing an example, regenerate its expected output with
  `uv run python scripts/run_examples.py --update` and review the difference.
- Code blocks in Markdown must compile and import only public names. Mark a block with
  `<!-- test -->` to run it; a following `text` block holds its exact output.
- `ruff format` also formats the Python blocks in Markdown files. Include example
  files in documentation with the block form of snippets, which ruff leaves untouched:
  a `--8<--` line, the file path, and another `--8<--` line.

Continuous integration also tests Python 3.12 through 3.15 on Linux and Windows,
audits the dependencies, and validates the built distributions:

```bash
uv build
uv run twine check --strict dist/*
uv run python scripts/validate_distribution.py dist --python 3.12 --python 3.15
```

## Making changes

- Add a test for every behavior change, and a regression test for every fix.
- Build on the ecosystem: use FastMCP, LangChain, LangGraph, refresh-engine, and
  well-maintained PyPI packages instead of reimplementing what they provide.
- Keep the public API typed and documented with Google-style docstrings. New public
  names must be exported from `mcp_capability_router` or its public `otel` and `testing`
  modules and listed in the API reference.
- Preserve the guarantees described in the
  [architecture overview](docs/architecture/overview.md).
- Update the guides, examples, Agent Skills, and `CHANGELOG.md` together with the
  behavior they describe.
- When a change affects performance, run the benchmarks before and after it on the
  same machine and include both results.

## Diagrams

Diagrams are written in Mermaid in `docs/assets/diagrams/*.mmd` and committed as light
and dark PNG images. After editing a diagram, render the images with
[Node.js](https://nodejs.org) installed:

```bash
uv run python scripts/render_diagrams.py
```

Set `MERMAID_BROWSER` to the path of an installed Chromium-based browser to reuse it
instead of downloading one.

## Agent Skills

The integration and extension skills in `mcp-capability-router-skills/skills/` must
describe the current public API. After changing the API or either skill, follow
[the skill validation guide](mcp-capability-router-skills/validation/README.md).

## Releases

1. Update `__version__` in `src/mcp_capability_router/__init__.py`, both skills'
   `metadata.version`, and `CHANGELOG.md`.
2. Merge the changes into `master` after continuous integration passes.
3. Push a `vX.Y.Z` tag. The release workflow checks that the tag matches the package
   version, runs the checks, and publishes to PyPI with trusted publishing and
   attestations.

## License

By contributing, you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE).
