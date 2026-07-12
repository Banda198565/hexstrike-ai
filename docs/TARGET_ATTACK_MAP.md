# Target Attack Map

Read-only recon, sandbox battle, and operator rescue — **no third-party drain or mainnet submit**.

## Wallets

| Role | Address | Script / workflow | Artifact | MCP tool |
|------|---------|-------------------|----------|----------|
| hot_wallet | `0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA` | `run-field-targets-recon.sh` | `field-recon-bundle.json` | `get_token_transfers` |
| hot_wallet_2 | `0xce648a7c1dd3dabc9cd2f87c93986a98608f1eef` | `hot_wallet_watch.py` | `hot-wallet-watch.json` | `watch_hot_wallet_mempool` |
| treasury_bnb | `0x29bdfbf7d27462a2d115748ace2bd71a2646946c` | `field_targets_recon.py` | `field-recon-bundle.json` | `get_erc20_balance` |
| puissant_validator | `0x4848489f0b2bedd788c696e2d79b6b69d7484848` | `builder_sim.py` | `mev-builder-sim.json` | `builder_sim_dry_run` |
| authority_eip7702 | `0x730ea0231808f42a20f8921ba7fbc788226768f5` | `generate-target-profile.py` | `target-profiles.json` | `get_contract_code` |
| operator_proof | `0x85dB346BE1d9d5D8ec4F57acf0067FbE53a6E846` | `run-operator-rescue-mainnet.sh` | `operator-rescue-puissant.json` | — |
| target_watch | `0x96B23C4680E1a37cE17730e6118D0C9223e72A66` | `deploy-mainnet.sh` | `dummy-bot-events.jsonl` | — |
| safe_funder | `0x060447dC91dfb22A5233731aF67E9E8dafdF24d1` | `dummy_bot.py` (Anvil) | `redteam-report.json` | — |

## Infra

| Role | Host | Script | Artifact | Agent |
|------|------|--------|----------|-------|
| jenkins | `51.250.97.223` | `pentest/jenkins-rpc-enum.sh` | `jenkins-rpc-enum.json` | Agent-Pentest-Jenkins |
| bsc_node | `51.222.42.220` | `pentest/geth-rpc-enum.sh` | `geth-rpc-enum.json` | Agent-Pentest-RPC |
| kz_gateway | `38.107.234.149` | `field_targets_recon.py` (port ping) | `field-recon-bundle.json` | — |
| litellm | `118.196.141.168` | `field_targets_recon.py` (port ping) | `field-recon-bundle.json` | — |

## Battle suite (local Anvil only)

| Attack | Script | Outcome marker |
|--------|--------|----------------|
| 01–07 | `redteam/01-*.sh` … `07-*.sh` | `[RESULT]` in stdout |
| 08 sandwich | `08-mev-sandwich-sim.sh` | `mev-sandwich-result.json` |
| 09 frontrun | `09-mev-frontrun-gas-race.sh` | gas race log |
| 10 JIT | `10-mev-jit-liquidity.sh` | JIT classifier |
| 11 backrun | `11-mev-backrun-arb.sh` | backrun sim |
| 12 fork pipe | `12-fork-offensive-mempool.sh` | `mev-live-pipeline-result.json` |
| 13 sync | `13-battle-offensive-rescue-sync.sh` | bot + mempool coexist |

Runner: `./bin/hexstrike-agent battle -v` → `artifacts/sandbox/battle-report.json`

## Signing bot hunt

| Step | Script | Output |
|------|--------|--------|
| Artifact scan | `agent_signing_bot_hunt.py` | `signing-bot-hunt.json` |
| Jenkins enum | `jenkins-rpc-enum.sh` | `jenkins-rpc-enum.json` |
| Geth RPC enum | `geth-rpc-enum.sh` | `geth-rpc-enum.json` |

## Workflows

| Name | Steps |
|------|-------|
| `field-recon-full` | field recon → hot watch → signing hunt |
| `pentest-chain` | jenkins enum → geth enum → signing hunt |
| `operator-rescue` | puissant dry-run → deploy-mainnet dry-run |

## CI

- **Battle:** `.github/workflows/agent-battle.yml` on push/PR
- **Field recon cron:** `.github/workflows/field-recon-cron.yml` every **30 min** (incremental + parallel)

## ⚡ Fast commands

| Command | What |
|---------|------|
| `bash scripts/run-hexstrike-fast.sh` | Full P1–P7 parallel pipeline |
| `python3 scripts/hexstrike-orchestrator.py run field-recon-parallel` | P1+P2+P3 parallel |
| `python3 scripts/hexstrike-orchestrator.py run pentest-parallel` | P4 async |
| `python3 scripts/hexstrike-orchestrator.py run operator-rescue-parallel` | P5 parallel |
| `python3 scripts/docs/attack_map_diff.py` | Auto-diff attack map vs registry |

## Constraints

- `MEV_SANDBOX_ONLY=1` — no mainnet MEV submit
- `DRY_RUN=true` — operator rescue default
- `SANDBOX_MODE=1` — pentest scripts passive only
- Third-party hot wallets: recon + sim only; `would_submit: false`
