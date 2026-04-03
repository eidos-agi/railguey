---
id: "ADR-001"
type: "decision"
title: "PyPI release pipeline: minimal fix + railguey artifact tracking, no semantic-release"
status: "accepted"
date: "2026-04-03"
source_research_id: "4f296f95-959d-4ada-8741-25122f69e1ce"
---

## Decision

Adopt two complementary approaches. Reject full automation tooling.

### Phase 1: Fix version single-source-of-truth (all Eidos packages)
- Replace hardcoded `__version__` in `__init__.py` with `importlib.metadata.version("package-name")`
- pyproject.toml becomes the only place version is defined
- Add CI guardrails: tag version must match pyproject.toml, CHANGELOG must have entry for version
- Keep hand-written CHANGELOG (narrative style, explains why not just what)
- Keep manual tagging + trusted publisher auto-publish

### Phase 2: Railguey PyPI artifact tracking
- Add `type: pypi_package` as first-class service type in service registry
- Passive drift detection: compare latest PyPI version vs latest git tag
- Status display: IN_SYNC, GIT_AHEAD, PUBLISH_FAILED
- `depends_on` support: Railway services can gate on `kind: artifact_published`
- Verify publish: poll PyPI after tag push, configurable timeout

### Rejected: commitizen + python-semantic-release
- Process overhead (conventional commit enforcement) exceeds benefit at current scale
- Auto-generated changelogs inferior to hand-written narrative changelogs
- Poor ecosystem fit — forges use skills, not commit hooks
- Re-evaluate when release cadence exceeds 2/week or outside contributors join

## Evidence
- 6 research findings, 2 CONFIRMED, 4 REASONED
- 2 independent LLM consultations (GPT-5.2, Gemini 2.5 Pro) confirmed approach
- Web research: trusted publishing is industry standard, no existing PyPI+Railway bridge tool
- Scoring: minimal-fix 39, railguey-pypi 36, full-automation 24

## Consequences
- All Eidos packages get single-source version (breaking change to __init__.py import pattern)
- Railguey scope expands to track non-Railway artifacts (PyPI packages)
- Scope creep risk mitigated by limiting to PyPI only, not Docker/NPM/etc
