---
id: TASK-0006
title: 2 pre-existing test_orchestrate failures (preflight migrations-unsynced) tied to skip_deploys WIP
status: To Do
created: '2026-08-19'
priority: Low
tags:
  - tests
  - wip
acceptance-criteria:
  - python -m pytest tests/ -q fully green on main
---
tests/test_orchestrate.py::TestPreflight::test_migrations_dependency_unsynced_blocks (+1) failing before and after the 2026-08-19 domain-lifecycle work; appears tied to the uncommitted skip_deploys / variable_set WIP in tools.py + cli.py (autostashed through 4 rebases today, preserved). Whoever lands that WIP should make these green in the same change; if the WIP is abandoned, revert the working-tree diff instead.
