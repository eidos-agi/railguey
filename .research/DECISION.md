# Decision

**Date:** 2026-04-03
**Status:** Decided
**ADR:** ADR to be created in railguey visionlog

## Decision

Adopt BOTH minimal-fix AND railguey-pypi. Reject full-automation. Phase 1: fix version single-source-of-truth with importlib.metadata across all Eidos packages (immediate, low effort). Phase 2: add type: pypi_package to railguey's service registry with passive drift detection (MVP). Skip commitizen/semantic-release — not justified at current scale.

## Rationale

Minimal-fix scored highest (39) on efficiency — it solves the immediate pain (two-file version sync) with zero new dependencies. Railguey-pypi scored second (36) but highest on correctness and ecosystem_fit — it solves a problem nobody else addresses and fits naturally into railguey's existing schema. These are complementary, not competing: minimal-fix standardizes the release pipeline, railguey-pypi gives deployment visibility. Full-automation scored lowest (24) — the process overhead of conventional commits and auto-generated changelogs exceeds the benefit for a small team with low release cadence. Two independent LLM consultations (GPT-5.2, Gemini 2.5 Pro) confirmed this assessment. Re-evaluate full-automation when release cadence exceeds 2/week or outside contributors join.
