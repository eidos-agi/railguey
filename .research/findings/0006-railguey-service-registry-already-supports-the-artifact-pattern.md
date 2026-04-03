---
id: '0006'
title: Railguey service registry already supports the artifact pattern
status: open
evidence: REASONED
sources:
- text: 'Direct inspection: railguey/registry/service-registry.yaml (content_hash:svcregya)'
  tier: PRIMARY
- text: 'GPT-5.2 consultation via PAL — confirmed pypi_package as artifact not running
    service'
  tier: EXPERT
created: '2026-04-03'
---

## Claim

Railguey's service-registry.yaml already has type (railway_service, migrations), deploy.mode, depends_on with gate semantics, and health checks. Adding type: pypi_package fits naturally — it's an artifact with publication state instead of HTTP health. Depends_on with kind: artifact_published gates Railway deploys on PyPI availability.

## Supporting Evidence

> **Source [PRIMARY]:** Direct inspection: railguey/registry/service-registry.yaml (content_hash:svcregya), retrieved 2026-04-03
>
> **Source [EXPERT]:** GPT-5.2 consultation via PAL — confirmed pypi_package as artifact not running service, retrieved 2026-04-03

## Caveats

None identified yet.
