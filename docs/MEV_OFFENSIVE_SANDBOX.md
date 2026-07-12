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

# BSC fork — real Pancake WBNB/USDT reserves, sim-only PnL
hexstrike-agent mev fork -v
# or:
./scripts/sandbox/run-bsc-fork-mev.sh

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


```
sandwich → frontrun → backrun → JIT
     ↓
BSC fork (real data, sim only)
```
