from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_QUANT = Decimal("0.01")


def parse_fp(value: str | None) -> Decimal:
    if value is None:
        return _ZERO
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        logger.warning("Invalid fixed-point value %r; normalizing to zero: %s", value, exc)
        return _ZERO


def sum_fp(values: list[str | None]) -> str:
    total = sum((parse_fp(value) for value in values), start=_ZERO)
    return format(total.quantize(_QUANT, rounding=ROUND_HALF_UP), "f")