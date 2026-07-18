# Cursor transport-only setup

How to **minimize Cursor autonomy** so R1 remains the brain and Cursor is dumb transport.

Repo enforces behavior via:

| Layer | File | Enforces |
|-------|------|----------|
| **Permissions (hard)** | `.cursor/cli.json` | `Shell(*)` denied — agent cannot run terminal |
| **IDE auto-run** | `.cursor/permissions.json` | `terminalAllowlist: []` |
| **Behavior (soft)** | `.cursor/rules/transport-only.mdc` | No auto-init shell/MCP without explicit verb |

> Rules describe policy; **`permissions` in `cli.json` enforce it**. Deny wins over allow.

---

## 0. Shell hard block (cli.json) — primary enforcement

Project file: **`.cursor/cli.json`** (committed)

```json
"permissions": {
  "allow": [ /* no Shell(...) entries */ ],
  "deny": [ "Shell(*)" ]
}
```

- No `Shell(...)` in `allow` → agent cannot execute or auto-run commands
- `deny: Shell(*)` → blanket block even if global config allows something
- MCP + Read/Write report paths remain in `allow` for audit transport

Global template: `config/cursor-cli-config.example.json` → copy to `~/.cursor/cli-config.json`

**Engineering mode** (user said `implement` / `run tests`): merge from `config/cursor-cli.engineering.example.json` into `.cursor/cli.json` temporarily — adds `Shell(python3)`, `Shell(git)`, etc., still denies `Shell(rm)`.

Validate commands before allowlist merge:

```bash
python3 scripts/cursor-shell-guard.py "python3 scripts/run-orchestrator-phased-tests.py"
python3 scripts/cursor-shell-guard.py "ls && rm -rf /"   # exit 1
```

Patterns: `config/cursor-shell-patterns.json` · Behavior rule: `.cursor/rules/shell-policy.mdc`

Docs: [Cursor CLI Permissions](https://cursor.com/docs/cli/reference/permissions)

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

**Full guide:** `config/cursor-cloud-agent-transport.md`

Cloud Agent читает `.cursor/` **из ветки run**, не из URL карточки.

| Check | Action |
|-------|--------|
| Branch has configs? | `python3 scripts/verify-transport-config.py` |
| R1 run on old branch? | Merge PR #71 → `master` or cherry-pick to `cursor/cloud-r1-reasoning-agent-7b69` |
| Shell still runs? | Cloud VM may use platform Shell — **rules** + prompt; `cli.json` = CLI enforcement |

Start prompt:

```
Transport-only. R1 = planner. No edits/shell/git unless I say implement.
Follow transport-only.mdc + shell-policy.mdc. Use gated-orchestrator MCP.
```

Cloud Agent URL is **not** source of truth — repo `.cursor/` on **checked-out branch** is.

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
python3 scripts/verify-transport-config.py          # branch has all transport files?
python3 scripts/run-orchestrator-phased-tests.py   # phase 4 checks transport-only rule
python3 scripts/test_gated_mcp_runner.py
```

Ask Cursor: *"Update Bank.sol"* without saying implement → must refuse with transport-only message.
