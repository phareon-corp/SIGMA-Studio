"""Eixo de frequência, estimativa de tempo e o resultado de uma varredura."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from .config import MeasurementConfig
from .params import MEAS_PARAMS, MeasParam


@dataclass(frozen=True, slots=True)
class AxisInfo:
    """O que o eixo X de uma varredura é: muda com SWPP, a matemática não."""

    param: str  # FREQ | OLEV | DCB
    label: str  # para gráfico e tabela
    unit: str  # SI
    column: str  # nome de coluna no CSV/Parquet
    header: str  # como aparece em "SWEEP TYPE: LIN <header>"

    @property
    def is_frequency(self) -> bool:
        return self.param == "FREQ"


def axis_info(sweep_param: str, osc_mode: str = "VOLT", dc_bias_mode: str = "VOLT") -> AxisInfo:
    if sweep_param == "DCB":
        v = dc_bias_mode == "VOLT"
        return AxisInfo("DCB", "Bias DC", "V" if v else "A", "dc_bias_V" if v else "dc_bias_A",
                        "DC BIAS VOLT" if v else "DC BIAS CURRENT")
    if sweep_param == "OLEV":
        v = osc_mode == "VOLT"
        return AxisInfo("OLEV", "Nível do oscilador", "V" if v else "A",
                        "osc_level_V" if v else "osc_level_A", "OSC LEVEL")
    return AxisInfo("FREQ", "Frequência", "Hz", "frequency_Hz", "FREQ")


def sweep_axis(start: float, stop: float, points: int, sweep_type: str,
               direction: str = "UP") -> np.ndarray:
    """Eixo de LIN/LOG calculado de STAR?/STOP?/POIN?, em qualquer unidade."""
    if sweep_type == "LIN":
        x = np.linspace(start, stop, points)
    elif sweep_type == "LOG":
        x = np.geomspace(start, stop, points)
    else:
        raise ValueError("em LIST o eixo precisa vir do instrumento (OUTPSWPRM?)")
    return x[::-1].copy() if direction == "DOWN" else x


#: nome antigo, mantido para quem ainda chama
frequency_axis = sweep_axis


# Tempo por ponto por BWFACT. Ordem de grandeza só para a barra de progresso
# e para o teto de espera: o término real é dado pelo instrumento.
_SEC_PER_POINT = {1: 0.003, 2: 0.006, 3: 0.012, 4: 0.03, 5: 0.06}


def _work_points(cfg: MeasurementConfig) -> int:
    paver = cfg.point_avg_factor if cfg.point_avg_on else 1
    return cfg.points * paver * cfg.sweeps_per_trigger


def timing_key(cfg: MeasurementConfig) -> str:
    """O tempo por ponto depende sobretudo de BWFACT e da menor frequência medida."""
    decade = int(math.floor(math.log10(max(cfg.lowest_frequency, 1.0))))
    return f"{cfg.sweep_param}:bw{cfg.bw}:1e{decade}"


class SweepTimer:
    """Lembra o tempo real por ponto de cada varredura concluída.

    A tabela fixa abaixo erra feio em frequência baixa (a 100 Hz o 4294A
    integra vários períodos de 10 ms por ponto); medido uma vez, o tempo real
    passa a valer para a barra de progresso daquela combinação.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.sec_per_point: dict[str, float] = {}
        if path is not None and path.exists():
            try:
                self.sec_per_point = {k: float(v) for k, v in json.loads(path.read_text()).items()}
            except (OSError, ValueError, AttributeError):
                self.sec_per_point = {}

    def estimate(self, cfg: MeasurementConfig) -> float:
        learned = self.sec_per_point.get(timing_key(cfg))
        if learned is None:
            return estimate_sweep_seconds(cfg)
        return _work_points(cfg) * learned + 0.3

    def record(self, cfg: MeasurementConfig, seconds: float) -> None:
        self.sec_per_point[timing_key(cfg)] = max(seconds - 0.3, 0.0) / max(_work_points(cfg), 1)
        if self.path is not None:
            try:
                self.path.write_text(json.dumps(self.sec_per_point, indent=1))
            except OSError:
                pass


def estimate_sweep_seconds(cfg: MeasurementConfig) -> float:
    per = _SEC_PER_POINT.get(cfg.bw, 0.06)
    f_low = cfg.lowest_frequency  # STAR em FREQ; CWFREQ em OLEV/DCB
    if f_low < 1e3:  # abaixo de 1 kHz o período domina
        per += 2.0 / max(f_low, 40.0) / 10
    paver = cfg.point_avg_factor if cfg.point_avg_on else 1
    return cfg.points * per * paver * cfg.sweeps_per_trigger + 0.3


@dataclass(slots=True)
class CompensationState:
    open: bool | None = None
    short: bool | None = None
    load: bool | None = None

    def text(self) -> str:
        f = lambda v: "?" if v is None else ("ON" if v else "OFF")  # noqa: E731
        return f"OPEN {f(self.open)} · SHORT {f(self.short)} · LOAD {f(self.load)}"


@dataclass(slots=True)
class SweepResult:
    config: MeasurementConfig
    x: np.ndarray  # eixo varrido; unidade em .axis
    trace_a: np.ndarray
    trace_b: np.ndarray
    timestamp: datetime = field(default_factory=datetime.now)
    idn: str = ""
    compensation: CompensationState = field(default_factory=CompensationState)
    source: str = "gpib"  # "gpib" | "savdasc"
    notes: dict[str, str] = field(default_factory=dict)

    @property
    def param(self) -> MeasParam:
        return MEAS_PARAMS[self.config.meas]

    @property
    def axis(self) -> AxisInfo:
        c = self.config
        return axis_info(c.sweep_param, c.osc_mode, c.dc_bias_mode)

    @property
    def frequency(self) -> np.ndarray:
        """Frequência em que cada ponto foi medido (CWFREQ fora de SWPP FREQ)."""
        if self.axis.is_frequency:
            return self.x
        return np.full(self.x.shape, float(self.config.cw_freq_hz))

    @property
    def points(self) -> int:
        return int(self.x.size)
