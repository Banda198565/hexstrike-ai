# Critical alert paging (operator-owned)

## Wiring (code)

| Path | Behavior |
| --- | --- |
| Python `append_alert` | jsonl + `alert_paging.maybe_page` |
| Go `Engine.OnCritical` | kill switch + async `alerting.PageCritical` |

## Env

```bash
export ALERT_PAGING_ENABLED=true
export ALERT_WEBHOOK_URL=https://hooks.slack.com/services/...   # or PD Events proxy
export ALERT_PAGING_TIMEOUT_SEC=5
export ALERT_PAGING_SEVERITIES=critical,high
```

## Routed kinds (minimum)

`rpc_mismatch`, `direct_rpc_unavailable`, `BLOCK_COMPROMISED_FUNDER`, `post_sign_drift`, other `BLOCK_*`, `paging_drill`.

## Drill

```bash
export ALERT_PAGING_ENABLED=true
export ALERT_WEBHOOK_URL=...
python3 scripts/ops/paging_drill.py
# expect exit 0 + artifacts/ops/paging-drill-<ts>.json + paging-delivery.jsonl
```

## Evidence for GO_LIVE §7

- Drill JSON with `"verdict":"PASS"`
- Screenshot / on-call ack of the test page
- Confirm production webhook is not pointing at a personal sandbox forever
