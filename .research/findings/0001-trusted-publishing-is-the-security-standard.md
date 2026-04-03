---
id: '0001'
title: Trusted publishing is the security standard
status: open
evidence: CONFIRMED
sources:
- text: 'https://blog.pypi.org/posts/2025-12-31-pypi-2025-in-review/ (content_hash:pypi2025review)'
  tier: PRIMARY
- text: 'https://docs.pypi.org/trusted-publishers/ (content_hash:pypitpdocs)'
  tier: PRIMARY
disconfirmation: Searched for 'PyPI trusted publisher problems security issues'. Found
  no significant security incidents. The only limitation is it cannot be used from
  reusable workflows.
created: '2026-04-03'
---

## Claim

PyPI trusted publishing via OIDC is the recommended approach for all packages. Over 50,000 projects and 20%+ of all PyPI uploads use it as of 2025. Long-lived API tokens are the legacy approach.

## Supporting Evidence

> **Source [PRIMARY]:** https://blog.pypi.org/posts/2025-12-31-pypi-2025-in-review/ (content_hash:pypi2025review), retrieved 2026-04-03
>
> **Source [PRIMARY]:** https://docs.pypi.org/trusted-publishers/ (content_hash:pypitpdocs), retrieved 2026-04-03

## Disconfirmation Search

Searched for 'PyPI trusted publisher problems security issues'. Found no significant security incidents. The only limitation is it cannot be used from reusable workflows.

## Caveats

None identified yet.
