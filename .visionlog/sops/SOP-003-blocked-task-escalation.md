---
id: "SOP-003"
type: "sop"
title: "Blocked Task Escalation"
status: "active"
date: "2026-03-22"
---

## When to use this

When an ike.md task cannot proceed. A blocked task is a signal that the plan is misaligned with reality. Do not leave it blocked without diagnosing why and taking explicit action.

## Steps

1. **Record the blockage** — call `ike.task_edit(task_id, status: "In Progress")` and add a note with the reason. Name the reason precisely. Vague blocked reasons ("can't proceed") are not acceptable.

2. **Diagnose the type** — determine which category applies:

   **A. Dependency** — another task or goal must complete first.
   Action: verify the dependency in ike.md or visionlog. Update `dependencies` on the task if not already set. Wait or switch to unblocked work.

   **B. Information gap** — the task cannot be completed because knowledge is missing.
   Action: open a research.md project to find the answer. Call `research.project_init` with a clear question. Update the blocked task's notes with the research project ID. Return to this task when the research project is decided.

   **C. Contradiction** — the task conflicts with a visionlog guardrail or ADR.
   Action: this is a serious escalation. The task as written is invalid. Either (a) redesign the task to comply, or (b) if the contract itself is wrong, open a research.md project to earn a new decision that supersedes the existing ADR. Do not proceed with a task that violates a guardrail.

   **D. Resource or access constraint** — the agent lacks a tool, permission, or capability.
   Action: create a high-priority task assigned to a human (`assignees: ["human"]`) describing the missing capability. The original task remains blocked until the human task is resolved.

3. **Never leave a task blocked without a linked action** — every blocked task must have either a dependency link, a research project ID in its notes, a redesigned scope, or a human-assigned task waiting for it.

## Guards

- A blocked task with no diagnosis is invisible debt — it will sit in the backlog forever
- Do not spawn a research.md project for questions that can be answered by reading existing visionlog ADRs or SOPs first
- A contradiction with a guardrail is never a blocker to work around — it is a signal to stop and govern
