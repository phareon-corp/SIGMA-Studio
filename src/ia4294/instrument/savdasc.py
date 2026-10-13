"""Rota alternativa: arquivo .TXT gravado pelo próprio 4294A (SAVDASC).

O instrumento grava no disquete/memória; o arquivo chega ao PC por fora do
GPIB e é importado aqui como uma corrida normal.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from ..model.config import MeasurementConfig
from ..model.params import MEAS_PARAMS
from ..model.sweep import SweepResult
from .parser import AsciiFile, ParseError, parse_savdasc

_MNEMONIC = re.compile(r"\(([A-Z]{2,4})\)\s*$")


def meas_from_header(text: str) -> str | None:
    if (m := _MNEMONIC.search(text)) and m.group(1) in MEAS_PARAMS:
        return m.group(1)
    for k, p in MEAS_PARAMS.items():
        if p.long_name == text.strip():
            return k
    return None


def to_result(f: AsciiFile, base: MeasurementConfig) -> SweepResult:
    if "A" not in f.traces or "B" not in f.traces:
        raise ParseError("arquivo sem TRACE A e TRACE B")
    a, b = f.traces["A"], f.traces["B"]
    h = f.header
    sweep = h.get("SWEEP TYPE", "").split()
    meas = meas_from_header(h.get("MEASURE PARAMETER", "")) or base.meas
    cfg = replace(base, meas=meas, points=int(a.frequency.size),
                  sweep_type=sweep[0] if sweep and sweep[0] in ("LIN", "LOG", "LIST") else base.sweep_type,
                  sweep_param="FREQ", start=float(a.frequency.min()), stop=float(a.frequency.max()),
                  fmt_a="LOGY" if a.fmt.startswith("LOG") else "LINY",
                  fmt_b="LOGY" if b.fmt.startswith("LOG") else "LINY")
    if h.get("BW", "").isdigit():
        cfg.bw = int(h["BW"])
    notes = {"SAVDASC " + k: v for k, v in h.items()}
    return SweepResult(cfg, a.frequency.copy(), a.data_trace.copy(), b.data_trace.copy(),
                       idn=f.revision, source="savdasc", notes=notes)


def load(path: Path, base: MeasurementConfig) -> SweepResult:
    return to_result(parse_savdasc(path.read_text(encoding="latin-1")), base)
