---
id: TASK-0004
title: Implement passive PyPI drift detection in railguey status
status: To Do
created: '2026-04-03'
priority: medium
tags:
  - phase-2
  - drift-detection
  - adr-001
definition-of-done:
  - railguey status shows sync state for pypi_package services
  - IN_SYNC when git tag matches PyPI latest
  - GIT_AHEAD when tag exists but PyPI behind
  - Graceful handling of PyPI API failures (UNKNOWN status)
---
For pypi_package services, railguey status compares latest git tag vs latest PyPI version. Reports IN_SYNC, GIT_AHEAD, PUBLISH_FAILED. Uses PyPI JSON API (public, no auth).
