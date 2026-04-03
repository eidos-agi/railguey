---
title: Minimal Fix — importlib.metadata + manual releases
verdict: provisional
---

## What It Is

Fix the two-file version problem with importlib.metadata.version(). Keep manual CHANGELOG, manual tagging, trusted publisher does the rest. Add CI guardrails: verify tag == pyproject version, verify CHANGELOG has entry. No new tooling.

## Validation Checklist

- [ ] Claim 1: Y — placeholder, replaced by specific claims
- [ ] importlib.metadata.version() eliminates the two-file sync problem with zero new dependencies: Y
- [ ] CI guardrails (tag == version, changelog entry exists) catch release errors without new tooling: Y — confirmed by Finding 0004 and Python Packaging User Guide

## Scoring
## Scores

| Criterion | Score |
|-----------|-------|
| implementation_effort | 9/10 |
| correctness | 7/10 |
| maintainability | 8/10 |
| ecosystem_fit | 6/10 |
| risk | 9/10 |
| **Total** | **39** |

**Notes:** Highest effort score — 5 minute fix. Solves version sync completely. Manual CHANGELOG is a feature. Doesn't address railguey PyPI awareness (separate concern). Very low risk.
