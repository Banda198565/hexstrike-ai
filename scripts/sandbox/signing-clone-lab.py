#!/usr/bin/env python3
"""Signing + clone contract call lab — TEST KEYS ONLY, local/anvil.

Install: pip install eth-account eth-abi

Full deploy/call path (recommended):
  foundryup && cd scripts/sandbox/contracts
  forge build
  anvil &
  forge script ...  # see signing-clone-lab.md

This script (offline): generate key, sign EIP-712, encode withdraw() calldata.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _require(pkg: str):
    try:
        return __import__(pkg)
    except ImportError:
        print(f"Install: pip install eth-account eth-abi", file=sys.stderr)
        raise SystemExit(1)


def demo_keys():
    Account = _require("eth_account").Account
    acc = Account.create()
    print("=== 1. Test wallet (NEVER use on mainnet with real funds) ===")
    print(f"address:     {acc.address}")
    print(f"private_key: {acc.key.hex()}")
    return acc


def demo_personal_sign(acc):
    from eth_account import Account
    from eth_account.messages import encode_defunct

    print("\n=== 2. personal_sign (EIP-191) ===")
    msg = encode_defunct(text="clone-lab authorize")
    signed = acc.sign_message(msg)
    ok = Account.recover_message(msg, signature=signed.signature) == acc.address
    print(f"signature: {signed.signature.hex()[:66]}…")
    print(f"recover ok: {ok}")


def demo_eip712(acc):
    from eth_account.messages import encode_typed_data

    print("\n=== 3. EIP-712 typed data (pattern for authority rails) ===")
    full_message = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "CloneAction": [
                {"name": "clone", "type": "address"},
                {"name": "amount", "type": "uint256"},
                {"name": "nonce", "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
            ],
        },
        "primaryType": "CloneAction",
        "domain": {
            "name": "CloneVaultLab",
            "version": "1",
            "chainId": 31337,
            "verifyingContract": "0x0000000000000000000000000000000000000001",
        },
        "message": {
            "clone": "0x0000000000000000000000000000000000000002",
            "amount": 10**15,
            "nonce": 0,
            "deadline": 9999999999,
        },
    }
    structured = encode_typed_data(full_message=full_message)
    signed = acc.sign_message(structured)
    print(f"signature: {signed.signature.hex()[:66]}…")
    print("(On-chain: ecrecover(digest, v,r,s) must match authorized signer)")


def demo_calldata():
    eth_abi = _require("eth_abi")
    from eth_utils import keccak, to_checksum_address

    print("\n=== 4. Encode call to clone — withdraw(uint256) ===")
    selector = keccak(text="withdraw(uint256)")[:4]
    amount = 10**15
    calldata = selector + eth_abi.encode(["uint256"], [amount])
    print(f"function:  withdraw(uint256)")
    print(f"selector:  0x{selector.hex()}")
    print(f"calldata:  0x{calldata.hex()}")
    print("\n=== 5. Factory cloneFor(address) ===")
    sel2 = keccak(text="cloneFor(address)")[:4]
    user = to_checksum_address("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266")
    calldata2 = sel2 + eth_abi.encode(["address"], [user])
    print(f"calldata:  0x{calldata2.hex()}")


def demo_eip1167_note():
    print("\n=== 6. EIP-1167 clone (concept) ===")
    impl = "0x1111111111111111111111111111111111111111"
    body = "363d3d373d3d3d363d73" + impl[2:].lower() + "5af43d82803e903d91602a57fd5bf3"
    print(f"impl:     {impl}")
    print(f"bytecode: 0x{body[:40]}… ({len(body)//2} bytes)")
    print("clone DELEGATECALLs to impl — initialize() runs on clone storage, not impl.")


def main() -> int:
    print("Clone + Signing Lab — test mode only\n")
    acc = demo_keys()
    demo_personal_sign(acc)
    demo_eip712(acc)
    demo_calldata()
    demo_eip1167_note()
    print("\nNext: read scripts/sandbox/signing-clone-lab.md for Foundry/anvil flow.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
