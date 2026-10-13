"""Permissividade pelo método de placas paralelas (16451B, eletrodo com guarda).

    eps_r' = Cp · t / (eps0 · A)       A = π (d/2)²
    tan δ  = D
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .params import to_cp_d
from .sweep import AxisInfo, SweepResult

EPS0 = 8.8541878128e-12  # F/m


@dataclass(frozen=True, slots=True)
class Geometry:
    thickness_m: float
    electrode_diameter_m: float

    @property
    def area_m2(self) -> float:
        return np.pi * (self.electrode_diameter_m / 2) ** 2

    def validate(self) -> list[str]:
        e = []
        if self.thickness_m <= 0:
            e.append("espessura precisa ser positiva")
        if self.electrode_diameter_m <= 0:
            e.append("diâmetro do eletrodo precisa ser positivo")
        return e


@dataclass(slots=True)
class DielectricResult:
    x: np.ndarray  # mesmo eixo da varredura (frequência, bias, nível)
    eps_real: np.ndarray
    tan_delta: np.ndarray
    geometry: Geometry
    axis: AxisInfo
    cw_freq_hz: float | None = None  # frequência fixa, fora de SWPP FREQ


def eps_from_cp(cp: np.ndarray, geom: Geometry) -> np.ndarray:
    return np.asarray(cp, dtype=float) * geom.thickness_m / (EPS0 * geom.area_m2)


def compute(sweep: SweepResult, geom: Geometry) -> DielectricResult:
    errs = geom.validate()
    if errs:
        raise ValueError("; ".join(errs))
    # Cp-G/Cp-Rp → D usa ω da frequência medida: em DCB/OLEV é CWFREQ
    cp, d = to_cp_d(sweep.config.meas, sweep.frequency, sweep.trace_a, sweep.trace_b)
    ax = sweep.axis
    return DielectricResult(sweep.x, eps_from_cp(cp, geom), d, geom, ax,
                            None if ax.is_frequency else float(sweep.config.cw_freq_hz))
