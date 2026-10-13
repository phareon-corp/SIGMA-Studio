"""4294A falso: aceita os mnemônicos HP, mantém estado, gera varredura sintética.

A amostra é um dielétrico de Cole-Cole entre os eletrodos do 16451B, com
parasitas de fixture que somem quando a compensação correspondente está
ligada — assim o assistente de compensação tem efeito visível.

O que o simulador NÃO sabe é o Programming Manual: os nomes de transferência
de array (OUTPDTRC?, OUTPDATA?, OUTPSWPRM?) e FORM2/3/4/5 seguem a convenção
HP da família 8753/4395. O probe existe justamente para descobrir o que o
instrumento real aceita.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

import numpy as np

from ..model.config import ADAPTERS, F_MAX, F_MIN
from ..model.params import MEAS_PARAMS, from_impedance

IDN = "HEWLETT-PACKARD,4294A,SIM00000001,REV1.11"

ERRORS = {
    10: "ADDITIONAL STANDARDS NEEDED",
    11: "CALIBRATION REQUIRED",
    -100: "Command error",
    -109: "Missing parameter",
    -113: "Undefined header",
    -141: "Invalid character data",
    -213: "Init ignored",
    137: "DCBIAS OVERLOAD",
    -221: "Settings conflict",
    -222: "Data out of range",
    -224: "Illegal parameter value",
    -410: "Query INTERRUPTED",
}

_ENUMS: dict[str, tuple[str, ...]] = {
    "E4TP": tuple(ADAPTERS),
    "CALP": ("FIXED", "USER"),
    "MEAS": tuple(MEAS_PARAMS),
    "TRAC": ("A", "B"),
    "SWPP": ("FREQ", "OLEV", "DCB"),
    "SWPT": ("LIN", "LOG", "LIST"),
    "SWED": ("UP", "DOWN"),
    "POWMOD": ("VOLT", "CURR"),
    "TRGS": ("INT", "EXT", "BUS", "MAN"),
    "DCMOD": ("VOLT", "CURR", "CVOLT", "CCURR"),
    "DCRNG": ("M1", "M10", "M100"),
    "STOD": ("MEMO", "FLASH", "DISK"),
}
_BOOLS = ("DCO", "AVER", "PAVER", "COMSTA", "COMSTB", "COMSTC", "SAVDAT", "SAVDTRC", "SAVCAL", "CALST")
_NUMS: dict[str, tuple[float, float, bool]] = {  # (mín, máx, inteiro)
    "STAR": (F_MIN, F_MAX, False), "STOP": (F_MIN, F_MAX, False),
    "POIN": (2, 801, True), "CWFREQ": (F_MIN, F_MAX, False),
    "POWE": (0, 1.0, False), "DCV": (-40, 40, False), "DCI": (-0.1, 0.1, False),
    "BWFACT": (1, 5, True), "AVERFACT": (1, 256, True), "PAVERFACT": (1, 256, True),
    "DCALOPENG": (-1e3, 1e3, False), "DCALOPENC": (-1, 1, False),
    "DCALSHORR": (-1e3, 1e3, False), "DCALSHORL": (-1, 1, False),
    "DCALLOADR": (-1e12, 1e12, False), "DCALLOADL": (-1, 1, False),
}
_SEC_PER_POINT = {1: 0.003, 2: 0.006, 3: 0.012, 4: 0.03, 5: 0.06}


def _defaults() -> dict[str, object]:
    return {
        "E4TP": "OFF", "CALP": "FIXED", "MEAS": "IMPH", "TRAC": "A",
        "SWPP": "FREQ", "SWPT": "LIN", "SWED": "UP", "POWMOD": "VOLT", "TRGS": "INT",
        "STOD": "MEMO", "DCMOD": "VOLT", "DCRNG": "M1", "DCO": False, "AVER": False, "PAVER": False,
        "COMSTA": False, "COMSTB": False, "COMSTC": False, "CALST": False,
        "SAVDAT": False, "SAVDTRC": True, "SAVCAL": False,
        "STAR": 40.0, "STOP": 110e6, "POIN": 201, "CWFREQ": 1e6, "POWE": 0.5,
        "DCV": 0.0, "DCI": 0.0, "BWFACT": 1, "AVERFACT": 16, "PAVERFACT": 1,
        "DCALOPENG": 0.0, "DCALOPENC": 0.0, "DCALSHORR": 0.0, "DCALSHORL": 0.0,
        "DCALLOADR": 50.0, "DCALLOADL": 0.0,
    }


@dataclass(slots=True)
class Sample:
    """Dielétrico de Cole-Cole num capacitor de placas paralelas.

    Sob bias DC a permissividade cai como num dielétrico sintonizável
    (forma de Johnson, ε(V) = ε(0) / (1 + (V/V0)²)^(1/3)), e sobe um pouco
    com o nível do oscilador. É uma C-V sintética para exercitar o app, não
    um modelo físico de uma amostra de 1 mm.
    """

    eps_inf: float = 3.2
    delta_eps: float = 1.8
    f_relax: float = 50e3
    alpha: float = 0.15
    sigma: float = 2e-9  # S/m
    thickness_m: float = 1e-3
    electrode_diameter_m: float = 38e-3
    tune_v0: float = 12.0  # V: tensão em que ε caiu ~21 %
    osc_coeff: float = 0.03  # 1/V: subida de ε com o nível do oscilador

    def impedance(self, f: np.ndarray, bias_v: np.ndarray | float = 0.0,
                  osc_v: np.ndarray | float = 0.5) -> np.ndarray:
        w = 2 * np.pi * f
        tau = 1 / (2 * np.pi * self.f_relax)
        eps = self.eps_inf + self.delta_eps / (1 + (1j * w * tau) ** (1 - self.alpha))
        eps = eps / (1 + (np.asarray(bias_v) / self.tune_v0) ** 2) ** (1 / 3)
        eps = eps * (1 + self.osc_coeff * np.asarray(osc_v))
        eps = eps - 1j * self.sigma / (w * 8.8541878128e-12)
        c0 = 8.8541878128e-12 * np.pi * (self.electrode_diameter_m / 2) ** 2 / self.thickness_m
        return 1 / (1j * w * c0 * eps)


@dataclass(slots=True)
class Fixture:
    c_stray: float = 1.5e-12  # some com OPEN
    r_res: float = 0.05  # somem com SHORT
    l_res: float = 40e-9
    gain_err: float = 0.004  # some com LOAD


@dataclass
class Sim4294A:
    time_scale: float = 0.1
    seed: int = 1
    clock: Callable[[], float] = time.monotonic
    sample: Sample = field(default_factory=Sample)
    fixture: Fixture = field(default_factory=Fixture)

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        self.files: dict[str, str] = {}
        self.output: deque[bytes] = deque()
        self.reset()

    # ── estado ──────────────────────────────────────────────────────────
    def reset(self) -> None:
        self.state = _defaults()
        self.fmt = {"A": "LOGY", "B": "LINY"}
        self.form = "FORM4"
        self.errors: deque[int] = deque(maxlen=32)
        self.esr = 0
        self.ese = 0
        self.sre = 0
        self.sweeps_left = 0
        self.sweep_end: float | None = None
        self.continuous = False
        self.pending_comp: str | None = None
        self.comp_measured = {"A": False, "B": False, "C": False}
        self.ecal_measured: set[str] = set()  # P, A, B, C — setup do adaptador
        self.ucal_measured: set[str] = set()  # A, B, C — calibração de usuário
        self.adapter_setup_done = False
        self.pending_cal: tuple[str, str] | None = None  # ("ecal"|"ucal", chave)
        self.opc_armed = False
        self.opc_query = False
        self.trace_a = self.trace_b = self.z = np.empty(0)
        self.freq = np.empty(0)
        self.sweep_count = 0

    def error(self, code: int) -> None:
        self.errors.append(code)
        self.esr |= 0x20 if code < 0 else 0x08  # CME / DDE

    @property
    def busy(self) -> bool:
        return self.sweep_end is not None

    def device_clear(self) -> None:
        self.output.clear()
        self.opc_query = False

    # ── tempo ───────────────────────────────────────────────────────────
    def sweep_seconds(self) -> float:
        per = _SEC_PER_POINT[int(self.state["BWFACT"])]
        paver = int(self.state["PAVERFACT"]) if self.state["PAVER"] else 1
        return max(int(self.state["POIN"]) * per * paver * self.time_scale, 1e-4)

    def _start(self, sweeps: int) -> None:
        self.sweeps_left = sweeps
        self.sweep_end = self.clock() + self.sweep_seconds()

    def service(self) -> None:
        """Avança o relógio: conclui varreduras vencidas."""
        while self.sweep_end is not None and self.clock() >= self.sweep_end:
            self._acquire()
            self.sweeps_left -= 1
            if self.continuous or self.sweeps_left > 0:
                self.sweep_end += self.sweep_seconds()
                continue
            self.sweep_end = None
            if self.pending_comp:
                self.comp_measured[self.pending_comp] = True
                self.state["COMST" + self.pending_comp] = True  # o 4294A liga sozinho (p. 152)
                self.pending_comp = None
            if self.pending_cal:
                kind, key = self.pending_cal
                (self.ecal_measured if kind == "ecal" else self.ucal_measured).add(key)
                self.pending_cal = None
            if self.opc_armed:
                self.esr |= 0x01
                self.opc_armed = False
            if self.opc_query:
                self.output.append(b"1")
                self.opc_query = False

    def status_byte(self) -> int:
        self.service()
        stb = 0
        if self.errors:
            stb |= 0x04
        if self.output:
            stb |= 0x10
        if self.esr & self.ese:
            stb |= 0x20
        if stb & self.sre:
            stb |= 0x40
        return stb

    # ── dados ───────────────────────────────────────────────────────────
    def axis(self) -> np.ndarray:
        s = self.state
        a, b, n = float(s["STAR"]), float(s["STOP"]), int(s["POIN"])
        f = np.geomspace(a, b, n) if s["SWPT"] == "LOG" else np.linspace(a, b, n)
        return f[::-1].copy() if s["SWED"] == "DOWN" else f

    def sweep_range(self) -> tuple[float, float]:
        s = self.state
        if s["SWPP"] == "DCB":
            lim = 40.0 if s["DCMOD"] in ("VOLT", "CVOLT") else 0.1
            return (-lim, lim)
        if s["SWPP"] == "OLEV":
            return (0.0, 1.0) if s["POWMOD"] == "VOLT" else (0.0, 0.02)
        return (F_MIN, F_MAX)

    def _acquire(self) -> None:
        s = self.state
        x = self.axis()
        n = x.size
        volt_bias = s["DCMOD"] in ("VOLT", "CVOLT")
        fixed_bias = float(s["DCV"]) if (s["DCO"] and volt_bias) else 0.0
        fixed_osc = float(s["POWE"]) if s["POWMOD"] == "VOLT" else 0.5
        f = x if s["SWPP"] == "FREQ" else np.full(n, float(s["CWFREQ"]))
        # bias em corrente num capacitor não sustenta tensão DC: C plana
        bias = x if (s["SWPP"] == "DCB" and volt_bias) else np.full(n, fixed_bias if s["SWPP"] != "DCB" else 0.0)
        osc = x if (s["SWPP"] == "OLEV" and s["POWMOD"] == "VOLT") else np.full(n, fixed_osc)
        z = self.sample.impedance(f, bias, osc)
        w = 2 * np.pi * f
        fx = self.fixture
        if not s["COMSTA"]:
            z = 1 / (1 / z + 1j * w * fx.c_stray)
        if not s["COMSTB"]:
            z = z + fx.r_res + 1j * w * fx.l_res
        if not s["COMSTC"]:
            z = z * (1 + fx.gain_err)
        bw = int(s["BWFACT"])
        avg = int(s["AVERFACT"]) if s["AVER"] else 1
        sigma = 1.5e-3 / bw / np.sqrt(avg)
        z = z * (1 + sigma * (self.rng.standard_normal(f.size) + 1j * self.rng.standard_normal(f.size)))
        self.freq, self.z = x, z  # "freq" = eixo varrido (OUTPSWPRM?)
        self.trace_a, self.trace_b = from_impedance(str(s["MEAS"]), f, z)
        self.sweep_count += 1

    def _ensure_data(self) -> None:
        if self.freq.size != int(self.state["POIN"]) or self.trace_a.size == 0:
            self._acquire()

    def _array(self, values: np.ndarray) -> bytes:
        if self.form == "FORM4":
            return ",".join(f"{v:+.11E}" for v in values).encode()
        dt = {"FORM2": ">f4", "FORM3": ">f8", "FORM5": "<f4"}[self.form]
        body = np.asarray(values, dtype=dt).tobytes()
        return f"#6{len(body):06d}".encode() + body

    # ── recepção ────────────────────────────────────────────────────────
    def receive(self, message: str) -> None:
        self.service()
        replies: list[bytes] = []
        for unit in message.split(";"):
            unit = unit.strip()
            if not unit:
                continue
            head, _, arg = unit.partition(" ")
            head, arg = head.upper(), arg.strip()
            try:
                r = self._query(head[:-1]) if head.endswith("?") else self._command(head, arg)
            except _SimError as exc:
                self.error(exc.code)
                continue
            if r is not None:
                replies.append(r)
        if replies:
            self.output.append(b";".join(replies))

    def _query(self, h: str) -> bytes | None:
        s = self.state
        if h == "*IDN":
            return IDN.encode()
        if h == "*OPC":
            if self.busy:
                self.opc_query = True
                return None
            return b"1"
        if h == "*ESR":
            v, self.esr = self.esr, 0
            return str(v).encode()
        if h == "*ESE":
            return str(self.ese).encode()
        if h == "*SRE":
            return str(self.sre).encode()
        if h == "*STB":
            return str(self.status_byte()).encode()
        if h == "OUTPERRO":
            if not self.errors:
                return b'0,"No error"'
            c = self.errors.popleft()
            return f'{c},"{ERRORS.get(c, "Error")}"'.encode()
        if h == "OUTPDTRC":
            self._ensure_data()
            v = self.trace_a if s["TRAC"] == "A" else self.trace_b
            pairs = np.column_stack([v, np.zeros_like(v)]).ravel()
            return self._array(pairs)
        if h == "OUTPDATA":
            self._ensure_data()
            return self._array(np.column_stack([self.z.real, self.z.imag]).ravel())
        if h == "OUTPSWPRM":
            self._ensure_data()
            return self._array(self.freq)
        if h == "FMT":
            return self.fmt[str(s["TRAC"])].encode()
        if h == "FORM":
            return self.form.encode()
        if h in s:
            v = s[h]
            if isinstance(v, bool):
                return b"1" if v else b"0"
            if isinstance(v, str):
                return v.encode()
            if _NUMS[h][2]:
                return f"{int(v)}".encode()
            return f"{float(v):+.11E}".encode()
        raise _SimError(-113)

    def _command(self, h: str, arg: str) -> None:
        s = self.state
        if h in ("PRES", "*RST"):
            self.reset()
        elif h == "*TRG":
            pass  # SING já iniciou a varredura
        elif h == "*CLS":
            self.errors.clear()
            self.esr = 0
        elif h == "*ESE":
            self.ese = int(self._num(arg, 0, 255))
        elif h == "*SRE":
            self.sre = int(self._num(arg, 0, 255))
        elif h == "*OPC":
            if self.busy:
                self.opc_armed = True
            else:
                self.esr |= 0x01
        elif h in ("FORM2", "FORM3", "FORM4", "FORM5"):
            self.form = h
        elif h == "HOLD":
            self.continuous = False
            self.sweep_end = None
            self.sweeps_left = 0
            self.pending_comp = None
            self.pending_cal = None
        elif h in ("SING", "NUMG"):
            if self.busy and not self.continuous:
                raise _SimError(-213)
            self.continuous = False
            n = 1 if h == "SING" else int(self._num(arg, 1, 999))
            self._start(n)
        elif h == "CONT":
            self.continuous = True
            self._start(1)
        elif h in ("COMA", "COMB", "COMC"):
            if self.busy and not self.continuous:
                raise _SimError(-213)
            self.continuous = False
            self.pending_comp = h[-1]
            self._start(1)
        elif h in ("ECALP", "ECALA", "ECALB", "ECALC"):
            if self.busy and not self.continuous:
                raise _SimError(-213)
            self.continuous = False
            self.pending_cal = ("ecal", h[-1])
            self.sweep_end = self.clock() + 30 * self.sweep_seconds()  # "alguns minutos"
            self.sweeps_left = 1
        elif h == "ECALDON":
            if "P" not in self.ecal_measured:
                raise _SimError(10)
            self.adapter_setup_done = True
            self.ecal_measured.clear()
        elif h in ("CALA", "CALB", "CALC"):
            if self.state["E4TP"] not in ("APC7", "PROBE"):
                raise _SimError(-224)  # 4TP 1M: "cannot be performed"
            if self.busy and not self.continuous:
                raise _SimError(-213)
            self.continuous = False
            self.pending_cal = ("ucal", h[-1])
            self._start(1)
        elif h == "CALDON":
            if self.ucal_measured != {"A", "B", "C"}:
                raise _SimError(10)
            self.state["CALST"] = True
        elif h == "SAVDASC":
            name = arg.strip('"').upper()
            if not name:
                raise _SimError(-109)
            self._ensure_data()
            self.files[f"{s['STOD']}:{name}.TXT"] = self.ascii_dump()
        elif h == "FMT":
            if arg.upper() not in ("LINY", "LOGY"):
                raise _SimError(-141)
            self.fmt[str(s["TRAC"])] = arg.upper()
        elif h in _ENUMS:
            v = arg.upper()
            if not v:
                raise _SimError(-109)
            if v not in _ENUMS[h]:
                raise _SimError(-141)
            # log e list só existem varrendo frequência (cap. 10)
            if h == "SWPT" and v != "LIN" and s["SWPP"] != "FREQ":
                raise _SimError(-221)
            s[h] = v
            if h == "SWPP":
                if v != "FREQ":
                    s["SWPT"] = "LIN"
                lo, hi = self.sweep_range()
                s["STAR"] = min(max(float(s["STAR"]), lo), hi)
                s["STOP"] = min(max(float(s["STOP"]), lo), hi)
        elif h in _BOOLS:
            v = arg.upper()
            if v not in ("ON", "OFF", "1", "0"):
                raise _SimError(-141 if v else -109)
            on = v in ("ON", "1")
            if h.startswith("COMST") and on and not self.comp_measured[h[-1]]:
                raise _SimError(11)
            if h == "CALST" and on and self.ucal_measured != {"A", "B", "C"}:
                raise _SimError(11)
            s[h] = on
        elif h in ("STAR", "STOP"):
            s[h] = self._num(arg, *self.sweep_range())  # unidade segue SWPP
        elif h in _NUMS:
            lo, hi, is_int = _NUMS[h]
            v = self._num(arg, lo, hi)
            s[h] = int(round(v)) if is_int else v
        else:
            raise _SimError(-113)
        return None

    @staticmethod
    def _num(arg: str, lo: float, hi: float) -> float:
        if not arg:
            raise _SimError(-109)
        try:
            v = float(arg)
        except ValueError:
            raise _SimError(-141) from None
        if not lo <= v <= hi:
            raise _SimError(-222)
        return v

    # ── SAVDASC ─────────────────────────────────────────────────────────
    def ascii_dump(self) -> str:
        s = self.state
        p = MEAS_PARAMS[str(s["MEAS"])]
        osc = f"{float(s['POWE']) * 1e3:g} mVolt" if s["POWMOD"] == "VOLT" else f"{float(s['POWE']) * 1e3:g} mAmp"
        out = [
            "4294A REV1.11",
            f'"DATE: {datetime.now():%b %d %Y}"',
            f'"MEASURE PARAMETER: {p.long_name}"',
            f'"ADAPTER: {ADAPTERS[str(s["E4TP"])]}"',
            f'"SWEEP TYPE: {s["SWPT"]} {dict(FREQ="FREQ", OLEV="OSC LEVEL", DCB="DC BIAS")[str(s["SWPP"])]}"',
            f'"NUMBER of POINTS: {s["POIN"]}"',
            '"POINT DELAY TIME: 0 Sec"',
            '"SWEEP DELAY TIME: 0 Sec"',
            f'"OSC LEVEL: {osc}"',
            f'"DC BIAS: {"ON" if s["DCO"] else "OFF"}"',
            f'"BW: {s["BWFACT"]}"',
            f'"SWEEP AVERAGING: {"ON" if s["AVER"] else "OFF"}"',
            f'"POINT AVERAGING: {"ON" if s["PAVER"] else "OFF"}"',
            f'"Cal Point: {s["CALP"]}"',
        ]
        for name, vals in (("A", self.trace_a), ("B", self.trace_b)):
            out += [f'"TRACE: {name}"',
                    f'"FORMAT: {"LOG" if self.fmt[name] == "LOGY" else "LINEAR"}"',
                    '"Frequency" "Data Real" "Data Imag" "Data Trace Real" "Data Trace Imag"']
            for f, z, v in zip(self.freq, self.z, vals):
                out.append(f"{f:.11e} {z.real:.6e} {z.imag:.6e} {v:.6e} {0:.6e}")
        return "\n".join(out) + "\n"


class _SimError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code
