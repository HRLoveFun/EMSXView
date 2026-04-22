# 语言设置 / Language Setting

所有 AI 回复（解释、分析、建议、问题描述等）**必须使用简体中文**，代码、变量名、文件路径、命令等技术内容除外。

---

# EMSX Trading Platform — Iterative Update Guidelines

## Core Principle

This workspace uses an **automatic iterative update mechanism** that continuously learns from past interactions, adapts to project changes, and prioritizes improvements. All agents must follow these rules.

## Knowledge Base

Before starting any task, consult the knowledge base in `.github/knowledge/`:

- [error-patterns.md](.github/knowledge/error-patterns.md) — Known error signatures and proven resolutions
- [user-needs.md](.github/knowledge/user-needs.md) — Recurring user needs and automation status
- [architecture-decisions.md](.github/knowledge/architecture-decisions.md) — Architectural decisions and review schedule
- [iteration-log.md](.github/knowledge/iteration-log.md) — Audit trail of all iterations
- [metrics.md](.github/knowledge/metrics.md) — Self-assessment metrics and mechanism health

## After Every Task

1. **Error Resolution**: If you resolved an error, check if it matches an existing pattern in `error-patterns.md`. If yes, verify the resolution still works. If it's new and recurring (appeared 2+ times), add it as a new pattern entry.

2. **User Need Detection**: After fulfilling a request, check if it matches a tracked need in `user-needs.md`. If the same type of request has appeared before, update the frequency count. If it's a new recurring pattern, add it.

3. **Architecture Impact**: If your changes affect project structure or add significant code, check `architecture-decisions.md` for relevant decisions. Log new architectural choices.

4. **Iteration Logging**: Append an entry to `iteration-log.md` with: date, type (error/need/architecture/task/mechanism), trigger, action taken, and outcome.

## Commit Message Format

Use this format for all commits: `{type}: {description} – iteration #{log_entry_number}`

Types: `fix`, `feat`, `refactor`, `docs`, `chore`, `perf`

## Rollback Rule

If a change causes test failures or system instability:
1. Revert to the last working state immediately
2. Log the failure in `iteration-log.md` with diagnostic data
3. Record the failed approach in `error-patterns.md` to prevent retry
4. Propose an alternative fix with justification

## Project Context

- **Architecture**: See [docs/MEMORY.md](docs/MEMORY.md) for design decisions and API contracts
- **Development Guide**: See [docs/CLAUDE.md](docs/CLAUDE.md) for common tasks and verification checklists
- **Known Issues**: See [docs/HANDOFF.md](docs/HANDOFF.md) for open blockers and recent fixes
- **Backend**: FastAPI + blpapi on port 3000 (`Execution/backend/api/main.py`)
- **Frontend**: React + TypeScript + Vite on port 5173 (`Execution/frontend/src/`)
- **CostView**: Python pipeline with SQLite databases (`CostView/src/`)

## Key Reminders

- Backend requires **restart** after Python code changes to take effect
- Bloomberg EMSX fields must be in the subscription list to be received
- Bloomberg field types (str/int/float) must match the parser used
- Log level defaults to WARNING — use WARNING+ for diagnostic messages
- Always run tests before and after changes to detect regressions
