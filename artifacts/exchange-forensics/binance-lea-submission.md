# Binance Law Enforcement Request — Draft Pack

**Generated:** 2026-07-10  
**Submit via:** https://www.binance.com/en/support/law-enforcement  
**Chain:** BSC (BNB Smart Chain, chainId 56)

---

## Request Summary

We request identification of the Binance account (KYC) associated with a withdrawal of **1,100,000 USDT** from **Binance Hot Wallet 11** to an unlabeled multichain operations wallet.

| Field | Value |
|-------|-------|
| Withdraw TX | `0x8f56f5e9c9a194202ff21f1002774eb0a8fb746c45cf519321cf0ceb1083e407` |
| Block | 108946611 |
| Timestamp (UTC) | 2026-07-09 08:19:48 |
| From | `0x161ba15a5f335c9f06bb5bbb0a9ce14076fbb645` (Binance Hot Wallet 11) |
| To | `0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA` |
| Amount | 1,100,000 BSC-USD (Binance-Peg USDT) |
| Token contract | `0x55d398326f99059fF775485246099027B3197955` |

**BscScan:** https://bscscan.com/tx/0x8f56f5e9c9a194202ff21f1002774eb0a8fb746c45cf519321cf0ceb1083e407

---

## Related Addresses

| Role | Address |
|------|---------|
| Hot wallet (recipient) | `0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA` |
| Authority (EIP-7702) | `0x730ea0231808f42a20f8921ba7fbc788226768f5` |
| Rhino.fi bridge sink | `0xb80a582fa430645a043bb4f6135321ee01005fef` |
| Operator lab wallet | `0x85dB346BE1d9d5D8ec4F57acf0067FbE53a6E846` |

---

## Timeline

1. **2026-07-09 08:19 UTC** — Binance withdraw +1.1M USDT → hot wallet
2. **Same day (~0.9 day window)** — Hot wallet disburses ~796k USDT to 977 recipients (200–5000 USDT chunks)
3. **Post-disbursement** — Hop wallets forward USDT to Rhino.fi bridge (no direct CEX deposit at depth 0–1)

---

## Information Requested

1. KYC identity and internal account ID for the user who initiated the withdrawal to `0x4943F5E7...`
2. Withdrawal metadata: IP, device fingerprint, 2FA method, address whitelist history
3. Full account transaction history (deposits/withdrawals) 2026-06-15 to present
4. Any deposits **back** to Binance from related addresses listed above

---

## Attachments

- `binance-lea-pack.json`
- `cex-cluster-map.json`
- `entity-id.json`
- `hot-wallet-onchain-graph.json`
- `rhino-bridge-trace.json`
- `cex-depth2-scan.json`

---

## Legal Notes

- Read-only on-chain forensics only; no unauthorized access attempted
- Submit through official Binance Law Enforcement portal with valid legal process documentation
