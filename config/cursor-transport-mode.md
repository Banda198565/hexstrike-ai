# Cursor transport-only setup

How to **minimize Cursor autonomy** so R1 remains the brain and Cursor is dumb transport.

Repo enforces behavior via `.cursor/rules/transport-only.mdc` (always on). UI settings below reduce platform auto-actions.

---

## 1. Cursor IDE — mode and auto-apply

| Setting | Value | Why |
|---------|-------|-----|
| Chat mode | **Ask** (not Agent / Auto / Plan) | Model answers; does not auto-edit or run commands |
| Auto Apply | **Off** | No silent patch application |

### Project settings (committed)

File: `.cursor/settings.json`

```json
{
  "cursor.agent.autoApply": false,
  "cursor.chat.autoApply": false,
  "hexstrike.transportOnly": true
}
```

### User settings (local, optional)

`~/.cursor/settings.json` — same keys if you want global transport-only.

> Cursor UI labels change between versions. If a key is ignored, set **Ask mode** and **Auto Apply off** manually in Settings → Cursor → Agent / Chat.

---

## 2. Cloud Agent runs (`cursor.com/agents/bc-…`)

Cloud Agents default to Agent mode with git push. For transport-only:

- Start runs with prompt: *"Transport-only. Analysis and R1 plan only. No file edits or shell unless I say implement."*
- Or use **Ask**-style session in IDE instead of Cloud Agent for planning
- Disable background agents for this repo if not needed (Settings → Agents)

Cloud Agent URL is **not** source of truth — repo rules in `.cursor/rules/` are.

---

## 3. MCP allowlist

Only connect servers from `.cursor/mcp.json`. Primary boundary:

| Server | Role |
|--------|------|
| **gated-orchestrator** | Read-only RPC + controlled FS |
| solidity-audit | Static analysis |
| foundry | Sandbox PoC only |
| chainstack / faro-fino | Optional; read-only context |

No MCP tool may call `eth_sendTransaction`. Report writes only via `fs_create_report_file`.

---

## 4. R1 invocation

```bash
python3 hexstrike_orchestrator.py reasoning plan config/reasoning-protocol.example.json
```

Cursor reads `cursor_handoff` from plan JSON — executes listed MCP steps only when user says **execute step N** or **implement plan**.

---

## 5. Escape hatch (when you want Cursor to act)

Say explicitly:

- `implement …` — allow file edits for stated scope
- `run tests` — allow shell for tests
- `commit and push` — allow git
- `execute R1 step 2` — allow named MCP tool only

Without these verbs → analysis and plans only.

---

## 6. Verify

```bash
python3 scripts/run-orchestrator-phased-tests.py   # phase 4 checks transport-only rule
python3 scripts/test_gated_mcp_runner.py
```

Ask Cursor: *"Update Bank.sol"* without saying implement → must refuse with transport-only message.
