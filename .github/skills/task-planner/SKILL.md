---
name: task-planner
description: "Decompose tasks into implementation plans with checkpoints. Use when receiving new feature requests, bug reports, refactoring tasks, or any multi-step work that needs structured planning and validation gates."
---
# Task Planner

## When to Use
- New feature request requiring changes across multiple files
- Bug fix that touches several modules
- Refactoring task requiring incremental steps
- Any task where the implementation order matters

## Procedure

### Step 1: Parse Requirements
- What is the expected outcome?
- What are the constraints (backward compatibility, performance, Bloomberg API limitations)?
- What does "done" look like? (specific acceptance criteria)

### Step 2: Identify Scope
- List all files that need modification
- List all files that need creation
- Identify test files that need updates
- Check [architecture-decisions.md](../../knowledge/architecture-decisions.md) for relevant constraints

### Step 3: Decompose
Break the task into sub-tasks where each:
- Is independently verifiable (produces a working state)
- Has clear input/output
- Can be described in 1-2 sentences

### Step 4: Order and Define Checkpoints
- Arrange sub-tasks by dependency (use the [planning workflow](./references/planning-workflow.md) templates)
- After each sub-task, define a checkpoint:
  - What tests to run
  - What to visually verify (if UI changes)
  - What invariants must hold

### Step 5: Generate Plan
Produce a structured plan using the template in [planning-workflow.md](./references/planning-workflow.md)

### Step 6: Execute with Validation
- Complete each sub-task in order
- At each checkpoint, run validation
- If checkpoint fails â†’ diagnose â†’ add corrective sub-task â†’ re-validate before continuing

### Step 7: Log
- Append completed task to [iteration-log.md](../../knowledge/iteration-log.md): date, type=task, trigger, action, outcome

## Reference
- [Planning Workflow](./references/planning-workflow.md) â€” Plan template, checkpoint criteria, dynamic replanning rules

