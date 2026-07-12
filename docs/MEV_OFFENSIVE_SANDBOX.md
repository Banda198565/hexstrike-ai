# HexStrike MEV Offensive Module (Sandbox)

**Scope:** Anvil / local fork only. Offensive simulation aligned with 2026 MEV taxonomy ([Mintarex MEV guide](https://mintarex.com/en/blog/mev-maximum-extractable-value-explained-avoid)).

## Attack patterns implemented

| Pattern | Red-team | Engine |
|---------|----------|--------|
| **Sandwich** | `08-mev-sandwich-sim` | `scripts/sandbox/mev/sandwich_engine.py` + `MockAMM.sol` |
| **Front-run (gas race)** | `09-mev-frontrun-gas-race` | higher gas → earlier block index |
| **Mempool classify** | — | `cmd/agent/internal/mev/` + `mempool_scanner.py` |

**Backlog (sandbox):** JIT liquidity on concentrated-liquidity mock pool.

## BSC note

Article: BNB Chain uses **builder-validator MEV** (48Club Puissant). HexStrike already has `PuissantRelay` for bundle submission — offensive module uses that path in **simulation**, not mainnet victim targeting.

## Commands

```bash
cd cmd/agent && go test ./internal/mev/ -v
./bin/hexstrike-agent mev -v          # mempool scan + sandwich on Anvil
./bin/hexstrike-agent battle -v       # full suite incl. 08/09
```

## Artifacts

- `artifacts/sandbox/mev-mempool-scan.json`
- `artifacts/sandbox/mev-sandwich-result.json`

## Chain guard

All MEV scripts refuse `chain_id != 31337`.
