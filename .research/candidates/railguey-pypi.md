---
title: Railguey as PyPI artifact manager
verdict: provisional
---

## What It Is

Add type: pypi_package to railguey's service registry. Railguey tracks PyPI version drift, gates Railway deploys on published artifacts, surfaces sync status. PyPI packages become first-class entities alongside Railway services.

## Validation Checklist

- [ ] Claim 1: Y — placeholder, replaced by specific claims
- [ ] type: pypi_package fits naturally into railguey's existing service registry schema: Y — confirmed by Finding 0006
- [ ] Passive drift detection (PyPI version vs deployed version) provides immediate value with low risk: Y — Finding 0006, confirmed by direct inspection of service-registry.yaml schema

## Scoring
## Scores

| Criterion | Score |
|-----------|-------|
| implementation_effort | 5/10 |
| correctness | 9/10 |
| maintainability | 7/10 |
| ecosystem_fit | 9/10 |
| risk | 6/10 |
| **Total** | **36** |

**Notes:** Moderate effort. Directly solves the deployment visibility gap nobody else addresses. Perfect ecosystem fit — extends railguey's existing registry pattern. Risk: scope creep. Mitigated by PyPI-only scope.
