# Lab: подпись + deploy clone + вызов контракта

**Mode: test only** — Anvil/local. Не использовать prod keys hot wallet `0x4943…`.

## Что выучите

1. **EIP-1167 clone** — cheap copy контракта, делегирует в implementation
2. **initialize()** — конструктор на clone (implementation constructor не вызывается повторно)
3. **Подпись** — EIP-191 / EIP-712 off-chain; tx sign для on-chain call
4. **Вызов clone** — `eth_sendRawTransaction` → `clone.withdraw(amount)`

## Быстрый старт (Python, offline)

```bash
pip install eth-account eth-abi
python3 scripts/sandbox/signing-clone-lab.py
```

## Полный цикл (Foundry + Anvil)

```bash
curl -L https://foundry.paradigm.xyz | bash
foundryup

cd scripts/sandbox/contracts
forge build
```

### Terminal 1 — локальная chain

```bash
anvil
# Account #0: 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
# Private key printed in anvil output
```

### Terminal 2 — deploy factory + clone

```bash
cd scripts/sandbox/contracts
export RPC=http://127.0.0.1:8545
export PK=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80

# Deploy factory
FACTORY=$(cast send --private-key $PK --rpc-url $RPC --create $(forge inspect MinimalCloneFactory bytecode) | grep contractAddress | awk '{print $2}')
echo "Factory: $FACTORY"

# Clone for Anvil account #0
CLONE=$(cast call $FACTORY "cloneFor(address)(address)" 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266 --rpc-url $RPC)
echo "Clone: $CLONE"

# Fund clone
cast send $CLONE --value 0.1ether --private-key $PK --rpc-url $RPC

# Call withdraw on CLONE (not implementation!)
cast send $CLONE "withdraw(uint256)" 0.05ether --private-key $PK --rpc-url $RPC
```

## Подпись tx (cast)

```bash
# Dry-run calldata
cast calldata "withdraw(uint256)" 0.05ether

# Sign without broadcast
cast mktx $CLONE "withdraw(uint256)" 0.05ether --private-key $PK --rpc-url $RPC

# Sign + send
cast send $CLONE "withdraw(uint256)" 0.05ether --private-key $PK --rpc-url $RPC
```

## EIP-712 (off-chain auth → on-chain verify)

Pattern used by signature-gated rails (cf. authority impl `0x314C01e7…` on BSC — **audit only on prod**):

```
1. Read domain + types from verified source
2. Owner signs typed struct (amount, to, nonce, deadline)
3. Relayer/contract calls execute(v,r,s, params)
4. Contract: ecrecover == authorizedSigner && nonce++
```

Lab: `signing-clone-lab.py` § EIP-712.

## Clone vs proxy (ваш audit контекст)

| Pattern | Standard | Audit focus |
|---------|----------|-------------|
| EIP-1167 minimal clone | cheap instances | impl bug = all clones affected |
| EIP-1967 transparent proxy | Rhino hub `0xb80a…` | impl upgrade path |
| EIP-7702 delegated EOA | authority `0x730e…` | signature + delegate code |

## Связь с оркестратором

- **test mode:** this lab
- **prod mode:** read-only RPC on live clones/proxies — no sign/broadcast

```bash
python3 scripts/run-orchestrator-phased-tests.py
```

## Ошибки новичков

| Mistake | Fix |
|---------|-----|
| Call `withdraw` on implementation address | Call on **clone** address returned by factory |
| Skip `initialize()` after clone | Clone owner = 0 → withdraw reverts |
| Re-use impl constructor logic | Only `initialize()` on clone |
| Mainnet + leaked test PK | Burn key; use anvil only |
