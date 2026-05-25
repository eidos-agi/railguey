---
id: TASK-0002
title: 'Add CI guardrails: tag == version, CHANGELOG entry required'
status: To Do
created: '2026-04-03'
priority: medium
tags:
  - phase-1
  - ci
  - adr-001
definition-of-done:
  - publish.yml checks tag version == pyproject.toml version
  - publish.yml checks CHANGELOG.md has entry for version
  - Publish fails with clear error if either check fails
  - Template available for all Eidos packages
---
In the publish.yml workflow, before publishing: verify git tag matches pyproject.toml version, verify CHANGELOG.md contains a section for that version. Fail the publish if either check fails.
