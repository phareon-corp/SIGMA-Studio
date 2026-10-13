"""Driver do 4294A sobre uma sessão AR488.

Todos os métodos bloqueiam e devem rodar na thread dona da porta.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np

from ..model.config import MeasurementConfig
from ..model.sweep import CompensationState, SweepResult, SweepTimer, estimate_sweep_seconds, sweep_axis
from ..transport.ar488 import AR488Session, GpibTimeout
from ..transport.traffic import NOTE
from .capabilities import Capabilities
from .parser import Identity, parse_block, parse_bool, parse_error, parse_idn, parse_number, parse_numbers, per_point

Progress = Callable[[float, str], None]

#: intervalo entre serial polls; não é espera fixa pelo fim da varredura
POLL_INTERVAL = 0.2
#: janela de cada ++read na estratégia *OPC?, para o abortar responder
OPC_WINDOW_MS = 2000

STB_ESB = 0x20


class Aborted(Exception):
    pass


class InstrumentError(Exception):
    def __init__(self, block: str, errors: list[tuple[int, str]]) -> None:
        self.block = block
        self.errors = errors
        seen: dict[tuple[int, str], int] = {}
        for e in errors:
            seen[e] = seen.get(e, 0) + 1
        text = "; ".join(f"{c} {m}" + (f" ×{n}" if n > 1 else "") for (c, m), n in seen.items())
        if any(c == 137 for c, _ in errors):
            text += (" — corrente DC acima da faixa DCRNG: desligue o bias, confira se os eletrodos "
                     "não se tocam e, se a corrente for legítima, suba DCRNG na aba Medida")
        super().__init__(f"{block}: {text}")


@dataclass(slots=True)
class BlockReport:
    name: str
    message: str
    errors: list[tuple[int, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _no_progress(frac: float, msg: str) -> None:
    pass


class HP4294A:
    def __init__(self, session: AR488Session, caps: Capabilities | None = None,
                 timer: SweepTimer | None = None) -> None:
        self.s = session
        self.caps = caps or Capabilities()
        self.timer = timer or SweepTimer()

    # ── básico ──────────────────────────────────────────────────────────
    def idn(self) -> Identity:
        return parse_idn(self.s.query("*IDN?"))

    def drain_errors(self, limit: int = 64) -> list[tuple[int, str]]:
        """OUTPERRO? até voltar 0. Devolve só os erros (código ≠ 0).

        O *CLS não esvazia a fila do 4294A (visto no instrumento real: erros
        -350 antigos sobreviveram), por isso o limite é generoso.
        """
        errs: list[tuple[int, str]] = []
        for _ in range(limit):
            code, msg = parse_error(self.s.query("OUTPERRO?"))
            if code == 0:
                break
            errs.append((code, msg))
        return errs

    def block(self, name: str, message: str) -> BlockReport:
        """Envia um bloco de configuração e confere OUTPERRO?."""
        self.s.write(message)
        rep = BlockReport(name, message, self.drain_errors())
        if rep.errors:
            self.s.traffic.record(NOTE, f"erro no bloco {name}: {rep.errors}")
        return rep

    def apply(self, cfg: MeasurementConfig) -> list[BlockReport]:
        problems = cfg.validate()
        if problems:
            raise ValueError("; ".join(problems))
        self.s.write("HOLD")
        return [self.block(name, msg) for name, msg in cfg.command_blocks()]

    def query_number(self, header: str) -> float:
        return parse_number(self.s.query(f"{header}?"))

    # ── espera ──────────────────────────────────────────────────────────
    def run_and_wait(self, start: str, estimate_s: float, abort: threading.Event,
                     progress: Progress = _no_progress, label: str = "varrendo",
                     max_wait_s: float | None = None) -> float:
        """Dispara ``start`` e espera o instrumento declarar fim de operação.

        Sem teto por padrão: quem decide que acabou é o 4294A, e quem desiste é
        a pessoa, pelo Abortar. A estimativa só alimenta a barra. ``max_wait_s``
        existe para o probe, que precisa detectar uma espera que nunca termina.
        Devolve os segundos até o fim.
        """
        hard = float("inf") if max_wait_s is None else max_wait_s
        t0 = time.monotonic()
        if self.caps.sync == "opc_query":
            self._wait_opc_query(start, estimate_s, hard, abort, progress, label)
        else:
            self._wait_spoll(start, estimate_s, hard, abort, progress, label)
        return time.monotonic() - t0

    def _progress(self, t0: float, est: float, progress: Progress, label: str) -> float:
        el = time.monotonic() - t0
        if el <= est:
            progress(min(el / est, 0.97) if est > 0 else 0.0, f"{label} · {el:.1f} s de ~{est:.0f} s")
        else:
            progress(0.97, f"{label} · {el:.0f} s, passou da estimativa de ~{est:.0f} s — "
                           "o 4294A ainda está medindo (Abortar para parar)")
        return el

    def _wait_spoll(self, start: str, est: float, hard: float, abort: threading.Event,
                    progress: Progress, label: str) -> None:
        self.s.write("*CLS;*ESE 1")
        self.s.write(f"{start};*OPC")
        t0 = time.monotonic()
        while True:
            if abort.is_set():
                self.recover_after_abort()
                raise Aborted(label)
            stb = self.s.spoll()
            if stb is not None and stb & STB_ESB:
                break
            el = self._progress(t0, est, progress, label)
            if el > hard:
                raise TimeoutError(f"{label}: sem fim de operação em {hard:.0f} s")
            # 200 ms no começo, até 1 s em varreduras longas: menos tráfego no log
            abort.wait(min(POLL_INTERVAL + el * 0.02, 1.0))
        self.s.query("*ESR?")  # limpa o OPC
        progress(1.0, f"{label} · concluído em {time.monotonic() - t0:.1f} s")

    def _wait_opc_query(self, start: str, est: float, hard: float, abort: threading.Event,
                        progress: Progress, label: str) -> None:
        self.s.write(f"{start};*OPC?")
        t0 = time.monotonic()
        with self.s.read_timeout(OPC_WINDOW_MS):
            while True:
                try:
                    if self.s.read().strip() in ("1", "+1"):
                        break
                except GpibTimeout:
                    pass
                if abort.is_set():
                    self.recover_after_abort()
                    raise Aborted(label)
                if self._progress(t0, est, progress, label) > hard:
                    raise TimeoutError(f"{label}: *OPC? não voltou em {hard:.0f} s")
        progress(1.0, f"{label} · concluído em {time.monotonic() - t0:.1f} s")

    def recover_after_abort(self) -> None:
        self.s.traffic.record(NOTE, "abortado pelo usuário")
        self.s.device_clear()
        self.s.write("HOLD")
        self.s.write("*CLS")

    # ── aquisição ───────────────────────────────────────────────────────
    def trigger(self, cfg: MeasurementConfig, abort: threading.Event,
                progress: Progress = _no_progress) -> None:
        start = f"NUMG {cfg.averaging_factor}" if cfg.averaging_on else "SING"
        if cfg.trigger_source == "BUS":
            start += ";*TRG"
        label = {"EXT": "aguardando disparo externo", "MAN": "aguardando disparo manual"}.get(
            cfg.trigger_source, "varrendo")
        secs = self.run_and_wait(start, self.timer.estimate(cfg), abort, progress, label)
        if cfg.trigger_source in ("INT", "BUS"):  # com EXT/MAN o tempo inclui esperar o disparo
            self.timer.record(cfg, secs)

    def read_traces(self, cfg: MeasurementConfig) -> SweepResult:
        points = int(self.query_number("POIN"))
        swpt = self.s.query("SWPT?").strip().upper()
        # o eixo é o que o instrumento está varrendo, não o que pedimos
        swpp = self.s.query("SWPP?").strip().upper()
        if swpp != cfg.sweep_param:
            cfg = replace(cfg, sweep_param=swpp)
        if swpp != "FREQ":
            cfg = replace(cfg, cw_freq_hz=self.query_number("CWFREQ"))
        if swpt in ("LIN", "LOG"):
            x = sweep_axis(self.query_number("STAR"), self.query_number("STOP"), points,
                           swpt, self.s.query("SWED?").strip().upper())
        else:
            if not self.caps.sweep_query:
                raise RuntimeError("varredura LIST precisa de uma consulta de eixo; rode o probe")
            x, _ = per_point(self._array(self.caps.sweep_query), points)
        traces = []
        for tr in ("A", "B"):
            self.s.write(f"TRAC {tr}")
            vals, _ = per_point(self._array(self.caps.trace_query), points)
            traces.append(vals)
        self.s.write("TRAC A")
        errs = self.drain_errors()
        if errs:
            raise InstrumentError("leitura", errs)
        return SweepResult(cfg, np.asarray(x, float), traces[0], traces[1],
                           compensation=self.comp_state())

    def _array(self, query: str) -> np.ndarray:
        if self.caps.binary_format:
            self.s.write(self.caps.binary_format)
            try:
                return parse_block(self.s.query_block(query), self.caps.binary_format)
            finally:
                self.s.write(self.caps.ascii_format)
        self.s.write(self.caps.ascii_format)
        return parse_numbers(self.s.query(query))

    def acquire(self, cfg: MeasurementConfig, abort: threading.Event,
                progress: Progress = _no_progress, apply: bool = True) -> tuple[SweepResult, list[BlockReport]]:
        """HOLD → configura → SING/NUMG → espera → lê."""
        reports = self.apply(cfg) if apply else []
        bad = [r for r in reports if not r.ok]
        if bad:
            raise InstrumentError(bad[0].name, bad[0].errors)
        self.trigger(cfg, abort, progress)
        result = self.read_traces(cfg)
        result.idn = self.s.query("*IDN?").strip()
        return result, reports

    # ── compensação ─────────────────────────────────────────────────────
    def comp_state(self) -> CompensationState:
        vals = []
        for h in ("COMSTA", "COMSTB", "COMSTC"):
            try:
                vals.append(parse_bool(self.s.query(f"{h}?")))
            except (GpibTimeout, ValueError):
                vals.append(None)
        return CompensationState(*vals)

    def comp_measure(self, key: str, cfg: MeasurementConfig, abort: threading.Event,
                     progress: Progress = _no_progress) -> list[tuple[int, str]]:
        """COMA / COMB / COMC: uma varredura de padrão, mesma espera da medida."""
        if key not in ("COMA", "COMB", "COMC"):
            raise ValueError(key)
        self.s.write("HOLD")
        self.run_and_wait(key, estimate_sweep_seconds(cfg), abort, progress, f"medindo {key}")
        return self.drain_errors()

    def cal_step(self, command: str, measures: bool, estimate_s: float, abort: threading.Event,
                 progress: Progress = _no_progress) -> tuple[list[tuple[int, str]], float]:
        """Um passo de calibração. Devolve (erros, segundos até o fim declarado).

        Passos de medida (ECALP, COMA, CALA…) usam a mesma espera da varredura.
        Se o instrumento declarar fim rápido demais, quem chama deve desconfiar:
        pode ser que *OPC não acompanhe aquele comando.
        """
        t0 = time.monotonic()
        if measures:
            self.s.write("HOLD")
            self.run_and_wait(command, estimate_s, abort, progress, f"medindo {command}")
            return self.drain_errors(), time.monotonic() - t0
        rep = self.block(command, command)
        return rep.errors, time.monotonic() - t0

    def adapter(self) -> str:
        return self.s.query("E4TP?").strip().upper()

    def user_cal_on(self) -> bool | None:
        try:
            return parse_bool(self.s.query("CALST?"))
        except (GpibTimeout, ValueError):
            return None

    def set_comp(self, open_: bool, short: bool, load: bool) -> BlockReport:
        on = lambda b: "ON" if b else "OFF"  # noqa: E731
        return self.block("compensação", f"COMSTA {on(open_)};COMSTB {on(short)};COMSTC {on(load)}")

    # ── rota alternativa ────────────────────────────────────────────────
    def save_ascii(self, name: str, storage: str = "MEMO", trace: bool = True,
                   data: bool = False, cal: bool = False) -> BlockReport:
        on = lambda b: "ON" if b else "OFF"  # noqa: E731
        safe = "".join(ch for ch in name.upper() if ch.isalnum() or ch == "_")[:8] or "IA4294"
        return self.block("salvar", f'STOD {storage};SAVDTRC {on(trace)};SAVDAT {on(data)};'
                                    f'SAVCAL {on(cal)};SAVDASC "{safe}"')
