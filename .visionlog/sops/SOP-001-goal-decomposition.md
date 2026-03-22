---
id: "SOP-001"
type: "sop"
title: "Goal Decomposition"
status: "active"
date: "2026-03-22"
---

## When to use this

When a visionlog goal has no ike.md tasks yet, or when starting work on a goal that is `available` or `in-progress`. Do not create tasks without first consulting this SOP.

## Steps

1. **Read the goal** — call `visionlog.goal_view(id)`. Understand the exit criteria, dependencies, and what "complete" means.

2. **Check guardrails** — call `visionlog.guardrail_list(status: active)`. Identify any guardrails that constrain how this goal is executed. If a proposed approach would violate one, stop and redesign before proceeding.

3. **Propose milestones** — decompose the goal into 1–3 milestones. A milestone is a meaningful, demonstrable checkpoint — not a task list. Ask: what intermediate states of the world would prove we are on track?

4. **Create milestones in ike.md** — call `ike.milestone_create` for each milestone. Name them after the outcome, not the activity.

5. **Decompose each milestone into tasks** — for each milestone, identify the atomic work items. A task should be completable in one session. Call `ike.task_create` for each with:
   - `visionlog_goal_id` set to the goal's ID
   - `milestone` set to the milestone ID
   - `priority` reflecting urgency
   - `acceptance_criteria` defining what done looks like

6. **Update goal status** — if the goal was `locked`, check whether its `depends_on` goals are complete. If yes, call `visionlog.goal_update(status: available)`. If you are starting work now, set `in-progress`.

## Guards

- Never create tasks without reading the goal and active guardrails first
- A goal should have no more than 3 milestones unless the scope demands it — if it does, the goal is probably too large and should be split
- Every task must have `acceptance_criteria` — a task without a definition of done will never be verifiably complete
- Do not skip directly from goal to tasks — the milestone layer is what connects strategy to execution
