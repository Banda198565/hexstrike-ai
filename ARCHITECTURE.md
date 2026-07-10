# HexStrike Architecture Manifest

CLI-oriented orchestrator for defensive security, on-chain forensics, and gated execution.

## 1. Core Engine

| Component | Path | Role |
|-----------|------|------|
| **Orchestrator** | `hexstrike_orchestrator.py`, `src/hexstrike_orchestrator.py` | Main CLI dispatcher — lifecycle, health, agent routing |
| **AgentManager** | `src/hexstrike/agent_manager.py` | Binds instruction protocols + MCP tools to modules |
| **ContextBus** | `src/hexstrike/bus/context_bus.py` | Pub/sub event bus between agents |
| **mcp_execution_gate** | `src/hexstrike/mcp/execution_gate.py` | Human-in-the-loop gate — blocks broadcast until `pending_action.json` approved |

## 2. Capability Modules (Skills / Agents)

| ID | Path | Task |
|----|------|------|
| `core.monitor` | `src/hexstrike/core/monitor/` | Mempool monitoring, live alerts |
| `core.forensics` | `src/hexstrike/core/forensics/` | On-chain analysis, CEX clustering, asset tracing |
| `skill.recon_osint` | `src/hexstrike/skills/recon_osint.py` | Infrastructure OSINT, port/CVE surface |
| `skill.timing_analysis` | `src/hexstrike/skills/timing_analysis.py` | RPC latency, gas-fee positioning |
| `core.execution` | `src/hexstrike/core/execution/` | TX formation/broadcast (gated only) |
| `core.stealth` | `src/hexstrike/core/stealth/` | Traffic masking, proxy, UA rotation |

Instructions: `src/hexstrike/instructions/*.md`

## 3. MCP Interfaces

| MCP | Path | Role |
|-----|------|------|
| `mcp_execution_gate` | `src/hexstrike/mcp/execution_gate.py` | Operator approval queue |
| `mcp_shodan` | `src/hexstrike/mcp/shodan.py` | Shodan OSINT (`SHODAN_API_KEY`) |
| `mcp_blockscout_api` | `src/hexstrike/mcp/blockscout_api.py` | Multichain explorer depth-3 trace |
| `mcp_geth_p2p` | `src/hexstrike/mcp/geth_p2p.py` | devp2p TCP probe, discv4 ping |
| `mcp_storage_gate` | `src/hexstrike/mcp/storage_gate.py` | Gated access to config/credentials |
| `mcp_rpc_gateway` | `src/hexstrike/mcp/rpc_gateway.py` | Unified RPC node manager |
| `mcp_rag_memory` | `src/hexstrike/mcp/rag_memory.py` | LanceDB forensic memory |

## 4. Infrastructure & Data

```
~/hexstrike-ai/
├── artifacts/              # JSON reports, logs, dumps
│   └── pending_action.json # Operator approval queue (broadcast)
├── config/
│   └── rpc_config.json     # Primary/fallback RPC endpoints
├── project_manifest.json   # Machine-readable component registry
└── ARCHITECTURE.md         # This file
```

## 5. Quick Start

```bash
# Component status
python3 hexstrike_orchestrator.py status

# Health + manifest update
python3 hexstrike_orchestrator.py health

# Bound agents
python3 hexstrike_orchestrator.py agents
```

## 6. Security Policy

- **Read-only first** — recon, forensics, OSINT
- **No auto-broadcast** — all writes via `mcp_execution_gate`
- **Sensitive files** — `mcp_storage_gate` queues writes to `config.xml`, `credentials.xml`, vault
- **Operator approval** — edit `artifacts/pending_action.json` → `"status": "approved"`

## 7. External MCP (Cursor IDE)

Template: `hexstrike-ai-mcp.json` → copy to `~/.cursor/mcp.json` with real paths.

```bash
python3 hexstrike_server.py          # Legacy API :8888
python3 hexstrike_mcp.py --server http://127.0.0.1:8888
```
