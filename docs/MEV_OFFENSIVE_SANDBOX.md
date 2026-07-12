# HexStrike MEV Offensive Stack (Sandbox)

Full offensive MEV triad + BSC fork sim. **No mainnet transaction submission.**

Reference: [MEV Explained 2026](https://mintarex.com/en/blog/mev-maximum-extractable-value-explained-avoid)

## Attack matrix

| ID | Pattern | Contract / Engine |
|----|---------|-------------------|
| 08 | Sandwich | `MockAMM.sol` + `sandwich_engine.py` |
| 09 | Front-run gas race | `anvil_setAutomine` ordering |
| 10 | JIT liquidity | `MockCLAMM.sol` + `jit_engine.py` |
| 11 | Back-run arb | `MockRouter.sol` + `backrun_engine.py` |
| fork | BSC real pools | `setup-bsc-fork.sh` + `fork_offensive.py` |

## Go classifiers (`internal/mev`)

- `ClassifySwap` / `IsSandwichCandidate` — mempool swap detection
- `PlanSandwich` — CPAMM sandwich PnL estimate
- `PlanFrontRunGas` — gas premium model
- `PlanJIT` — **fee vs gas** classifier (when JIT is profitable)
- `PlanBackrun` — cross-pool spread model

## Commands

```bash
# Full Anvil stack: sandwich + JIT + backrun
hexstrike-agent mev -v
hexstrike-agent mev full -v

# BSC fork — real Pancake WBNB/USDT reserves, mempool-driven sim-only PnL
hexstrike-agent mev fork -v
# or:
./scripts/sandbox/run-bsc-fork-mev.sh

# Variant D — full BSC fork stress (mempool + real pools + 08–11 on fork)
./scripts/sandbox/run-bsc-fork-stress.sh

# Battle suite (all 11 attacks)
hexstrike-agent battle -v
```

## Artifacts

| File | Content |
|------|---------|
| `mev-sandwich-result.json` | Attacker profit wei |
| `mev-jit-result.json` | JIT fee share vs gas |
| `mev-backrun-result.json` | Cross-pool arb profit |
| `mev-bsc-fork-result.json` | Real reserve sandwich sim |
| `mev-bsc-mempool-scan.json` | Pending Pancake swaps on fork |
| `mev-bsc-fork-stress-report.json` | Variant D pass/fail matrix |

## Chain guards

- Anvil engines: `chain_id == 31337`
- Fork engine: `chain_id == 56`
- `MEV_SANDBOX_ONLY=1` required

## MEV stress testing (Variant B + C)

```bash
# Full suite: unit classifiers + live Anvil e2e (attacks 08–11)
bash scripts/sandbox/run-mev-stress.sh

# Unit tests only (no Anvil)
MEV_STRESS_SKIP_E2E=1 bash scripts/sandbox/run-mev-stress.sh

# E2e only (skip Python/Go unit phase)
MEV_STRESS_SKIP_UNIT=1 bash scripts/sandbox/run-mev-stress.sh
```

### Variant C invariants (Anvil e2e)

| Step | Validates |
|------|-----------|
| Full stack pipeline | `MockAMM` / `MockCLAMM` / `MockRouter` deploy + tx + artifacts |
| `mev_e2e_assert.py` | `profit_wei > 0`, `net_after_gas_wei > 0`, contract addresses |
| JIT skip gate | Classifier blocks mint/burn without `JIT_FORCE_DEMO` |
| Redteam 08–11 | Gas race ordering + engine re-runs on same Anvil session |
| `mev-stress-report.json` | Unified pass/fail matrix |

### Variant D — BSC fork mempool (realistic offensive profile)

```bash
./scripts/sandbox/run-bsc-fork-stress.sh
```

| Step | What happens |
|------|----------------|
| `setup-bsc-fork.sh` | Anvil fork of BSC mainnet (`chain_id=56`) |
| `fork_mempool_seed` | Queue pending Pancake BNB→USDT swaps |
| `mempool_scanner.py` | `txpool_content` + router filter |
| `fork_offensive.py` | Real WBNB/USDT reserves + per-victim PnL |
| Mock engines | `MockAMM` / `MockCLAMM` / `MockRouter` on fork |
| Redteam 09–11 | Same attacks with `REDTEAM_CHAIN_ID=56` (08 = real-pool `fork_offensive`) |

Still **simulation only** — no mainnet bundle submission.

## Production hardening (live pipeline)

```bash
bash scripts/sandbox/run-mev-live-stress.sh
hexstrike-agent mev live -v
```

See [OFFENSIVE_CORE.md](../OFFENSIVE_CORE.md) for full stack map.



```
sandwich → frontrun → backrun → JIT
     ↓
BSC fork (real data, sim only)
```
