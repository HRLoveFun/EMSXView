# Self-Assessment Metrics

> Auto-maintained by the iterative update mechanism. Updated during biweekly self-assessment cycles.

## Last Assessment
- **Date**: 2026-05-11
- **Assessor**: Auto-sync

## Error Resolution Metrics
- **Total Patterns Recorded**: 23
- **Patterns Resolved**: 22
- **Patterns Recurring**: 0
- **Avg Resolution Time**: N/A (pre-mechanism)
- **Resolution Rate**: 100%

## User Needs Metrics
- **Total Needs Identified**: 9
- **Needs Automated**: 0
- **Needs In Progress**: 0
- **Request Reduction Rate**: N/A (baseline)

## Architecture Metrics
- **Decisions Logged**: 5
- **Decisions Overdue for Review**: 0
- **Technical Debt Items**: 1 (main.py single-file backend)
- **Refactoring Plans Active**: 0

## Task Planning Metrics
- **Tasks Planned**: 0
- **Checkpoints Passed**: 0
- **Checkpoints Failed**: 0
- **Plans Revised**: 0
- **Planning Accuracy**: N/A (baseline)

## Mechanism Health
- **Instructions Active**: 5
- **Skills Active**: 5
- **Agents Active**: 5
- **Hooks Active**: 3
- **MCP Tools Active**: 8
- **Last Self-Improvement**: 2026-04-23 (metrics baseline sync)
- **Next Assessment Due**: 2026-05-21

## Observations â€” In-Flight

### Batch route concurrency (2026-04-28)
- **Setting**: `BATCH_CONCURRENCY=5` (env-overridable, default in `ExecutionView/backend/api/config.py`).
- **Implementation**: `stream_batch_route` / `stream_batch_modify` use
  `asyncio.Semaphore(BATCH_CONCURRENCY)` to bound in-flight blpapi calls.
- **What to watch in backend logs** (`logger.info`):
  - `batch-route batch total=N concurrency=K wall_ms=W succeeded=â€¦ blocked=â€¦ failed=â€¦` (per request)
  - `batch-route item key=â€¦ status=â€¦ rtt_ms=â€¦` (per item)
- **Caveat**: `bloomberg_adapter._request_lock` already serialises EMSX
  requests at the session level, so client-side concurrency mainly improves
  the ordering of validated submissions, not raw throughput.
- **Tuning criterion**: if a 50-order batch's `wall_ms` is approximately
  `50 Ã— median(rtt_ms)`, EMSX is the bottleneck â€” leave concurrency at 5.
  If `wall_ms < 0.5 Ã— (N Ã— median(rtt_ms))`, consider lowering to 3 to
  reduce burst pressure on the EMSX session.
- **Action**: collect 1 week of logs after rollout; revisit in next assessment.

