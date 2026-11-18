# Dependency audit

**Verified:** 2026-11-18

**Source:** PyPI JSON release metadata (`https://pypi.org/pypi/<package>/json`) and
the package's official release notes where relevant. Only stable, non-prerelease
releases were considered. The repository supports Python 3.12–3.14.

The table compares the pre-audit lower bound with the selected requirement and the
latest stable PyPI version on the verification date. All declared direct dependencies'
Python metadata permits the supported Python range. The ten version updates were
minor or patch releases; no major-version constraint was widened.

On the subsequent 2.0.1 preparation audit, all 39 declared direct and build
dependencies were rechecked against PyPI's non-yanked stable releases. Every selected
lower bound remains current; release-file Python metadata permits Python 3.12, 3.13,
and 3.14. No requirements or lock selections were upgraded in that audit. Python
metadata alone does not establish transitive compatibility or wheel availability.

| Class | Package | Pre-audit | Selected | Latest stable | Result |
| --- | --- | ---: | ---: | ---: | --- |
| Build | [uv-build](https://pypi.org/project/uv-build/) | 0.13.7 | 0.13.9 | 0.13.9 | Updated |
| Core | [aiolimiter](https://pypi.org/project/aiolimiter/) | 1.3.0 | 1.3.0 | 1.3.0 | Current |
| Core | [anyio](https://pypi.org/project/anyio/) | 4.16.0 | 4.16.0 | 4.16.0 | Current |
| Core, codemode extra | [fastmcp](https://pypi.org/project/fastmcp/) | 4.1.8 | 4.2.1 | 4.2.1 | Updated |
| Core | [httpx2](https://pypi.org/project/httpx2/) | 2.16.0 | 2.16.2 | 2.16.2 | Updated |
| Core | [mcp](https://pypi.org/project/mcp/) | 2.3.0 | 2.3.0 | 2.3.0 | Current |
| Core | [opentelemetry-api](https://pypi.org/project/opentelemetry-api/) | 1.45.2 | 1.45.2 | 1.45.2 | Current |
| Core | [pydantic](https://pypi.org/project/pydantic/) | 2.14.3 | 2.14.3 | 2.14.3 | Current |
| Core, redis extra | [purgatory](https://pypi.org/project/purgatory/) | 3.0.2 | 3.0.2 | 3.0.2 | Current |
| Core, otel extra | [refresh-engine](https://pypi.org/project/refresh-engine/) | 1.0.0 | 1.0.1 | 1.0.1 | Updated |
| Core | [retrievalloom](https://pypi.org/project/retrievalloom/) | 0.2.0 | 0.2.0 | 0.2.0 | Current |
| Core | [tenacity](https://pypi.org/project/tenacity/) | 9.2.1 | 9.2.1 | 9.2.1 | Current |
| LangChain extra | [langchain](https://pypi.org/project/langchain/) | 1.5.0 | 1.5.0 | 1.5.0 | Current |
| LangChain extra | [langchain-core](https://pypi.org/project/langchain-core/) | 1.8.0 | 1.8.2 | 1.8.2 | Updated |
| OTEL extra | [opentelemetry-sdk](https://pypi.org/project/opentelemetry-sdk/) | 1.45.2 | 1.45.2 | 1.45.2 | Current |
| Tests | [coverage](https://pypi.org/project/coverage/) | 7.17.3 | 7.17.3 | 7.17.3 | Current |
| Tests | [hypothesis](https://pypi.org/project/hypothesis/) | 6.170.15 | 6.170.15 | 6.170.15 | Current |
| Tests | [pytest](https://pypi.org/project/pytest/) | 9.2.0 | 9.2.0 | 9.2.0 | Current |
| Tests | [pytest-asyncio](https://pypi.org/project/pytest-asyncio/) | 1.5.0 | 1.5.0 | 1.5.0 | Current |
| Tests | [pytest-cov](https://pypi.org/project/pytest-cov/) | 7.1.0 | 7.1.0 | 7.1.0 | Current |
| Tests | [pytest-timeout](https://pypi.org/project/pytest-timeout/) | 2.4.0 | 2.4.0 | 2.4.0 | Current |
| Tests | [skills-ref](https://pypi.org/project/skills-ref/) | 0.1.1 | 0.1.1 | 0.1.1 | Current |
| Lint | [ruff](https://pypi.org/project/ruff/) | 0.17.5 | 0.17.5 | 0.17.5 | Current |
| Types | [pyrefly](https://pypi.org/project/pyrefly/) | 1.4.1 | 1.4.1 | 1.4.1 | Current |
| Docs | [griffe-pydantic](https://pypi.org/project/griffe-pydantic/) | 1.3.2 | 1.3.2 | 1.3.2 | Current |
| Docs | [mkdocstrings-python](https://pypi.org/project/mkdocstrings-python/) | 2.0.11 | 2.0.11 | 2.0.11 | Current |
| Docs | [zensical](https://pypi.org/project/zensical/) | 0.1.1 | 0.1.2 | 0.1.2 | Updated |
| Examples | [asyncpg](https://pypi.org/project/asyncpg/) | 0.32.0 | 0.32.0 | 0.32.0 | Current |
| Examples | [deepagents](https://pypi.org/project/deepagents/) | 0.7.37 | 0.7.39 | 0.7.39 | Updated |
| Examples | [langchain-openai](https://pypi.org/project/langchain-openai/) | 1.7.4 | 1.8.1 | 1.8.1 | Updated |
| Examples | [langgraph](https://pypi.org/project/langgraph/) | 1.2.21 | 1.2.22 | 1.2.22 | Updated |
| Examples | [langgraph-swarm](https://pypi.org/project/langgraph-swarm/) | 0.1.0 | 0.1.0 | 0.1.0 | Current |
| Examples | [openai](https://pypi.org/project/openai/) | 3.50.0 | 3.55.0 | 3.55.0 | Updated |
| Examples, OTEL | [opentelemetry-exporter-otlp-proto-grpc](https://pypi.org/project/opentelemetry-exporter-otlp-proto-grpc/) | 1.45.2 | 1.45.2 | 1.45.2 | Current |
| Examples | [prometheus-client](https://pypi.org/project/prometheus-client/) | 0.26.0 | 0.26.0 | 0.26.0 | Current |
| Packaging | [twine](https://pypi.org/project/twine/) | 7.0.0 | 7.0.0 | 7.0.0 | Current |
| Audit | [pip-audit](https://pypi.org/project/pip-audit/) | 2.10.1 | 2.10.1 | 2.10.1 | Current |
| Models | [sentence-transformers](https://pypi.org/project/sentence-transformers/) | 6.3.0 | 6.3.0 | 6.3.0 | Current |
| Models | [torch](https://pypi.org/project/torch/) | 2.15.0 | 2.15.0+cpu | 2.15.0 | Current¹ |

¹ The `models` group uses the official PyTorch CPU wheel index. `2.15.0+cpu` is
the CPU build of PyPI's `2.15.0` release. The security workflow removes the local
`+cpu` suffix when submitting that locked version to pip-audit, which looks up
advisories against PyPI.

### Known development dependency conflict

On 2026-11-18, `uv pip check` found that the examples environment's
`google-genai` 3.5.0 requires `tenacity>=8.2.3,<9.2.0`, while core dependency
`refresh-engine` 1.0.1 requires `tenacity>=9.2.1`. Deep Agents 0.7.39 brings in
`google-genai` through `langchain-google-genai`; published `google-genai` 3.2.0
through 3.5.0 all have the conflicting bound. The repository's existing uv
override selects tenacity 9.2.1 for development but does not make the upstream
requirements compatible or apply to downstream package installations. A strict
resolver cannot install these releases together. The core-only environment passes
`uv pip check`; recheck upstream releases before using this combination in production.

### Compatibility and release-note review

- **FastMCP 4.2.1:** 4.2 introduced a new server-side skills API and deprecated its
  4.1 skills API. This package does not use either API; its installed skills are
  repository assets. The 4.2.1 patch also hardens OAuth/JWT handling. The package's
  Python floor (3.12) exceeds FastMCP's 3.11 minimum.
- **refresh-engine 1.0.1:** latest compatible 1.0 patch; existing integration and
  refresh tests pass.
- **LangChain/OpenAI and Deep Agents:** the selected versions retain the existing
  major-version constraints and are exercised by the full suite and examples with
  the development override described above. Their Python 3.11+ floor is compatible
  with this project's Python 3.12–3.14 support.
- **Zensical 0.1.2:** patch release; strict documentation build and link validation
  pass.
- **Maintenance:** no dependency was removed or replaced. Release cadence varies;
  pytest-timeout's latest official repository commit was 2026-11-06, and
  langgraph-swarm-py's was 2026-10-29, even though their latest PyPI releases are
  older. Both repositories remain active. Recheck release metadata and repository
  activity during future audits.

Official release-note sources reviewed: [FastMCP 4.2.1](https://github.com/PrefectHQ/fastmcp/releases/tag/v4.2.1),
[Deep Agents 0.7.39](https://github.com/langchain-ai/deepagents/releases/tag/deepagents%3D%3D0.7.39),
[OpenAI 3.55.0](https://github.com/openai/openai-python/releases/tag/v3.55.0),
[LangGraph releases](https://github.com/langchain-ai/langgraph/releases),
[Zensical releases](https://github.com/zensical/zensical/releases),
and [refresh-engine changelog](https://refresh-engine.readthedocs.io/en/latest/changelog/).
Maintenance checks: [pytest-timeout commits](https://github.com/pytest-dev/pytest-timeout/commits),
[langgraph-swarm-py commits](https://github.com/langchain-ai/langgraph-swarm-py/commits).
