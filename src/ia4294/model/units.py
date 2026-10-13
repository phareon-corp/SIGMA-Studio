"""Números com prefixo SI: "10M", "500m", "100E9", "2.2p"."""

from __future__ import annotations

import math
import re

PREFIXES = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3,
            "": 1.0, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}
_RX = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([fpnuµmkKMGT]?)\s*[A-Za-zΩ°]*\s*$")
_EXP_TO_PREFIX = {-15: "f", -12: "p", -9: "n", -6: "µ", -3: "m", 0: "", 3: "k", 6: "M", 9: "G", 12: "T"}


def parse_eng(text: str) -> float:
    m = _RX.match(text.replace(",", "."))
    if not m:
        raise ValueError(f"número inválido: {text!r}")
    return float(m.group(1)) * PREFIXES[m.group(2)]


def format_eng(value: float, unit: str = "", digits: int = 4) -> str:
    """``format_eng(1.2e-11, "F") == "12 pF"``. Unidade vazia → número puro."""
    if value is None or not math.isfinite(value):
        return "—"
    if not unit:
        return f"{value:.{digits}g}"
    if value == 0:
        return f"0 {unit}"
    exp = int(math.floor(math.log10(abs(value)) / 3) * 3)
    exp = max(-15, min(12, exp))
    mant = value / 10**exp
    if abs(float(f"{mant:.{digits}g}")) >= 1000 and exp < 12:
        exp += 3
        mant /= 1000
    return f"{mant:.{digits}g} {_EXP_TO_PREFIX[exp]}{unit}"
