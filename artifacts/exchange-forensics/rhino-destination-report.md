# Rhino.fi Destination Chain Trace

**Generated:** 2026-07-10  
**Mode:** read-only on-chain

## BSC Deposits to Rhino.fi Bridge

| Metric | Value |
|--------|-------|
| Bridge (BSC) | `0xb80a582fa430645a043bb4f6135321ee01005fef` |
| Sample deposit txs parsed | 9 |
| Total USDT to Rhino (parsed) | **105,621.34** |
| Unique senders | **43** |

### Top senders (BSC → Rhino)

| Address | USDT | Role |
|---------|------|------|
| `0x730ea0231808f42a20f8921ba7fbc788226768f5` | 19,133.83 | Authority (EIP-7702) |
| `0x2a3cba35c2b427850c2047b2d79164a6227ebe7b` | 5,972.97 | Hop from hot wallet |
| `0x6977262a9a9b2eaaf7c20903b45798b1676ea7fd` | 4,998.67 | Hop from hot wallet |
| `0xd0b5b1fa9122696bcab0cc5d5f4421e6d94a9e52` | 4,000.00 | Hop from hot wallet |

## Destination chains (Rhino.fi contracts)

| Chain | Bridge contract |
|-------|-----------------|
| Ethereum | `0xbca3039a18c0d2f2f84ba8a028c67290bc045afa` |
| Arbitrum | `0x10417734001162Ea139e8b044DFe28DbB8B28ad0` |
| Base | `0x2f59e9086ec8130e21bd052065a9e6b2497bb102` |

## Findings

1. **BSC off-ramp confirmed** — hop wallets deposit USDT into Rhino.fi bridge (not direct CEX).
2. **Hot wallet multichain** — prior recon shows ~634k USDC on **BASE** (56% of portfolio); likely bridge destination.
3. **Rhino API** — `GET /bridge/history/bridge/by-deposit-hash/{tx}` requires JWT; use Rhino Console or Blockscan for withdraw hash.
4. **CEX on destination** — not confirmed in this pass; need withdraw-side trace on BASE/ETH/ARB.

## Next steps

1. Blockscan multichain outflows: https://blockscan.com/address/0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA
2. Per deposit tx — Rhino withdraw hash → destination recipient address
3. Scan BASE USDC outflows from hot wallet for OKX/Bybit/Binance labels
