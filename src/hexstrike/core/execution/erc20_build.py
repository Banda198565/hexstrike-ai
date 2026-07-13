"""ERC20 transfer payload builder."""

from __future__ import annotations

ERC20_TRANSFER_SELECTOR = "a9059cbb"


def encode_erc20_transfer(recipient: str, amount_wei: int) -> str:
    """Build calldata for transfer(address,uint256)."""
    to = recipient.lower().replace("0x", "")
    if len(to) != 40:
        raise ValueError(f"invalid recipient: {recipient}")
    addr_padded = to.rjust(64, "0")
    amt_hex = hex(amount_wei)[2:].rjust(64, "0")
    return "0x" + ERC20_TRANSFER_SELECTOR + addr_padded + amt_hex


def build_erc20_tx_fields(*, token: str, recipient: str, amount_wei: int) -> dict[str, str]:
    return {
        "to": token if token.startswith("0x") else f"0x{token}",
        "value": "0x0",
        "data": encode_erc20_transfer(recipient, amount_wei),
    }
