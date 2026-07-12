# HexStrike Offensive Core

Unified battle stack: skills, agent capabilities, modules, and attack phases.

## Skills map

| Category | Purpose | Entry points |
|----------|---------|--------------|
| practice-test | Stress + e2e | `run-mev-stress.sh`, `run-bsc-fork-stress.sh`, `run-mev-live-stress.sh` |
| studying | PnL classifiers | `mev_pnl.py`, `cmd/agent/internal/mev/` |
| workspace-search | Artifacts | `artifacts/sandbox/mev-*.json` |
| schedule-tasks | Automation | cron examples below |
| genui | Reports | `mev-*-stress-report.json`, `battle-report.json` |

## Agent capabilities

| Skill | Implementation |
|-------|----------------|
| Reconnaissance | `mempool_live.py`, `mempool_scanner.py` |
| Classification | `internal/mev/*.go`, `classify_*_execution()` |
| Simulation | `*_engine.py`, `fork_offensive.py` |
| PnL analysis | `mev_pnl.py`, `pnl_stress.go` |
| Builder dry-run | `builder_sim.py`, `builder_sim.go` |
| Red-team orchestration | `scripts/sandbox/redteam/08-13` |

## Attack phases

| Phase | ID | Command |
|-------|-----|---------|
| Sandwich | 08 | `08-mev-sandwich-sim.sh` |
| Frontrun | 09 | `09-mev-frontrun-gas-race.sh` |
| JIT | 10 | `10-mev-jit-liquidity.sh` |
| Backrun | 11 | `11-mev-backrun-arb.sh` |
| Fork offensive | 12 | `12-fork-offensive-mempool.sh` |
| Battle sync | 13 | `13-battle-offensive-rescue-sync.sh` |

## CLI

```bash
# Anvil full stack (C)
hexstrike-agent mev -v

# BSC fork (D)
hexstrike-agent mev fork -v

# Live pipeline — production hardening (read-only)
hexstrike-agent mev live -v

# Full battle 01-13
hexstrike-agent battle -v
```

## Environment (production-hardening)

```bash
# Live mempool (read-only)
BSC_HTTP_URL=https://bsc-dataseed.binance.org
MEV_MEMPOOL_BLOCK_DEPTH=5
MIN_VICTIM_WEI=100000000000000000
MEV_SANDBOX_ONLY=1

# Builder sim (no submit)
BUILDER_SIM_ONLY=1
BUILDER_TIP_WEI=50000000000000000
PUISSANT_ENDPOINT=https://puissant-builder.48.club/

# Hard gate — never set in sandbox
# MEV_MAINNET_SUBMIT=1  # BLOCKED
```

## Cron examples

```cron
0 */6 * * * cd /workspace && bash scripts/sandbox/run-mev-stress.sh
0 3 * * *   cd /workspace && bash scripts/sandbox/run-bsc-fork-stress.sh
0 4 * * *   cd /workspace && bash scripts/sandbox/run-mev-live-stress.sh
```

## Artifacts

| File | Content |
|------|---------|
| `mev-live-mempool-scan.json` | Live BSC mempool candidates |
| `mev-live-pipeline-result.json` | Full pipeline output |
| `mev-builder-sim.json` | Puissant dry-run |
| `battle-report.json` | Defense + offensive + integration scores |

## Safety

- `MEV_SANDBOX_ONLY=1` required for Python engines
- `MEV_MAINNET_SUBMIT=1` is explicitly blocked in live pipeline
- `would_submit: false` in all builder sim artifacts
