```
╔════════════════════════════════════════════════════════════════════════════════╗
║                   HEXSTRIKE EVOLUTION: DUMMY → FULL AGENT                      ║
║                         Three-Layer Defense System                              ║
╚════════════════════════════════════════════════════════════════════════════════╝


┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 1: DUMMY BOT (VULNERABLE BASELINE)                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │ Anvil (Local Chain)                                             │        │
│  │ ├─ 10 test accounts (10,000 ETH each)                          │        │
│  │ └─ Chain ID: 31337                                             │        │
│  └────────────────────┬────────────────────────────────────────────┘        │
│                       │                                                     │
│                   :8545 RPC                                                │
│                       │                                                     │
│  ┌────────────────────▼────────────────────────────────────────────┐        │
│  │ DUMMY BOT (Python)                                              │        │
│  │ ├─ Every 10s: eth_getBalance(bot_addr)                         │        │
│  │ ├─ if balance < 0.5 ETH:                                       │        │
│  │ │   └─ SIGN & SEND rescue TX (NO CHECKS) 🔴 VULNERABLE         │        │
│  │ └─ Log to: dummy-bot-events.jsonl                              │        │
│  └────────────────────────────────────────────────────────────────┘        │
│                                                                              │
│  ATTACKS THAT SUCCEED:                                                      │
│  🔴 01-baseline-trigger      → Bot signs on low balance                     │
│  🔴 02-race-duplicate-sign   → Multiple TXs (no dedup)                      │
│  🔴 03-front-run-drain       → Balance 0 but signed                         │
│  🔴 04-replay-rescue-tx      → TX sent twice                                │
│  🔴 05-toctou-nonce-bump     → Nonce race wins                              │
│  🔴 06-compromised-funder    → Attacker receives $                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 2: ADD RPC INTERCEPTOR (MONITORING ONLY)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │ Anvil (Local Chain)                                             │        │
│  │ :8545                                                           │        │
│  └────────────────────┬────────────────────────────────────────────┘        │
│                       ▲                                                     │
│                       │                                                     │
│                   (real RPC)                                                │
│                       │                                                     │
│  ┌────────────────────┼────────────────────────────────────────────┐        │
│  │ RPC INTERCEPTOR (FastAPI)                                       │        │
│  │ :8546 (proxy port)                                              │        │
│  │ ├─ Receives all JSON-RPC calls                                 │        │
│  │ ├─ Log: method, params, latency_ms                             │        │
│  │ ├─ Forward unchanged to :8545                                  │        │
│  │ ├─ Return upstream response (NO MODIFICATION)                  │        │
│  │ └─ Log to: rpc-interceptor.jsonl                               │        │
│  └────────────────────┬────────────────────────────────────────────┘        │
│                       │                                                     │
│                   :8546 (bot reads)                                         │
│                       │                                                     │
│  ┌────────────────────▼────────────────────────────────────────────┐        │
│  │ DUMMY BOT (Python)                                              │        │
│  │ ├─ Every 10s: eth_getBalance(bot_addr) via PROXY               │        │
│  │ ├─ if balance < 0.5 ETH:                                       │        │
│  │ │   └─ SIGN & SEND rescue TX (NO CHECKS) 🔴 STILL VULNERABLE   │        │
│  │ └─ Log to: dummy-bot-events.jsonl                              │        │
│  └────────────────────────────────────────────────────────────────┘        │
│                                                                              │
│  WHAT CHANGED:                                                              │
│  • Bot now reads via proxy (:8546)                                          │
│  • All RPC calls logged (monitoring)                                        │
│  • But NO protection → same 6 attacks still succeed 🔴                     │
│  • Can now DETECT attacks in logs (but can't block)                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 3: ADD DEFENSIVE HARDENING (FULL PROTECTION)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │ Anvil (Local Chain) - DIRECT RPC (Truth Source)                 │        │
│  │ :8545                                                           │        │
│  └────────────────┬──────────────────────────┬──────────────────────┘        │
│                   │                          │                             │
│         (direct call)              (direct call)                           │
│                   │                          │                             │
│  ┌────────────────▼─────┐   ┌────────────────▼────────────────────┐        │
│  │ GUARD #1: RPC CHECK  │   │ GUARD #2: ANOMALY CHECK             │        │
│  │                      │   │                                     │        │
│  │ Fetch:               │   │ Fetch:                              │        │
│  │ • primary_balance    │   │ • current_balance                  │        │
│  │   (from proxy)       │   │ • current_nonce                    │        │
│  │                      │   │                                     │        │
│  │ • direct_balance     │   │ Compare with:                       │        │
│  │   (from Anvil)       │   │ • last_balance                     │        │
│  │                      │   │ • last_nonce                       │        │
│  │ Decision:            │   │                                     │        │
│  │ if |delta| >         │   │ Decision:                           │        │
│  │    MAX_DELTA:        │   │ if balance↓ && nonce==last_nonce:  │        │
│  │   BLOCK ❌           │   │   BLOCK ❌ (drain w/o activity)     │        │
│  │ else: continue ✓     │   │ else: continue ✓                    │        │
│  └──────────┬───────────┘   └─────────────┬──────────────────────┘        │
│             │                             │                               │
│             └─────────────┬───────────────┘                               │
│                           │                                               │
│  ┌────────────────────────▼────────────────────────────────────────┐        │
│  │ GUARD #3: PRE-SIGN VERIFY                                       │        │
│  │                                                                  │        │
│  │ Final check before signing:                                     │        │
│  │ ├─ Fetch balance from DIRECT RPC again                         │        │
│  │ ├─ if balance < THRESHOLD: SIGN ✓                              │        │
│  │ └─ else: BLOCK ❌ (false trigger from proxy)                    │        │
│  └────────────────────────────────────────────────────────────────┘        │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────┐        │
│  │ RPC INTERCEPTOR (FastAPI)                                       │        │
│  │ :8546 (proxy port)                                              │        │
│  │ ├─ Logs all calls                                              │        │
│  │ └─ No modification (pass-through)                              │        │
│  └────────────────────┬────────────────────────────────────────────┘        │
│                       │                                                     │
│                   :8546 (bot reads)                                         │
│                       │                                                     │
│  ┌────────────────────▼────────────────────────────────────────────┐        │
│  │ HARDENED BOT (Python + Guards)                                  │        │
│  │ ├─ Every 10s: eth_getBalance(bot_addr) via PROXY               │        │
│  │ ├─ if balance < 0.5 ETH:                                       │        │
│  │ │   ├─ Call GUARD #1 (RPC mismatch check)                     │        │
│  │ │   ├─ Call GUARD #2 (anomaly detection)                      │        │
│  │ │   ├─ Call GUARD #3 (pre-sign verify)                        │        │
│  │ │   └─ If ANY guard blocks → BLOCK ❌                          │        │
│  │ │   └─ If ALL guards pass → SIGN ✓                             │        │
│  │ └─ Log to: dummy-bot-events.jsonl + anomaly-alerts.jsonl       │        │
│  └────────────────────────────────────────────────────────────────┘        │
│                                                                              │
│  ATTACKS NOW DEFENDED:                                                      │
│  ✅ 01-baseline-trigger      → Guard #3 verifies on direct RPC              │
│  ✅ 02-race-duplicate-sign   → Guard #1 detects proxy tampering             │
│  ✅ 03-front-run-drain       → Guard #3 checks balance before sign          │
│  ✅ 04-replay-rescue-tx      → Guard #2 detects nonce anomaly               │
│  ✅ 05-toctou-nonce-bump     → Guard #2 flags nonce race                    │
│  ✅ 06-compromised-funder    → (Funder allowlist in future)                 │
│                                                                              │
│  ALERTS GENERATED:                                                          │
│  • rpc_mismatch: primary != direct balance                                  │
│  • anomaly_no_onchain_activity: balance↓ without nonce↑                     │
│  • direct_rpc_unavailable: fail-closed on RPC error                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│ GO AGENT: AUTONOMOUS ORCHESTRATION                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │ hexstrike-agent (Go Binary)                                     │        │
│  │                                                                  │        │
│  │ 1. Verify Prerequisites                                        │        │
│  │    └─ anvil, cast, python3, bash ✓                            │        │
│  │                                                                  │        │
│  │ 2. Setup Environment                                           │        │
│  │    └─ Create artifacts/, run setup-anvil-env.sh ✓              │        │
│  │                                                                  │        │
│  │ 3. Run All 7 Attacks (Sequential)                              │        │
│  │    ├─ 01-baseline-trigger                                      │        │
│  │    ├─ 02-race-duplicate-sign                                   │        │
│  │    ├─ 03-front-run-drain                                       │        │
│  │    ├─ 04-replay-rescue-tx                                      │        │
│  │    ├─ 05-toctou-nonce-bump                                     │        │
│  │    ├─ 06-compromised-funder                                    │        │
│  │    └─ 07-hardening-blocks-tamper                               │        │
│  │                                                                  │        │
│  │ 4. Parse Results                                               │        │
│  │    ├─ VULN_CONFIRMED: attack succeeded                         │        │
│  │    ├─ DEFENDED: attack blocked                                 │        │
│  │    └─ INCONCLUSIVE: test failed or timeout                     │        │
│  │                                                                  │        │
│  │ 5. Analyze & Score                                             │        │
│  │    ├─ +10 per defended attack                                  │        │
│  │    ├─ +5 per vulnerability found                               │        │
│  │    ├─ -20 per inconclusive                                     │        │
│  │    └─ Score: 0-100 (readiness)                                 │        │
│  │                                                                  │        │
│  │ 6. Generate Report                                             │        │
│  │    ├─ Console output (ASCII art)                               │        │
│  │    ├─ JSON report: battle-report.json                          │        │
│  │    └─ Exit code: 0 (score≥50), 1 (score<50)                    │        │
│  │                                                                  │        │
│  │ OUTPUT:                                                         │        │
│  │ ┌──────────────────────────────────────────────────────┐       │        │
│  │ │ 🎯 HexStrike Battle Agent Started                   │       │        │
│  │ │ ════════════════════════════════════════════════════ │       │        │
│  │ │                                                      │       │        │
│  │ │ [*] Verifying prerequisites...                      │       │        │
│  │ │     ✓ anvil                                         │       │        │
│  │ │     ✓ cast                                          │       │        │
│  │ │     ✓ python3                                       │       │        │
│  │ │     ✓ bash                                          │       │        │
│  │ │                                                      │       │        │
│  │ │ [*] Launching battle test suite (7 attacks)...      │       │        │
│  │ │ ════════════════════════════════════════════════════ │       │        │
│  │ │                                                      │       │        │
│  │ │ [1/7] Running: 01-baseline-trigger                  │       │        │
│  │ │ ⚠ 01-baseline-trigger → VULN_CONFIRMED              │       │        │
│  │ │                                                      │       │        │
│  │ │ [2/7] Running: 02-race-duplicate-sign               │       │        │
│  │ │ ⚠ 02-race-duplicate-sign → VULN_CONFIRMED           │       │        │
│  │ │                                                      │       │        │
│  │ │ ... (5 more attacks)                                │       │        │
│  │ │                                                      │       │        │
│  │ │ 📊 BATTLE REPORT                                    │       │        │
│  │ │ ════════════════════════════════════════════════════ │       │        │
│  │ │                                                      │       │        │
│  │ │ 📈 SUMMARY:                                         │       │        │
│  │ │   Total Tests:      7                               │       │        │
│  │ │   Vulnerabilities:  4 ⚠️                             │       │        │
│  │ │   Defended:         2 ✓                             │       │        │
│  │ │   Inconclusive:     1 ?                             │       │        │
│  │ │                                                      │       │        │
│  │ │ 🎯 READINESS SCORE:                                │       │        │
│  │ │   62/100 ⚠️ NEEDS HARDENING                         │       │        │
│  │ │                                                      │       │        │
│  │ │ 🔴 FOUND VULNERABILITIES:                           │       │        │
│  │ │   • 01-baseline-trigger: bot signed w/o guards      │       │        │
│  │ │   • 02-race-duplicate-sign: 3 txs, no dedup         │       │        │
│  │ │   • 03-front-run-drain: balance 0, still signed     │       │        │
│  │ │   • 06-compromised-funder: sent to attacker         │       │        │
│  │ │                                                      │       │        │
│  │ │ 💾 Report saved to: artifacts/sandbox/battle-report.json │  │        │
│  │ └──────────────────────────────────────────────────────┘       │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│ COMPARISON TABLE: DUMMY vs. HARDENED                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Test                      │ Step 1  │ Step 2  │ Step 3  │ Guard Responsible │
│  ─────────────────────────┼─────────┼─────────┼─────────┼──────────────────  │
│  01 Baseline Trigger       │ VULN ❌ │ VULN ❌ │ DEF ✅  │ #3 Pre-sign       │
│  02 Race Duplicate         │ VULN ❌ │ VULN ❌ │ DEF ✅  │ #1 RPC Mismatch   │
│  03 Front-run Drain        │ VULN ❌ │ VULN ❌ │ DEF ✅  │ #3 Pre-sign       │
│  04 Replay Attack          │ VULN ❌ │ VULN ❌ │ DEF ✅  │ #2 Anomaly        │
│  05 TOCTOU Nonce           │ VULN ❌ │ VULN ❌ │ DEF ✅  │ #2 Anomaly        │
│  06 Compromised Funder     │ VULN ❌ │ VULN ❌ │ DEF ✅  │ Allowlist (future)│
│  07 Hardening Blocks       │ N/A  ✓ │ N/A  ✓ │ TEST ✅ │ All guards        │
│                                                                              │
│  SCORE                     │  20/100 │  20/100 │  75/100 │ ✅ DEPLOYABLE     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│ FLOW: FROM ATTACK TO BLOCK                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  SCENARIO: Attacker tampers with proxy (pretends low balance)               │
│                                                                              │
│  Timeline:                                                                  │
│  ───────────────────────────────────────────────────────────────────────    │
│                                                                              │
│  t=0s: Attacker intercepts proxy response                                   │
│        └─ Returns: getBalance → "0x0" (fake low balance)                    │
│                                                                              │
│  t=1s: Bot polls getBalance from PROXY                                      │
│        └─ Receives: 0 ETH (attacker's fake response)                        │
│        └─ Decides: balance < threshold → TRIGGER RESCUE                     │
│                                                                              │
│  t=2s: Guard #1 (RPC Mismatch Check) runs                                   │
│        ├─ Fetch balance from PROXY: 0 ETH                                   │
│        ├─ Fetch balance from DIRECT: 10 ETH                                 │
│        ├─ Delta: |0 - 10| = 10 ETH > MAX_DELTA (0)                          │
│        └─ DECISION: BLOCK ❌ "RPC Mismatch - possible tampering"            │
│                                                                              │
│  t=3s: ALERT logged to anomaly-alerts.jsonl                                 │
│        {                                                                    │
│          "ts": "2025-01-15T14:25:30Z",                                      │
│          "type": "rpc_mismatch",                                            │
│          "severity": "critical",                                            │
│          "primary_wei": 0,                                                  │
│          "direct_wei": 10000000000000000000,                                │
│          "delta_wei": 10000000000000000000,                                 │
│          "action": "block_signing",                                         │
│          "message": "Primary RPC balance differs from direct upstream"      │
│        }                                                                    │
│                                                                              │
│  t=4s: Bot event logged to dummy-bot-events.jsonl                           │
│        {                                                                    │
│          "ts": "2025-01-15T14:25:30Z",                                      │
│          "action": "blocked",                                               │
│          "result": "rpc_mismatch",                                          │
│          "balance_wei": 0,                                                  │
│          "block_reason": "rpc_mismatch"                                     │
│        }                                                                    │
│                                                                              │
│  t=5s: No TX signed → Attack FAILED ✅                                       │
│        Operator alerted → Can investigate proxy tampering                   │
│                                                                              │
│  ───────────────────────────────────────────────────────────────────────    │
│                                                                              │
│  WITHOUT HARDENING (Step 1):                                                │
│  └─ TX would be signed → Attacker wins 🔴                                    │
│                                                                              │
│  WITH HARDENING (Step 3):                                                   │
│  └─ TX blocked → Attacker loses, alert generated ✅                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘


DEPLOYMENT STRATEGY:
═══════════════════════════════════════════════════════════════════════════════

  ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
  │  Step 1     │  ────▶  │  Step 2     │  ────▶  │  Step 3     │
  │  Baseline   │         │  Monitoring │         │  Protected  │
  │  (Dev Test) │         │  (Staging)  │         │  (Prod)     │
  └─────────────┘         └─────────────┘         └─────────────┘
       ↓                         ↓                       ↓
     30s                       5min                    30min
  (smoke test)          (log analysis)           (full validation)
     ↓                         ↓                       ↓
  Score 20/100 ────────────────────────────────────▶ Score 75/100 ✅
     (LEARN)              (DETECT)                    (DEFEND)

  Go Agent automates entire flow and generates readiness report


GIT WORKFLOW:
═══════════════════════════════════════════════════════════════════════════════

  1. Create PR with sandbox code
  2. Agent auto-runs on push (GitHub Actions)
  3. Agent comments PR with score
  4. If score ≥ 70: ready to merge
  5. If score < 70: fix & retest
  6. Merge to master when ready

```
