# Tool spec: `parse_contract`

## MCP tool definition

```json
{
  "name": "parse_contract",
  "description": "Normalize Solidity input and return structured contract metadata for audit planning.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "source_or_path": {
        "type": "string",
        "description": "Solidity source code OR relative repo path to .sol file / directory"
      },
      "source_is_code": {
        "type": "boolean",
        "default": false,
        "description": "Set true when source_or_path is inline Solidity"
      }
    },
    "required": ["source_or_path"]
  }
}
```

## FastAPI endpoint (orchestrator bridge)

```python
@router.post("/audit/parse-contract", response_model=ParseContractResponse)
async def parse_contract(body: ParseContractRequest) -> ParseContractResponse:
    return solidity_audit_runner.parse_contract(
        body.source_or_path,
        source_is_code=body.source_is_code,
    )
```

## Response shape

```json
{
  "success": true,
  "compiler_version": "^0.8.20",
  "solidity_version_pragmas": ["^0.8.20"],
  "detected_framework": "foundry",
  "contracts": [
    {
      "name": "Vault",
      "inheritance": ["Ownable", "ReentrancyGuard"],
      "modifiers": ["onlyOwner"],
      "events": ["Deposited"],
      "public_functions": ["deposit"],
      "external_functions": ["withdraw"]
    }
  ]
}
```

## Agent prompt snippet

> Always call `parse_contract` first. Use `detected_framework` to choose compile path (`compile_and_abi` for Foundry). Map `external_functions` to attack surface before running Slither.
