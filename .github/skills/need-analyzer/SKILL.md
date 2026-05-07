---
name: need-analyzer
description: "Analyze and prioritize user needs from interaction history. Use when reviewing recurring requests, planning feature additions, evaluating automation opportunities, or deciding what to build next."
---
# Need Analyzer

## When to Use
- Reviewing patterns across multiple sessions
- Planning feature work or sprint priorities
- Evaluating whether a request should become a permanent capability
- Auditing which automations are actually reducing manual work

## Procedure

### Step 1: Scan History
- Read [iteration-log.md](../../knowledge/iteration-log.md) for recent task entries
- Identify request types that appear 2+ times
- Group similar requests by category (e.g., "field additions", "debugging Bloomberg", "UI changes")

### Step 2: Cross-Reference
- Compare findings with [user-needs.md](../../knowledge/user-needs.md)
- For existing needs: update frequency count and last-seen date
- For new patterns: prepare a new entry

### Step 3: Score and Prioritize
- Apply the scoring rubric from [need-tracking.md](./references/need-tracking.md)
- Score = Frequency Ã— Impact Ã· Effort
- Rank all needs by score, highest first

### Step 4: Design Solutions
For the top 3 needs:
1. Determine the right primitive: skill (workflow), prompt (one-shot), instruction (always-on), or code module
2. Design a **generic** solution that handles the pattern class, not just specific instances
3. Define success criteria: what reduction in manual requests constitutes success?

### Step 5: Monitor
- After implementing a solution, set a review date (2 weeks out)
- At review: check if related requests decreased
- If not â†’ refine or replace the solution

### Step 6: Update Knowledge Base
- Update [user-needs.md](../../knowledge/user-needs.md) with new/changed entries
- Append to [iteration-log.md](../../knowledge/iteration-log.md): date, type=need, trigger, action, outcome

## Reference
- [Need Tracking](./references/need-tracking.md) â€” Scoring rubric, entry template, review process

