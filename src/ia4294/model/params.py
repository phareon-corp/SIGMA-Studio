"""Parâmetros de medida do 4294A (MEAS) e sua conversão a partir de Z.

Lista conferida no Operation Manual, tabela de teclas de [Meas].
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class Quantity:
    symbol: str  # como aparece na tela: "Cp", "|Z|", "θ"
    unit: str  # SI, vazio para adimensional
    column: str  # nome de coluna seguro para CSV/Parquet


@dataclass(frozen=True, slots=True)
class MeasParam:
    mnemonic: str
    label: str  # "Cp-D"
    long_name: str  # como o 4294A escreve no cabeçalho ASCII
    a: Quantity
    b: Quantity


Z_ABS = Quantity("|Z|", "Ω", "Z_abs_ohm")
THETA_Z = Quantity("θz", "°", "theta_z_deg")
Y_ABS = Quantity("|Y|", "S", "Y_abs_S")
THETA_Y = Quantity("θy", "°", "theta_y_deg")
R = Quantity("R", "Ω", "R_ohm")
X = Quantity("X", "Ω", "X_ohm")
G = Quantity("G", "S", "G_S")
B = Quantity("B", "S", "B_S")
LS = Quantity("Ls", "H", "Ls_H")
LP = Quantity("Lp", "H", "Lp_H")
CS = Quantity("Cs", "F", "Cs_F")
CP = Quantity("Cp", "F", "Cp_F")
RS = Quantity("Rs", "Ω", "Rs_ohm")
RP = Quantity("Rp", "Ω", "Rp_ohm")
Q = Quantity("Q", "", "Q")
D = Quantity("D", "", "D")


def _p(m: str, label: str, long: str, a: Quantity, b: Quantity) -> MeasParam:
    return MeasParam(m, label, long, a, b)


MEAS_PARAMS: dict[str, MeasParam] = {p.mnemonic: p for p in (
    _p("CPD", "Cp-D", "PARALLEL CAPACITANCE - DISSIPATION FACTOR", CP, D),
    _p("CPQ", "Cp-Q", "PARALLEL CAPACITANCE - Q", CP, Q),
    _p("CPG", "Cp-G", "PARALLEL CAPACITANCE - CONDUCTANCE", CP, G),
    _p("CPR", "Cp-Rp", "PARALLEL CAPACITANCE - PARALLEL RESISTANCE", CP, RP),
    _p("CSD", "Cs-D", "SERIES CAPACITANCE - DISSIPATION FACTOR", CS, D),
    _p("CSQ", "Cs-Q", "SERIES CAPACITANCE - Q", CS, Q),
    _p("CSR", "Cs-Rs", "SERIES CAPACITANCE - SERIES RESISTANCE", CS, RS),
    _p("IMPH", "|Z|-θ", "IMPEDANCE MAG PHASE (DEG)", Z_ABS, THETA_Z),
    _p("IRIM", "R-X", "IMPEDANCE REAL IMAG", R, X),
    _p("AMPH", "|Y|-θ", "ADMITTANCE MAG PHASE (DEG)", Y_ABS, THETA_Y),
    _p("ARIM", "G-B", "ADMITTANCE REAL IMAG", G, B),
    _p("LSR", "Ls-Rs", "SERIES INDUCTANCE - SERIES RESISTANCE", LS, RS),
    _p("LSQ", "Ls-Q", "SERIES INDUCTANCE - Q", LS, Q),
    _p("LPG", "Lp-G", "PARALLEL INDUCTANCE - CONDUCTANCE", LP, G),
    _p("LPQ", "Lp-Q", "PARALLEL INDUCTANCE - Q", LP, Q),
    _p("LPR", "Lp-Rp", "PARALLEL INDUCTANCE - PARALLEL RESISTANCE", LP, RP),
    _p("IMLS", "|Z|-Ls", "IMPEDANCE MAG - SERIES INDUCTANCE", Z_ABS, LS),
    _p("IMCS", "|Z|-Cs", "IMPEDANCE MAG - SERIES CAPACITANCE", Z_ABS, CS),
    _p("IMLP", "|Z|-Lp", "IMPEDANCE MAG - PARALLEL INDUCTANCE", Z_ABS, LP),
    _p("IMCP", "|Z|-Cp", "IMPEDANCE MAG - PARALLEL CAPACITANCE", Z_ABS, CP),
    _p("IMRS", "|Z|-Rs", "IMPEDANCE MAG - SERIES RESISTANCE", Z_ABS, RS),
    _p("IMQ", "|Z|-Q", "IMPEDANCE MAG - Q", Z_ABS, Q),
    _p("IMD", "|Z|-D", "IMPEDANCE MAG - DISSIPATION FACTOR", Z_ABS, D),
)}

#: parâmetros dos quais o dielétrico sabe tirar Cp e D
DIELECTRIC_PARAMS = ("CPD", "CPG", "CPQ", "CPR")


def from_impedance(mnemonic: str, freq: np.ndarray, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Converte Z complexo nos dois traços do parâmetro (usado pelo simulador)."""
    w = 2 * np.pi * np.asarray(freq, dtype=float)
    z = np.asarray(z, dtype=complex)
    y = 1 / z
    rs, xs = z.real, z.imag
    g, b = y.real, y.imag
    vals: dict[Quantity, np.ndarray] = {
        Z_ABS: np.abs(z), THETA_Z: np.degrees(np.angle(z)),
        Y_ABS: np.abs(y), THETA_Y: np.degrees(np.angle(y)),
        R: rs, X: xs, G: g, B: b, RS: rs, RP: 1 / g,
        LS: xs / w, CS: -1 / (w * xs), LP: -1 / (w * b), CP: b / w,
        Q: np.abs(xs) / rs, D: rs / np.abs(xs),
    }
    p = MEAS_PARAMS[mnemonic]
    return vals[p.a], vals[p.b]


def to_cp_d(mnemonic: str, freq: np.ndarray, a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Cp e D a partir de qualquer parâmetro paralelo com capacitância."""
    w = 2 * np.pi * np.asarray(freq, dtype=float)
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if mnemonic == "CPD":
        return a, b
    if mnemonic == "CPQ":
        return a, 1 / b
    if mnemonic == "CPG":
        return a, b / (w * a)
    if mnemonic == "CPR":
        return a, 1 / (w * a * b)
    raise ValueError(f"{mnemonic} não dá Cp e D; meça em {', '.join(DIELECTRIC_PARAMS)}")
