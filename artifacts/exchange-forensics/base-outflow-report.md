# BASE USDC Outflow Trace

**Target:** `0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA`  
**Chain:** Base  
**Generated:** 2026-07-10  
**Mode:** read-only (Blockscout API)

## Live snapshot (BaseScan)

| Metric | Value |
|--------|-------|
| USDC balance | **~489,285 USDC** (~71.5% portfolio) |
| Base tx count | **58,075+** |
| First seen | ~23 days ago |

## Scan window

- **800** recent USDC token rows (8 pages × 100)
- Stable: `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`

## Summary

| Metric | Value |
|--------|-------|
| Outflow txs (sample) | **641** |
| Inflow txs (sample) | **159** |
| Unique recipients | **575** |
| USDC out (sample) | **144,584** |
| USDC in (sample) | **16,498** |
| **CEX hits (OKX/Bybit/Binance)** | **0** |
| **DeFi protocol hits (tagged outflows)** | **0** |
| BSC hop correlation | **0** |
| Authority `0x730ea023...` on Base | **Not seen** |

## Pattern: payroll / disbursement hub (same as BSC)

Тот же паттерн, что на BSC: сотни мелких получателей, типичные суммы **100–5000 USDC**. Это **не** прямой вывод на CEX — снова распределительный хаб.

### Top outflow recipients (sample)

| Address | USDC | Tag |
|---------|------|-----|
| `0x99935ebbbc3124e769a0b01edc1597623571e515` | 4,999.70 | — |
| `0xe9dda552afa874c8536d577f4c24ccce2b90d768` | 4,450.00 | — |
| `0x0095e3a0b798d37e7dddd0e24bcac5828d770f46` | 4,000.00 | — |
| `0x94532b77e5d4ed744bbfc616160b1b0312f1f59c` | 3,471.53 | — |

## Cross-chain correlation

| Check | Result |
|-------|--------|
| BSC hops receive on Base? | ❌ Not in sample |
| Authority on Base? | ❌ |
| Rhino bridge → Base recipient match? | Needs Rhino JWT API |

**Inflow note:** в sample есть inflow через **ERC-4337 bundler** `0x0770595e6b3d91ac0c5d676bb795bdeba53e08d8` с calldata **LiFi Diamond** (`0x1231deb6...`) — cross-chain routing **INTO** Base, не outflow на CEX.

## DeFi / L2 (requested check)

| Protocol | Outflow hit | Notes |
|----------|-------------|-------|
| Aave V3 Base | ❌ | No tagged outflow in sample |
| Moonwell | ❌ | No tagged outflow in sample |
| Compound | ❌ | No tagged outflow in sample |
| L2 Standard Bridge | ❌ | No tagged outflow in sample |
| LiFi | ⚠️ | **Inflow** via smart account (not outflow) |

## Verdict

1. **Base = operational treasury**, не CEX off-ramp — ~489k USDC держится и раздаётся по payroll-паттерну.
2. **CEX (OKX/Bybit/Binance) на Base — не найдены** в depth 0–2 по tagged addresses.
3. **Authority `0x730ea023...`** — ключевой узел на **BSC** (Rhino), на Base в sample **не появляется**.
4. **Следующий шаг:** depth-3 scan top-25 Base recipients без label; Arkham/Blockscan label propagation; lending protocol **deposits** (aToken/mToken balance), не только transfers.

## Artifacts

- `artifacts/exchange-forensics/base-outflow-trace.json`
- Script: `python3 scripts/analyze_chain.py --chain base --depth 3`
