# Tool spec: `rpc_contract_audit`

## MCP config (Cursor `mcp.json`)

```json
{
  "mcpServers": {
    "hexstrike-web3-rpc": {
      "command": "python3",
      "args": ["scripts/web3_rpc_mcp_server.py"],
      "env": {
        "WEB3_RPC_URL": "https://mainnet.infura.io/v3",
        "WEB3_RPC_KEY": "your-personal-rpc-key-here"
      }
    }
  }
}
```

## MCP tool definition

```json
{
  "name": "rpc_contract_audit",
  "description": "Read-only contract audit by on-chain address using server-side RPC credentials.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "address": { "type": "string", "pattern": "^0x[0-9a-fA-F]{40}$" },
      "chain": { "type": "string", "default": "mainnet" }
    },
    "required": ["address"]
  }
}
```

## Agent prompt snippet

> Never ask the user for RPC keys. Call `detect_rpc_config` first. For unknown deployed contracts use `rpc_contract_audit`; if `is_proxy`, repeat on `implementation_address`. Pair with Solidity Audit MCP when verified source exists.
