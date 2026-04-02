---
description: "Use when debugging errors, analyzing test failures, or investigating runtime exceptions. Covers error pattern recognition, knowledge base lookup, and resolution tracking."
applyTo: ["**/*.py", "**/*.ts", "**/*.tsx"]
---
# Error Pattern Recognition

## Before Debugging

1. Read `.github/knowledge/error-patterns.md` for known patterns
2. Compare the current error signature (message, stack trace, affected files) against recorded patterns
3. If a match is found, apply the documented resolution — do not re-analyze from scratch

## When Fixing

1. Identify the root cause with specific evidence (log lines, variable values, code paths)
2. Check if a previous fix for this pattern exists and failed — if so, use an alternative approach
3. Validate the fix by running relevant tests before considering it resolved
4. If the fix involves Bloomberg EMSX fields, verify: field is in subscription list, parser matches field type (str/int/float), frontend interface mirrors backend model

## After Fixing

1. If this error signature appeared 2+ times, add it to `.github/knowledge/error-patterns.md` with:
   - **Signature**: Error message, exception type, and conditions that trigger it
   - **Root Cause**: Why it happens (not just what happens)
   - **Resolution**: Step-by-step fix with file references
   - **Lessons**: What to watch for to prevent recurrence
2. If a previous fix was attempted and failed, document the failure and the alternative that worked
3. Append an entry to `.github/knowledge/iteration-log.md`
