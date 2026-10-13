"""AR488 falso diante de um 4294A falso, exposto como um ``Link``.

Reproduz o que importa da interface real: banner depois do reset, comandos
``++``, leitura em duas etapas com ``++read eoi`` e timeout de
``++read_tmo_ms``, ``++spoll`` — e o 4294A ignorando em silêncio tudo que não
chega terminado em LF puro (``++eos 2``).
"""

from __future__ import annotations

import time

from .hp4294a import Sim4294A

BANNER = b"AR488 GPIB controller, ver. 0.53.46 (simulador), 05/07/2026\r\n"


class SimulatedAR488:
    def __init__(self, instrument: Sim4294A, address: int = 17) -> None:
        self.inst = instrument
        self.inst_address = address
        self.addr = 10
        self.eos = 0
        self.eoi = 0
        self.read_tmo_ms = 1200
        self.to_host = bytearray()
        self._pending_read: float | None = None  # prazo do ++read em curso

    def boot(self) -> None:
        self.to_host += BANNER

    @property
    def _listening(self) -> bool:
        return self.addr == self.inst_address

    def from_host(self, line: str) -> None:
        line = line.rstrip("\r")
        if line.startswith("++"):
            self._interface(line[2:].strip())
        elif self._listening and self.eos == 2:
            self.inst.receive(line)
        # com eos ≠ 2 o 4294A não reconhece o fim da mensagem: silêncio

    def _reply(self, text: str) -> None:
        self.to_host += text.encode() + b"\r\n"

    def _interface(self, cmd: str) -> None:
        name, _, arg = cmd.partition(" ")
        arg = arg.strip()
        if name in ("addr", "eos", "eoi", "read_tmo_ms", "mode", "auto"):
            if arg:
                v = int(arg)
                if name == "addr":
                    self.addr = v
                elif name == "eos":
                    self.eos = v
                elif name == "eoi":
                    self.eoi = v
                elif name == "read_tmo_ms":
                    self.read_tmo_ms = v
            else:
                self._reply(str({"addr": self.addr, "eos": self.eos, "eoi": self.eoi,
                                 "read_tmo_ms": self.read_tmo_ms}.get(name, 0)))
        elif name == "read":
            if self._listening:
                self._pending_read = time.monotonic() + self.read_tmo_ms / 1000
        elif name == "spoll":
            if self._listening:
                self._reply(str(self.inst.status_byte()))
        elif name == "clr":
            if self._listening:
                self.inst.device_clear()
        elif name == "ver":
            self._reply("AR488 GPIB controller, ver. 0.53.46 (simulador)")
        elif name == "fndl":
            self._reply(str(self.inst_address))
        elif name in ("savecfg", "ifc", "loc", "rst", "default"):
            pass
        else:
            self._reply("Unrecognized command")

    def service(self) -> None:
        self.inst.service()
        if self._pending_read is None:
            return
        if self.inst.output:
            self.to_host += self.inst.output.popleft() + b"\n"
            self._pending_read = None
        elif time.monotonic() > self._pending_read:
            self._pending_read = None  # timeout: o AR488 não devolve nada


class SimLink:
    """Implementa ``Link`` sobre o AR488 simulado."""

    def __init__(self, instrument: Sim4294A | None = None, reset_delay: float = 0.0,
                 address: int = 17) -> None:
        self.instrument = instrument or Sim4294A()
        self.address = address
        self.ar488 = SimulatedAR488(self.instrument, address)
        self.reset_delay = reset_delay
        self.read_margin = 0.1
        self.description = "simulador"
        self._open = False
        self._tx = bytearray()

    def open(self) -> None:
        self._open = True
        self.ar488 = SimulatedAR488(self.instrument, self.address)
        self.ar488.boot()

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def write(self, data: bytes) -> None:
        self._tx += data
        while (i := self._tx.find(b"\n")) >= 0:
            line = self._tx[:i].decode("ascii", "replace")
            del self._tx[: i + 1]
            self.ar488.from_host(line)

    def _wait(self, ready, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            self.ar488.service()
            if ready():
                return True
            if time.monotonic() > deadline:
                return False
            time.sleep(0.002)

    def read_line(self, first_timeout: float, gap_timeout: float) -> bytes | None:
        buf = self.ar488.to_host
        if not self._wait(lambda: b"\n" in buf, first_timeout):
            if not buf:
                return None
            out = bytes(buf)
            buf.clear()
            return out
        i = buf.find(b"\n")
        out = bytes(buf[: i + 1])
        del buf[: i + 1]
        return out

    def read_exact(self, n: int, timeout: float) -> bytes:
        buf = self.ar488.to_host
        self._wait(lambda: len(buf) >= n, timeout)
        out = bytes(buf[:n])
        del buf[:n]
        return out

    def drain(self, quiet: float) -> bytes:
        self.ar488.service()
        out = bytes(self.ar488.to_host)
        self.ar488.to_host.clear()
        return out
