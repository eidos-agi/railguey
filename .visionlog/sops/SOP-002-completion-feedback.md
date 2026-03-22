---
id: "SOP-002"
type: "sop"
title: "Completion Feedback"
status: "active"
date: "2026-03-22"
---

## When to use this

After completing an ike.md task. Completion is not just marking a task done — it is closing the loop back to the goal. Follow this SOP every time.

## Steps

1. **Complete the task** — call `ike.task_complete(task_id)`. Record completion notes describing what was done and any decisions made during execution.

2. **Check the milestone** — call `ike.task_list(milestone: <milestone_id>)`. If all tasks in the milestone are complete, call `ike.milestone_close(milestone_id)`.

3. **Check the goal** — if a milestone was closed, call `ike.task_list(visionlog_goal_id: <goal_id>, include_completed: false)`. If no open tasks remain for this goal:
   - Call `visionlog.goal_view(id)` — review exit criteria
   - If exit criteria are met, call `visionlog.goal_update(id, status: complete)`
   - If exit criteria are not fully met, create the remaining tasks before updating status

4. **Capture decisions made** — if any non-obvious decisions were made during execution that aren't recorded anywhere, call `visionlog.decision_create` with `status: accepted` to formalize them. A decision made in execution but not recorded is a contract that was never written.

5. **Check unlocks** — call `visionlog.goal_unlockable()`. If completing this goal unlocks others, update their status to `available`.

## Guards

- Never mark a goal complete without checking its exit criteria in visionlog
- If you made a decision during execution, write the ADR — do not leave it in task notes
- Do not skip step 5 — unlocking goals is how the DAG advances
