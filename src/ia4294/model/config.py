"""Configuração de medida, sua tradução em mnemônicos HP e perfis JSON."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .params import MEAS_PARAMS

# Limites do Operation Manual, cap. 10 (Basic Characteristics).
F_MIN = 40.0
F_MAX = 110e6
OSC_V = (5e-3, 1.0)  # Voltage Signal Level: 5 mVrms a 1 Vrms
OSC_A = (200e-6, 20e-3)  # Current Signal Level: 200 µArms a 20 mArms
BIAS_V = 40.0  # dc voltage bias: 0 a ±40 V (Figura 10-1)
BIAS_A = 0.1  # dc current bias: 0 a ±100 mA (Figura 10-1)
POINTS_MIN, POINTS_MAX = 2, 801

ADAPTERS = {"OFF": "NONE", "M1": "4TP 1M", "M2": "4TP 2M", "APC7": "7mm 42942A", "PROBE": "PROBE 42941A"}
#: SWPP: frequência, nível do oscilador, bias DC
SWEEP_PARAMS = ("FREQ", "OLEV", "DCB")
SWEEP_TYPES = ("LIN", "LOG", "LIST")
#: "Sweep types: Linear, log¹, list¹ — ¹Frequency sweep only" (cap. 10)
SWEEP_TYPES_FOR = {"FREQ": SWEEP_TYPES, "OLEV": ("LIN",), "DCB": ("LIN",)}
TRIGGER_SOURCES = ("INT", "EXT", "BUS", "MAN")
#: DCRNG: faixa de corrente DC que entra no circuito de medida (Tabela B-55)
DC_RANGES = {"M1": "< 1 mA", "M10": "< 10 mA", "M100": "< 100 mA"}

#: chaves de perfis antigos → atuais
_LEGACY_KEYS = {"start_hz": "start", "stop_hz": "stop"}


def osc_range(mode: str) -> tuple[float, float]:
    return OSC_V if mode == "VOLT" else OSC_A


def bias_range(mode: str) -> tuple[float, float]:
    lim = BIAS_V if mode == "VOLT" else BIAS_A
    return (-lim, lim)


@dataclass(slots=True)
class MeasurementConfig:
    # estado / fixture
    adapter: str = "M1"  # E4TP M1: o 16451B usa o cabo de 1 m
    cal_point: str = "FIXED"  # CALP
    # medida
    meas: str = "CPD"
    fmt_a: str = "LOGY"
    fmt_b: str = "LINY"
    # varredura — STAR/STOP são um par só; a unidade vem de sweep_param
    sweep_param: str = "FREQ"  # SWPP
    sweep_type: str = "LOG"
    start: float = 1e3
    stop: float = 10e6
    points: int = 201
    direction: str = "UP"
    # fonte
    osc_mode: str = "VOLT"  # POWMOD
    osc_level: float = 0.5  # V ou A conforme osc_mode; ignorado em SWPP OLEV
    cw_freq_hz: float = 1e6  # frequência fixa em SWPP OLEV/DCB
    dc_bias_on: bool = False  # forçado em SWPP DCB
    dc_bias_mode: str = "VOLT"  # DCMOD: VOLT → DCV, CURR → DCI
    dc_bias_level: float = 0.0  # ignorado em SWPP DCB
    # Faixa de corrente do bias. O manual (cap. 5) manda começar em 1 mA e subir
    # um degrau por vez enquanto aparecer "DCBIAS OVERLOAD" (137); sem bias, 1 mA.
    dc_range: str = "M1"
    # exatidão
    bw: int = 3
    averaging_on: bool = False
    averaging_factor: int = 4
    point_avg_on: bool = False
    point_avg_factor: int = 4
    # disparo
    trigger_source: str = "INT"

    # ── faixa do eixo ───────────────────────────────────────────────────
    def sweep_range(self) -> tuple[float, float]:
        if self.sweep_param == "OLEV":
            return osc_range(self.osc_mode)
        if self.sweep_param == "DCB":
            return bias_range(self.dc_bias_mode)
        return (F_MIN, F_MAX)

    @property
    def bias_active(self) -> bool:
        """Há tensão/corrente DC no fixture?"""
        return self.sweep_param == "DCB" or self.dc_bias_on

    # ── validação ───────────────────────────────────────────────────────
    def validate(self) -> list[str]:
        e: list[str] = []
        if self.meas not in MEAS_PARAMS:
            e.append(f"MEAS {self.meas} desconhecido")
        if self.adapter not in ADAPTERS:
            e.append(f"adaptador {self.adapter} desconhecido")
        if self.sweep_param not in SWEEP_PARAMS:
            e.append(f"SWPP {self.sweep_param} inválido")
        elif self.sweep_type not in SWEEP_TYPES_FOR[self.sweep_param]:
            e.append(f"SWPT {self.sweep_type} só existe varrendo frequência; com {self.sweep_param} use LIN")
        if self.sweep_type not in SWEEP_TYPES:
            e.append(f"tipo de varredura {self.sweep_type} inválido")
        if self.sweep_param in SWEEP_PARAMS:
            lo, hi = self.sweep_range()
            if not (lo <= self.start <= hi and lo <= self.stop <= hi):
                e.append(f"STAR/STOP fora de {self._range_text(lo, hi)}")
        if self.start >= self.stop:
            e.append("START precisa ser menor que STOP (para descer, use SWED DOWN)")
        if self.sweep_param != "FREQ" and not (F_MIN <= self.cw_freq_hz <= F_MAX):
            e.append("CWFREQ fora de 40 Hz – 110 MHz")
        if self.sweep_param != "OLEV":
            lo, hi = osc_range(self.osc_mode)
            if not lo <= self.osc_level <= hi:
                e.append(f"POWE fora de {self._range_text(lo, hi, self.osc_mode)}")
        if self.sweep_param != "DCB" and self.dc_bias_on:
            lo, hi = bias_range(self.dc_bias_mode)
            if not lo <= self.dc_bias_level <= hi:
                e.append(f"nível de bias fora de {self._range_text(lo, hi, self.dc_bias_mode)}")
        if self.dc_range not in DC_RANGES:
            e.append(f"DCRNG {self.dc_range} inválido")
        if not (POINTS_MIN <= self.points <= POINTS_MAX):
            e.append("POIN fora de 2–801")
        if not (1 <= self.bw <= 5):
            e.append("BWFACT fora de 1–5")
        if not (1 <= self.averaging_factor <= 256):
            e.append("AVERFACT fora de 1–256")
        if not (1 <= self.point_avg_factor <= 256):
            e.append("PAVERFACT fora de 1–256")
        if self.trigger_source not in TRIGGER_SOURCES:
            e.append(f"TRGS {self.trigger_source} inválido")
        return e

    def _range_text(self, lo: float, hi: float, mode: str | None = None) -> str:
        from .units import format_eng

        if mode is None:
            unit = {"FREQ": "Hz", "OLEV": "V" if self.osc_mode == "VOLT" else "A",
                    "DCB": "V" if self.dc_bias_mode == "VOLT" else "A"}[self.sweep_param]
        else:
            unit = "V" if mode == "VOLT" else "A"
        return f"{format_eng(lo, unit)} – {format_eng(hi, unit)}"

    # ── tradução ────────────────────────────────────────────────────────
    def command_blocks(self) -> list[tuple[str, str]]:
        """Blocos (nome, mensagem). Depois de cada um o driver pergunta OUTPERRO?.

        A fonte vem antes da varredura: em SWPP DCB a faixa de STAR/STOP depende
        de DCMOD, e em OLEV de POWMOD. O nível fixo que a varredura comanda
        (POWE em OLEV, DCV/DCI em DCB) não é enviado.
        """
        on = lambda b: "ON" if b else "OFF"  # noqa: E731
        src = [f"POWMOD {self.osc_mode}"]
        if self.sweep_param != "OLEV":
            src.append(f"POWE {self.osc_level:g}")
        src.append(f"CWFREQ {self.cw_freq_hz:.6g}")
        src.append(f"DCMOD {self.dc_bias_mode}")
        # sem bias, sempre 1 mA (cap. 5): a faixa larga só serve com corrente DC
        src.append(f"DCRNG {self.dc_range if self.bias_active else 'M1'}")
        if self.sweep_param == "DCB":
            src.append("DCO ON")
        else:
            src.append(f"DCV {self.dc_bias_level:g}" if self.dc_bias_mode == "VOLT" else f"DCI {self.dc_bias_level:g}")
            src.append(f"DCO {on(self.dc_bias_on)}")
        return [
            ("estado", f"E4TP {self.adapter};CALP {self.cal_point}"),
            ("medida", f"MEAS {self.meas};TRAC A;FMT {self.fmt_a};TRAC B;FMT {self.fmt_b};TRAC A"),
            ("fonte", ";".join(src)),
            ("varredura", f"SWPP {self.sweep_param};SWPT {self.sweep_type};STAR {self.start:.6g};"
                          f"STOP {self.stop:.6g};POIN {self.points};SWED {self.direction}"),
            ("exatidão", f"BWFACT {self.bw};AVER {on(self.averaging_on)};AVERFACT {self.averaging_factor};"
                         f"PAVER {on(self.point_avg_on)};PAVERFACT {self.point_avg_factor}"),
            ("disparo", f"TRGS {self.trigger_source}"),
        ]

    @property
    def sweeps_per_trigger(self) -> int:
        """Com média de varredura, um disparo são AVERFACT varreduras (NUMG)."""
        return self.averaging_factor if self.averaging_on else 1

    @property
    def lowest_frequency(self) -> float:
        """Menor frequência medida: STAR em FREQ, CWFREQ nos outros."""
        return self.start if self.sweep_param == "FREQ" else self.cw_freq_hz

    def osc_text(self) -> str:
        unit = "Volt" if self.osc_mode == "VOLT" else "Amp"
        if self.sweep_param == "OLEV":
            return f"SWEPT {self.start * 1e3:g} to {self.stop * 1e3:g} m{unit}"
        return f"{self.osc_level * 1e3:g} m{unit}"

    def bias_text(self) -> str:
        unit = "Volt" if self.dc_bias_mode == "VOLT" else "Amp"
        if self.sweep_param == "DCB":
            return f"SWEPT {self.start:g} to {self.stop:g} {unit}"
        if not self.dc_bias_on:
            return "OFF"
        return f"ON {self.dc_bias_level:g} {unit}"

    # ── perfis ──────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MeasurementConfig":
        known = {f.name for f in fields(cls)}
        d = {_LEGACY_KEYS.get(k, k): v for k, v in d.items()}
        return cls(**{k: v for k, v in d.items() if k in known})

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"ia4294_perfil": 1, **self.to_dict()}, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "MeasurementConfig":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
