---
description: "Use when analyzing user requests, planning features, reviewing usage patterns, or evaluating automation opportunities for recurring tasks."
---
# User Need Identification

## During Every Task

1. After fulfilling a request, ask: "Is this the kind of task that recurs?"
2. Check `.github/knowledge/user-needs.md` for similar tracked needs
3. If a match exists, update its frequency count

## Identifying New Needs

A need is worth tracking when:
- The same type of request appears 2+ times across sessions
- The request follows a predictable pattern (e.g., "add field X to Y", "fix Z after restart")
- Manual effort is disproportionate to the complexity (e.g., editing 5 files for one field addition)

## Prioritization

Score needs by: **Frequency × Impact ÷ Effort**
- **Frequency**: How often does this request type appear? (1=rare, 5=every session)
- **Impact**: How much time/risk does it save? (1=minor, 5=critical workflow)
- **Effort**: How hard is the automation? (1=trivial, 5=complex)

## Proposing Solutions

For each high-priority need:
1. Design a **generic** solution (skill, prompt, instruction, or code module) that handles the pattern, not just the specific instance
2. Ensure future similar requests become a single configuration change instead of repeated custom work
3. After implementation, set a monitoring flag — if the same request type still appears, refine or replace the solution

## Recording

Add new needs to `.github/knowledge/user-needs.md` with: name, frequency, impact, current solution, proposed automation, status, date.
