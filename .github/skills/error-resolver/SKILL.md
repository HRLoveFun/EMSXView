---
name: error-resolver
description: "Resolve recurring errors using pattern recognition. Use when debugging repeated failures, analyzing error logs, investigating test regressions, or when the same error signature appears more than once."
---
# Error Resolver

## When to Use
- A test failure or runtime error recurs (same signature 2+ times)
- Error logs show repeated patterns across sessions
- A known fix failed and an alternative is needed
- After a deployment causes regressions

## Procedure

### Step 1: Parse the Error
- Extract: error message, exception type, stack trace, affected files
- Identify the error signature (the stable part that recurs, not instance-specific data like timestamps)

### Step 2: Search Knowledge Base
- Read [error-patterns.md](../../knowledge/error-patterns.md) for matching signatures
- If match found â†’ go to Step 3a
- If no match â†’ go to Step 3b

### Step 3a: Apply Known Resolution
- Follow the documented resolution steps
- Verify the fix still applies to current codebase (files/functions may have changed)
- If the resolution no longer works â†’ go to Step 4

### Step 3b: Analyze Context
- Gather: stack traces, recent code changes (git diff), environment state, Bloomberg connection status
- Check if similar patterns exist (partial signature match)
- Identify root cause with specific evidence

### Step 4: Generate Fix
- If a previous fix exists and failed, propose an **alternative** approach with justification for why it differs
- Design the fix to address root cause, not just symptoms
- For Bloomberg-related errors, verify: field in subscription, parser matches type, frontend mirrors backend

### Step 5: Validate
- Run affected unit tests
- Run integration tests if the fix crosses module boundaries
- If tests fail â†’ iterate on the fix (back to Step 4, max 3 attempts)

### Step 6: Update Knowledge Base
- Add or update the pattern in [error-patterns.md](../../knowledge/error-patterns.md) using the format in [resolution-workflow.md](./references/resolution-workflow.md)
- If a previous approach failed, document it as a "Failed Approach" in the pattern entry

### Step 7: Log Iteration
- Append entry to [iteration-log.md](../../knowledge/iteration-log.md): date, type=error, trigger, action, outcome

## Reference
- [Resolution Workflow](./references/resolution-workflow.md) â€” Decision tree, pattern entry template, failed-approach documentation

