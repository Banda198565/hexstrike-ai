"""IBAN extraction, format validation, and ISO 13616 mod-97 checksum verification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

# ISO 13616 — country code + check digits + BBAN (15–30 alphanumeric)
_IBAN_PATTERN = re.compile(r"\b([A-Z]{2}\d{2}[A-Z0-9]{11,30})\b", re.IGNORECASE)
_NORMALIZE_RE = re.compile(r"[\s\-]")


class IbanValidationStatus(str, Enum):
    VALID_WHITELISTED = "valid_whitelisted"
    VALID_NOT_WHITELISTED = "valid_not_whitelisted"
    INVALID_FORMAT = "invalid_format"
    INVALID_CHECKSUM = "invalid_checksum"


@dataclass(frozen=True)
class IbanValidationResult:
    raw: str
    normalized: str
    status: IbanValidationStatus
    whitelisted: bool


def normalize_iban(value: str) -> str:
    return _NORMALIZE_RE.sub("", value).upper()


def extract_ibans(text: str) -> list[str]:
    """Return deduplicated normalized IBAN candidates found in text."""
    seen: set[str] = set()
    results: list[str] = []
    for match in _IBAN_PATTERN.finditer(text):
        normalized = normalize_iban(match.group(1))
        if normalized not in seen:
            seen.add(normalized)
            results.append(normalized)
    return results


def _iban_to_numeric(iban: str) -> str:
    rearranged = iban[4:] + iban[:4]
    digits: list[str] = []
    for char in rearranged:
        if char.isdigit():
            digits.append(char)
        elif char.isalpha():
            digits.append(str(ord(char) - 55))
        else:
            return ""
    return "".join(digits)


def verify_iban_checksum(iban: str) -> bool:
    """ISO 13616 mod-97 check — remainder must equal 1."""
    normalized = normalize_iban(iban)
    if not _IBAN_PATTERN.fullmatch(normalized):
        return False
    numeric = _iban_to_numeric(normalized)
    if not numeric:
        return False
    # Chunked mod to avoid bigint overflow on long IBANs
    remainder = 0
    for i in range(0, len(numeric), 9):
        chunk = str(remainder) + numeric[i : i + 9]
        remainder = int(chunk) % 97
    return remainder == 1


def validate_iban(value: str, whitelist: frozenset[str]) -> IbanValidationResult:
    normalized = normalize_iban(value)
    if not _IBAN_PATTERN.fullmatch(normalized):
        return IbanValidationResult(
            raw=value,
            normalized=normalized,
            status=IbanValidationStatus.INVALID_FORMAT,
            whitelisted=False,
        )
    if normalized in whitelist:
        return IbanValidationResult(
            raw=value,
            normalized=normalized,
            status=IbanValidationStatus.VALID_WHITELISTED,
            whitelisted=True,
        )
    if not verify_iban_checksum(normalized):
        return IbanValidationResult(
            raw=value,
            normalized=normalized,
            status=IbanValidationStatus.INVALID_CHECKSUM,
            whitelisted=False,
        )
    return IbanValidationResult(
        raw=value,
        normalized=normalized,
        status=IbanValidationStatus.VALID_NOT_WHITELISTED,
        whitelisted=False,
    )


def evaluate_outbound_ibans(
    text: str,
    whitelist: frozenset[str],
) -> list[IbanValidationResult]:
    return [validate_iban(iban, whitelist) for iban in extract_ibans(text)]
