"""Read-only EVM JSON-RPC helpers for HexStrike MCP layer."""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

DEFAULT_RPC = os.environ.get("EVM_RPC_URL", "http://51.222.42.220:8545")
DEFAULT_CHAIN_ID = int(os.environ.get("EVM_CHAIN_ID", "56"))
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
OFFICIAL_USDT_BSC = "0x55d398326f99059fF775485246999027B3197955"
WBNB_BSC = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
PANCAKE_FACTORY_V2 = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"

CEX_LABELS = {
    "0x8894e0a0c962cb723c1976a4421c95949be2d4e3": "Binance Hot Wallet 6",
    "0x28c6c06298d81db4d864dfa4d9be2409a7ea8e5": "Binance Hot Wallet 14",
    "0x21a31ee1afc51d94c2e590aa8462985235223dd": "Binance Hot Wallet 15",
    "0x161ba15a5f335c9f06bb5bbb0a9ce14076fbb645": "Binance Hot Wallet 11",
    "0xf977814e90da44bfa03b6295a0616a897441acec": "Binance Hot Wallet 8",
}


class EvmClient:
    def __init__(self, rpc_url: str | None = None):
        self.rpc_url = (rpc_url or DEFAULT_RPC).rstrip("/")

    def rpc(self, method: str, params: list[Any]) -> Any:
        body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
        req = urllib.request.Request(self.rpc_url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            out = json.load(resp)
        if "error" in out:
            raise RuntimeError(out["error"])
        return out["result"]

    @staticmethod
    def pad_addr(addr: str) -> str:
        return addr.lower().replace("0x", "").zfill(64)

    @staticmethod
    def decode_addr(topic: str) -> str:
        return "0x" + topic[-40:]

    def eth_call(self, to: str, data: str) -> str:
        return self.rpc("eth_call", [{"to": to, "data": data}, "latest"])

    def latest_block(self) -> int:
        return int(self.rpc("eth_blockNumber", []), 16)

    def get_code(self, address: str) -> str:
        return self.rpc("eth_getCode", [address, "latest"])

    def balance_of(self, token: str, holder: str, decimals: int = 18) -> float:
        data = "0x70a08231" + self.pad_addr(holder)
        raw = int(self.eth_call(token, data), 16)
        return raw / (10**decimals)

    def token_meta(self, token: str) -> dict[str, Any]:
        def _str(sel: str) -> str | None:
            raw = self.eth_call(token, sel)
            if not raw or raw == "0x":
                return None
            b = bytes.fromhex(raw[2:])
            if len(b) < 64:
                return b.decode("utf-8", errors="ignore").strip("\x00")
            ln = int.from_bytes(b[32:64], "big")
            return b[64 : 64 + ln].decode("utf-8", errors="ignore")

        dec = int(self.eth_call(token, "0x313ce567"), 16)
        return {
            "address": token,
            "name": _str("0x06fdde03"),
            "symbol": _str("0x95d89b41"),
            "decimals": dec,
        }

    def get_token_transfers(
        self,
        token: str,
        address: str,
        direction: str = "both",
        blocks: int = 10000,
        min_amount: float = 0,
    ) -> dict[str, Any]:
        latest = self.latest_block()
        from_b = max(0, latest - blocks)
        topic = self.pad_addr(address)
        addr_topic = "0x" + topic
        rows: list[dict[str, Any]] = []

        def _scan(topics: list[Any], dir_label: str):
            chunk = 5000
            for start in range(from_b, latest + 1, chunk):
                end = min(start + chunk - 1, latest)
                logs = self.rpc(
                    "eth_getLogs",
                    [{"fromBlock": hex(start), "toBlock": hex(end), "address": token, "topics": topics}],
                )
                for lg in logs:
                    val = int(lg["data"], 16) / 1e18
                    if val < min_amount:
                        continue
                    rows.append(
                        {
                            "direction": dir_label,
                            "from": self.decode_addr(lg["topics"][1]),
                            "to": self.decode_addr(lg["topics"][2]),
                            "amount": round(val, 6),
                            "tx": lg["transactionHash"],
                            "block": int(lg["blockNumber"], 16),
                        }
                    )

        if direction in ("out", "both"):
            _scan([TRANSFER_TOPIC, addr_topic, None], "out")
        if direction in ("in", "both"):
            _scan([TRANSFER_TOPIC, None, addr_topic], "in")

        return {
            "rpc": self.rpc_url,
            "token": token,
            "address": address,
            "block_range": [from_b, latest],
            "count": len(rows),
            "transfers": rows[:500],
        }

    def pancake_pair(self, token_a: str, token_b: str) -> str | None:
        data = "0xe6a43905" + self.pad_addr(token_a) + self.pad_addr(token_b)
        raw = self.eth_call(PANCAKE_FACTORY_V2, data)
        if not raw or int(raw, 16) == 0:
            return None
        return "0x" + raw[-40:]

    def pair_reserves(self, pair: str) -> tuple[float, float]:
        # getReserves() -> reserve0, reserve1, blockTimestampLast
        raw = self.eth_call(pair, "0x0902f1ac")
        b = bytes.fromhex(raw[2:])
        r0 = int.from_bytes(b[0:32], "big") / 1e18
        r1 = int.from_bytes(b[32:64], "big") / 1e18
        return r0, r1

    def label(self, address: str) -> str | None:
        return CEX_LABELS.get(address.lower())
