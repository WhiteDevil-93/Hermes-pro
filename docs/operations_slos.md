# Hermes SLO Dashboards and Alerts

This document defines production dashboards and alerting focused on run reliability and capacity.

## Service Level Objectives

- Run success rate SLO: **99.0% over 30 days**.
- Phase timeout SLO: **<1.0% of runs** hit global timeout over 30 days.
- Queue depth SLO: **p95 queue depth <= 5** for 5-minute windows.

## Dashboard 1: Run Outcomes

Panels:
- Run count by status (`complete`, `failed`) grouped by extraction mode.
- Failure rate (`failed / total`) over 5m, 1h, 24h.
- Top failure reasons from `RUN_FAILED` signal payload.

Primary alert:
- `hermes_run_failure_rate_high`
- Trigger: 5m failure rate > 5% AND at least 20 runs in window.
- Severity: page.

Secondary alert:
- `hermes_run_failure_rate_burn`
- Trigger: 1h failure rate > 2% OR 24h failure rate > 1.2%.
- Severity: ticket.

## Dashboard 2: Phase Timeout and Latency

Panels:
- Count of failures where `failure_reason` includes `Global timeout exceeded`.
- Phase dwell time percentile (p50/p95/p99) inferred from `PHASE_TRANSITION` signal timestamps.
- AI latency from `AI_RESPONDED.payload.latency_ms`.

Primary alert:
- `hermes_global_timeout_spike`
- Trigger: > 3 timeout failures in 10 minutes.
- Severity: page.

Secondary alert:
- `hermes_phase_latency_regression`
- Trigger: p95 dwell time in `NAVIGATE` or `ASSESS` > 2x 7-day baseline for 15 minutes.
- Severity: ticket.

## Dashboard 3: Queue and Concurrency

Panels:
- Active run count (`status=running`) from `/api/v1/runs`.
- Queue depth from run admission path (created minus started).
- Abort count from `/runs/{id}/abort`.

Primary alert:
- `hermes_queue_depth_high`
- Trigger: queue depth > 10 for 10 minutes.
- Severity: page.

Secondary alert:
- `hermes_queue_stall`
- Trigger: queue depth increasing for 15 minutes while completion rate is near zero.
- Severity: page.

## Implementation Notes

- Prefer extracting metrics from signals ledger (`signals.jsonl`) if direct metrics export is unavailable.
- Correlate by `run_id` and `phase_at_failure`.
- Include `error_code` from structured error telemetry for drill-down.
