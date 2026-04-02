# Self-Assessment Criteria Reference

## Metric Definitions

### Error Resolution
| Metric | Definition | Target | Measurement |
|--------|-----------|--------|-------------|
| Patterns Recorded | Total error patterns in KB | Growing | Count entries in error-patterns.md |
| Resolution Rate | Patterns with status=Resolved / Total | ≥ 90% | Count statuses |
| Repeat Rate | Errors that recurred after being "resolved" | ≤ 10% | Count re-opened patterns |
| Avg Resolution Time | Time from first detection to resolution | Decreasing | From iteration-log timestamps |
| KB Hit Rate | Errors resolved using existing KB pattern / Total errors | ≥ 50% | From iteration-log actions |

### User Needs
| Metric | Definition | Target | Measurement |
|--------|-----------|--------|-------------|
| Needs Identified | Total tracked needs | Growing | Count entries in user-needs.md |
| Needs Automated | Needs with status=Automated | Increasing | Count statuses |
| Request Reduction | Decrease in manual requests for automated needs | ≥ 50% | Compare frequency before/after |
| Automation Accuracy | Automated solutions that actually work | ≥ 80% | User feedback, re-request rate |

### Architecture
| Metric | Definition | Target | Measurement |
|--------|-----------|--------|-------------|
| Reviews Completed | Architecture reviews performed | ≥ 1/month | Count in iteration-log |
| Decisions Current | Decisions not past review date | 100% | Check dates in architecture-decisions.md |
| Debt Items | Outstanding technical debt items | Stable or decreasing | Count in architecture-decisions.md |
| Refactoring Progress | Planned refactoring steps completed | On schedule | Compare plan vs actual |

### Task Planning
| Metric | Definition | Target | Measurement |
|--------|-----------|--------|-------------|
| Plans Generated | Tasks with formal plans | Increasing | Count plan entries |
| Checkpoint Pass Rate | Checkpoints passed first time / Total | ≥ 80% | From plan execution logs |
| Revision Rate | Plans that needed mid-execution changes | ≤ 30% | Count revisions |
| Estimation Accuracy | Actual sub-tasks vs estimated sub-tasks | Within ±20% | Compare plan vs actual |

### Mechanism Health
| Metric | Definition | Target | Measurement |
|--------|-----------|--------|-------------|
| Hook Success Rate | Hooks executed without error / Total | ≥ 95% | From hook logs |
| KB Freshness | Days since last KB update | ≤ 14 days | Check file timestamps |
| Component Coverage | Active components / Total designed | 100% | Inventory check |
| Self-Improvement Rate | Mechanism changes per assessment | ≥ 1 | Count mechanism-type entries |

## Assessment Thresholds

| Overall Health | Criteria |
|---------------|----------|
| **Healthy** | All metrics at target or improving |
| **Attention Needed** | 1-2 metrics below target |
| **Action Required** | 3+ metrics below target or any critical metric failed |

## Improvement Template

```markdown
### Improvement: {Title}
- **Metric**: {Which metric this addresses}
- **Current Value**: {Current measurement}
- **Target Value**: {Goal}
- **Root Cause**: {Why the metric is underperforming}
- **Proposed Change**: {Specific edit to instructions/skill/hook/agent/MCP}
- **Affected File(s)**: {File paths}
- **Expected Impact**: {How this will improve the metric}
- **Verification**: {How to confirm the improvement worked}
```

## Adaptation Triggers

The mechanism should extend its capabilities when:
- A new framework or tool is added to the project → add relevant instructions/checklist items
- A new module is created → update architecture-decisions.md and review checklist
- A new error category is encountered → extend error-patterns categories
- A new type of user request emerges → create a need entry and evaluate for automation
- The project deployment model changes → update hooks and MCP tools
