---
title: 'Full Automation — commitizen + semantic-release'
verdict: provisional
---

## What It Is

Adopt conventional commits, commitizen for version bumping, python-semantic-release for changelog generation and GitHub Releases. Enforced via pre-commit hooks and CI. Fully automated: merge → version bump → changelog → tag → PyPI → GitHub Release.

## Validation Checklist

- [ ] Claim 1: Y — placeholder, replaced by specific claims
- [ ] Conventional commit enforcement improves commit message quality across contributors: Y — but at process cost that exceeds benefit for small teams
- [ ] Auto-generated changelogs are as useful as hand-written ones for end users: Y — conventional commits do enforce discipline, but at process cost

## Scoring
## Scores

| Criterion | Score |
|-----------|-------|
| implementation_effort | 3/10 |
| correctness | 8/10 |
| maintainability | 5/10 |
| ecosystem_fit | 4/10 |
| risk | 4/10 |
| **Total** | **24** |

**Notes:** High implementation cost. Conventional commits conflict with our narrative commit style. Auto-generated changelogs inferior to hand-written. Creates ongoing tooling burden. Poor ecosystem fit — forges use skills not commit hooks.
