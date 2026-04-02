# Sprint 0 Implementation Checklist

**Scope**: Workflow foundation for the EMSX Execution Platform delivery plan
**Source Plan**: `c:/Users/hrchen/Documents/EMSX/docs/EXECUTION_PLATFORM_WBS.md`
**Primary Sprint Key**: `P0-S0`
**Goal**: Create the persistent planning, tracking, CI, and handoff artifacts required before Phase 1 work begins

---

## 1. Sprint 0 outcome

Sprint 0 is complete only when the project has:

- a machine-readable delivery ledger
- a machine-readable risk register
- issue and PR templates linked to sprint metadata
- CI workflows for plan validation, frontend checks, and backend syntax checks
- scripts that can validate the plan, sync progress state, and generate handoff snapshots
- knowledge files ready for automated updates
- automation prompts updated to include sprint/risk/progress context

---

## 2. Execution order

Follow this order exactly:

1. Create the plan ledger and risk register
2. Create the workflow scripts that consume those files
3. Create GitHub issue/PR/workflow artifacts
4. Update knowledge, instruction, and automation files
5. Run validation scripts and generate the first snapshot
6. Review output, then begin Sprint 1 issue creation

---

## 3. Issue-by-issue actionable checklist

## P0-S0-01 - Create machine-readable sprint ledger

### Checklist
- [ ] Create `c:/Users/hrchen/Documents/EMSX/.workbuddy/plans/execution-platform-status.yaml`
- [ ] Include current phase/sprint identifiers
- [ ] Include Sprint 0 issues with dependency links
- [ ] Include placeholder phase/sprint structure for Phases 1-5
- [ ] Ensure issue IDs are unique and dependency references resolve

### Files
- `c:/Users/hrchen/Documents/EMSX/.workbuddy/plans/execution-platform-status.yaml` — master machine-readable status ledger
- `c:/Users/hrchen/Documents/EMSX/.workbuddy/plans/execution-platform-risk-register.yaml` — initial risk register used by gates and handoff generation

### Exit check
- `validate_phase_gate.py --mode plan` succeeds

---

## P0-S0-02 - Wire task and PR workflow templates

### Checklist
- [ ] Create GitHub issue template for issue-sized sprint tasks
- [ ] Create PR template requiring sprint key, dependency list, QA results, and rollback notes
- [ ] Update planning instructions so future planning references the WBS and sprint ledger
- [ ] Record the workflow-governance architecture decision

### Files
- `c:/Users/hrchen/Documents/EMSX/.github/ISSUE_TEMPLATE/execution-platform-task.yml`
- `c:/Users/hrchen/Documents/EMSX/.github/PULL_REQUEST_TEMPLATE/execution-platform.md`
- `c:/Users/hrchen/Documents/EMSX/.github/instructions/task-planning.instructions.md`
- `c:/Users/hrchen/Documents/EMSX/.github/knowledge/architecture-decisions.md`

### Exit check
- New issues and PRs can be opened with required sprint metadata

---

## P0-S0-03 - Add CI/QA orchestration

### Checklist
- [ ] Create CI workflow for plan validation, backend syntax, and frontend checks
- [ ] Create progress workflow for snapshot generation and artifact publication
- [ ] Ensure workflows call the new validation/sync scripts
- [ ] Keep workflows safe even when backend integration tests are not yet available in CI

### Files
- `c:/Users/hrchen/Documents/EMSX/.github/workflows/execution-platform-ci.yml`
- `c:/Users/hrchen/Documents/EMSX/.github/workflows/execution-platform-progress.yml`
- `c:/Users/hrchen/Documents/EMSX/scripts/workflow/validate_phase_gate.py`
- `c:/Users/hrchen/Documents/EMSX/scripts/workflow/sync_execution_status.py`
- `c:/Users/hrchen/Documents/EMSX/scripts/workflow/generate_handoff_snapshot.py`

### Exit check
- Workflow YAML validates
- Local script execution completes without syntax errors

---

## P0-S0-04 - Add automated progress and handoff updates

### Checklist
- [ ] Add managed sections to metrics and iteration log files
- [ ] Update daily session-capture prompt to ingest sprint/risk state
- [ ] Update handoff-merge prompt to consume generated snapshot artifacts
- [ ] Generate the first progress JSON snapshot
- [ ] Generate the first handoff snapshot markdown

### Files
- `c:/Users/hrchen/Documents/EMSX/.workbuddy/knowledge/metrics.md`
- `c:/Users/hrchen/Documents/EMSX/.workbuddy/knowledge/iteration-log.md`
- `c:/Users/hrchen/Documents/EMSX/.workbuddy/automations/session-capture-daily/automation.toml`
- `c:/Users/hrchen/Documents/EMSX/.workbuddy/automations/handoff-merge-daily/automation.toml`
- `c:/Users/hrchen/Documents/EMSX/docs/generated/execution-platform-handoff.md` (generated)
- `c:/Users/hrchen/Documents/EMSX/docs/generated/execution-platform-status.json` (generated)

### Exit check
- `sync_execution_status.py` updates managed sections successfully
- `generate_handoff_snapshot.py` produces a readable handoff artifact

---

## 4. Validation checklist

Run these validations before declaring Sprint 0 complete:

- [ ] `validate_phase_gate.py --mode plan`
- [ ] `sync_execution_status.py --output-json docs/generated/execution-platform-status.json`
- [ ] `generate_handoff_snapshot.py --output docs/generated/execution-platform-handoff.md`
- [ ] Frontend CI workflow syntax reviewed
- [ ] Progress workflow syntax reviewed
- [ ] Managed sections appear in metrics and iteration log
- [ ] Architecture decision log updated

---

## 5. Ready-for-Sprint-1 gate

Sprint 1 may begin only when all are true:

- [ ] `P0-S0-01` through `P0-S0-04` are marked complete in the status ledger
- [ ] No open critical risk in the risk register blocks Phase 1
- [ ] `docs/EXECUTION_PLATFORM_WBS.md` and the machine-readable ledger are aligned
- [ ] Issue template is used to open Sprint 1 tasks
- [ ] First progress snapshot exists under `docs/generated/`

---

## 6. Immediate next action after Sprint 0

Open Sprint 1 issues for:

1. Postgres service and backend dependency bootstrap
2. DB schema + repository foundation
3. projection persistence
4. realtime gateway bootstrap
