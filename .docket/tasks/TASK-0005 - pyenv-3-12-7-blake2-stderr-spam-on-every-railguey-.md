---
id: TASK-0005
title: pyenv 3.12.7 blake2 stderr spam on every railguey/clawdflare invocation
status: To Do
created: '2026-08-19'
priority: Medium
tags:
  - env
  - dx
acceptance-criteria:
  - railguey --version prints zero tracebacks to stderr
  - all editable installs reinstalled and their test suites still green
---
Every CLI from the pyenv 3.12.7 interpreter prints 4 'ValueError: unsupported hash type blake2b/blake2s' tracebacks to stderr at import (hashlib built against an older OpenSSL; runtime now links OpenSSL 3.6.3, 2026-06-09 build). Purely cosmetic today but it corrupts any consumer that reads stderr, hides real errors in noise, and would break anything that actually calls blake2. Fix: 'pyenv install 3.12.7' rebuild against current OpenSSL — WARNING: wipes that version's site-packages, so inventory editable installs first (railguey, clawdflare, felix, aider, resume-resume, claude-session-commons, eidos-dj-daemon, claude-boss at minimum) and reinstall after. Filed here because railguey/clawdflare are the loudest sufferers; the fix is machine-level.
