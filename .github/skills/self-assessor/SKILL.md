---
name: self-assessor
description: "Evaluate and improve the iterative update mechanism itself. Use for biweekly self-assessment, after mechanism failures, when adapting to new project patterns, or when mechanism effectiveness is questioned."
---
# Self-Assessor

## When to Use
- Biweekly self-assessment cycle (check `metrics.md` for next due date)
- After a mechanism component fails (hook error, stale knowledge base, wrong pattern match)
- When new project tools, frameworks, or patterns are introduced
- When the user questions whether the mechanism is helping

## Procedure

### Step 1: Compute Metrics
From [iteration-log.md](../../knowledge/iteration-log.md), calculate:
- **Error resolution**: Count of errors resolved, avg time from detection to fix, repeat rate
- **User needs**: Count automated, reduction in related manual requests
- **Architecture**: Reviews completed, decisions updated, refactoring progress
- **Task planning**: Plans generated, checkpoint pass/fail ratio, plans revised
- **Mechanism health**: Hook success rate, MCP tool usage, knowledge base freshness

### Step 2: Compare to Previous
- Read last assessment from [metrics.md](../../knowledge/metrics.md)
- For each metric: improved, same, or degraded?
- Flag any metric that degraded

### Step 3: Identify Improvements
For each degraded or underperforming area:
1. Diagnose: Why is this metric not improving?
2. Propose a specific change to one mechanism component (instruction, skill, hook, agent, or MCP tool)
3. Justify: What evidence suggests this change will help?

### Step 4: Apply Improvements
- Edit the relevant mechanism file(s)
- Add a version comment at the top: `<!-- Updated: YYYY-MM-DD by self-assessor -->`
- Ensure the change doesn't break other components

### Step 5: Record
- Update [metrics.md](../../knowledge/metrics.md) with new assessment data
- Set `Next Assessment Due` date (2 weeks from now)
- Append to [iteration-log.md](../../knowledge/iteration-log.md): date, type=mechanism, trigger=self-assessment, action, outcome

## Reference
- [Assessment Criteria](./references/assessment-criteria.md) â€” Metric definitions, thresholds, improvement templates

