# Need Tracking Reference

## Scoring Rubric

| Factor | 1 | 2 | 3 | 4 | 5 |
|--------|---|---|---|---|---|
| **Frequency** | Once ever | 2-3 times total | Monthly | Weekly | Every session |
| **Impact** | Cosmetic | Minor convenience | Moderate time savings | Significant workflow improvement | Critical blocker when unaddressed |
| **Effort** | Complex multi-system change | Multi-file refactoring | Single skill/prompt creation | Configuration change | Already possible, just needs documentation |

**Score** = Frequency × Impact ÷ Effort

**Thresholds**:
- Score ≥ 5.0 → Automate immediately
- Score 2.0–4.9 → Plan for next sprint
- Score < 2.0 → Document but defer

## Need Entry Template

```markdown
## Need: {Descriptive Name}

- **Frequency**: {1-5} ({description})
- **Impact**: {1-5} ({description})
- **Effort**: {1-5} ({description})
- **Score**: {calculated}
- **Current Solution**: {How it's done today — manual steps}
- **Proposed Automation**: {Skill/prompt/instruction/module design}
- **Success Criteria**: {Measurable reduction in manual requests}
- **Status**: Identified | In Progress | Automated | Monitoring | Retired
- **Date**: {YYYY-MM-DD first identified}
- **Review Date**: {YYYY-MM-DD next review}
```

## EMSX-Specific Need Categories

### Data Pipeline Needs
- Field additions (subscription → model → parser → frontend → UI)
- Data format transformations (Bloomberg types → display formats)
- Export/import workflows

### Operational Needs
- Backend restart reminders after code changes
- Bloomberg session health monitoring
- Log analysis for error trends

### Development Workflow Needs
- Multi-file coordinated changes
- Test coverage gaps
- Documentation updates after code changes

## Review Process

Every 2 weeks:
1. Re-score all "Identified" needs with updated frequency data
2. Check "Monitoring" needs for effectiveness
3. Retire needs that are fully automated with proven reduction
4. Promote high-score needs to "In Progress"
