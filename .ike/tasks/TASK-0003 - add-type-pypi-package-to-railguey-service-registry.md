---
id: TASK-0003
title: 'Add type: pypi_package to railguey service registry'
status: To Do
created: '2026-04-03'
priority: high
tags:
  - phase-2
  - registry
  - adr-001
definition-of-done:
  - 'type: pypi_package accepted in service registry YAML'
  - PyPI JSON API client queries latest version for a package
  - railguey status shows PyPI packages with version info
  - 'depends_on with kind: artifact_published supported'
---
Extend the service registry schema to support pypi_package as a service type. Define deploy.mode: pypi_trusted_publisher, deploy.pypi_name, deploy.trigger: tag_push, deploy.verify_publish. Add PyPI API client for version lookup.
