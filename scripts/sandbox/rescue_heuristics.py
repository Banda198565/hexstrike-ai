#!/usr/bin/env python3
"""Rescue heuristics — fast gas bump, calldata dedup, resign turbo."""
from __future__ import annotations

import hashlib
import os
import time
from typing import Any


def calldata_hash(data: str | bytes | None) -> str:
    if not data:
        return ""
    raw = data.encode() if isinstance(data, str) else data
    if raw.startswith(b"0x"):
        raw = bytes.fromhex(raw[2:].decode() if isinstance(raw[0], int) else raw[2:])
    return hashlib.sha256(raw).hexdigest()[:16]


class TxDedupUltra:
    """Dedup by calldata hash — not string compare."""

    def __init__(self, max_entries: int = 256):
        self._seen: dict[str, float] = {}
        self._max = max_entries

    def is_duplicate(self, *, to: str, value: int, data: str = "0x") -> bool:
        key = f"{to.lower()}:{value}:{calldata_hash(data)}"
        now = time.monotonic()
        if key in self._seen:
            return True
        self._seen[key] = now
        if len(self._seen) > self._max:
            oldest = sorted(self._seen.items(), key=lambda x: x[1])[: len(self._seen) // 4]
            for k, _ in oldest:
                self._seen.pop(k, None)
        return False


class FastGasBump:
    """Aggressive gas bump when pending > threshold seconds."""

    def __init__(self, pending_sec: float = 12.0, bump_pct: int = 25):
        self.pending_sec = float(os.environ.get("FAST_GAS_PENDING_SEC", pending_sec))
        self.bump_pct = int(os.environ.get("FAST_GAS_BUMP_PCT", bump_pct))
        self._submitted_at: dict[str, float] = {}

    def track_submit(self, tx_hash: str) -> None:
        self._submitted_at[tx_hash.lower()] = time.monotonic()

    def should_bump(self, tx_hash: str) -> tuple[bool, int]:
        ts = self._submitted_at.get(tx_hash.lower())
        if ts is None:
            return False, 0
        elapsed = time.monotonic() - ts
        if elapsed >= self.pending_sec:
            return True, self.bump_pct
        return False, 0

    def bumped_fees(self, base_fee: int, priority: int, bump_pct: int) -> tuple[int, int]:
        mult = 100 + bump_pct
        return base_fee * mult // 100, priority * mult // 100


class ResignTurbo:
    """Instant resign on nonce race — prefetch nonce, bump on mismatch."""

    def __init__(self):
        self._last_nonce: int | None = None
        self._last_prefetch: float = 0.0
        self.ttl = float(os.environ.get("NONCE_PREFETCH_TTL_SEC", "3"))

    def prefetch_nonce(self, fetch_fn) -> int:
        now = time.monotonic()
        if self._last_nonce is not None and now - self._last_prefetch < self.ttl:
            return self._last_nonce
        self._last_nonce = int(fetch_fn())
        self._last_prefetch = now
        return self._last_nonce

    def needs_resign(self, current_nonce: int) -> bool:
        return self._last_nonce is not None and current_nonce != self._last_nonce

    def resign_nonce(self, fetch_fn) -> int:
        self._last_nonce = int(fetch_fn())
        self._last_prefetch = time.monotonic()
        return self._last_nonce


# Module-level singletons for dummy_bot
DEDUP = TxDedupUltra()
GAS_BUMP = FastGasBump()
RESIGN = ResignTurbo()


def apply_rescue_heuristics(
    *,
    to: str,
    value: int,
    data: str = "0x",
    tx_hash: str | None = None,
    base_fee: int = 0,
    priority: int = 0,
) -> dict[str, Any]:
    """Return heuristic decisions for rescue signing path."""
    dup = DEDUP.is_duplicate(to=to, value=value, data=data)
    bump = False
    bump_pct = 0
    if tx_hash:
        bump, bump_pct = GAS_BUMP.should_bump(tx_hash)
    max_fee, max_prio = base_fee, priority
    if bump and base_fee:
        max_fee, max_prio = GAS_BUMP.bumped_fees(base_fee, priority, bump_pct)
    return {
        "block_duplicate": dup,
        "fast_gas_bump": bump,
        "gas_bump_pct": bump_pct,
        "max_fee_per_gas": max_fee,
        "max_priority_fee_per_gas": max_prio,
        "resign_turbo": RESIGN._last_nonce is not None,
    }
