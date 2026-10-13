"""Sessão com a interface AR488 (protocolo Prologix-like).

Regras que vêm do hardware (ver ar488-mega2560-4294a/README.md):

* a placa reseta por DTR ao abrir a porta: espera ~2 s e descarta o banner;
* ``++eos 2`` (LF puro) é obrigatório — com CR ou CRLF o 4294A ignora o
  comando em silêncio, sem erro, só timeout;
* toda leitura é em duas etapas: escreve o comando, depois ``++read eoi``.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from .links import Link
from .traffic import NOTE, RECV, SEND, TrafficLog

#: o AR488 aceita read_tmo_ms até 32000
MAX_READ_TMO_MS = 32000


class GpibError(Exception):
    pass


class GpibTimeout(GpibError):
    """O instrumento não respondeu dentro do read_tmo_ms."""


@dataclass(slots=True)
class AR488Settings:
    address: int = 17
    read_tmo_ms: int = 3000
    eos: int = 2  # LF — único valor que o 4294A aceita
    eoi: int = 1


def _clean(raw: bytes) -> str:
    # Nulos esparsos na serial são ruído de framing, não dado (README §5).
    return raw.replace(b"\x00", b"").decode("ascii", "replace").strip("\r\n")


class AR488Session:
    def __init__(self, link: Link, settings: AR488Settings | None = None,
                 traffic: TrafficLog | None = None) -> None:
        self.link = link
        self.settings = settings or AR488Settings()
        self.traffic = traffic or TrafficLog()
        self.banner = ""
        self.version = ""
        self._read_tmo_ms = self.settings.read_tmo_ms

    # ── abertura ────────────────────────────────────────────────────────
    def open(self) -> None:
        s = self.settings
        self.traffic.record(NOTE, f"abrindo {self.link.description}")
        self.link.open()
        if self.link.reset_delay:
            self.traffic.record(NOTE, f"aguardando reset por DTR ({self.link.reset_delay:.1f} s)")
            time.sleep(self.link.reset_delay)
        banner = _clean(self.link.drain(quiet=0.3)).strip()
        self.banner = banner
        if banner:
            self.traffic.record(RECV, f"[banner descartado] {banner}")
        for cmd in ("++mode 1", "++auto 0", f"++addr {s.address}", f"++eos {s.eos}",
                    f"++eoi {s.eoi}", f"++read_tmo_ms {s.read_tmo_ms}"):
            self.raw(cmd)
        self._read_tmo_ms = s.read_tmo_ms
        self.version = self.interface_query("++ver") or ""

    def close(self) -> None:
        if self.link.is_open:
            self.link.close()
            self.traffic.record(NOTE, "porta fechada")

    @property
    def is_open(self) -> bool:
        return self.link.is_open

    # ── primitivas ──────────────────────────────────────────────────────
    def raw(self, line: str) -> None:
        self.traffic.record(SEND, line)
        self.link.write(line.encode("ascii") + b"\n")

    def interface_query(self, cmd: str, timeout: float = 1.0) -> str | None:
        """Comando ``++`` que a própria interface responde."""
        self.raw(cmd)
        raw = self.link.read_line(timeout, 0.3)
        if raw is None:
            return None
        text = _clean(raw)
        self.traffic.record(RECV, text)
        return text

    def write(self, cmd: str) -> None:
        if cmd.startswith("++"):
            raise ValueError("use raw() para comandos da interface")
        self.raw(cmd)

    def read(self) -> str:
        """``++read eoi`` e uma linha de volta."""
        self.raw("++read eoi")
        raw = self.link.read_line(self._read_tmo_ms / 1000 + self.link.read_margin, 2.0)
        if raw is None:
            self.traffic.record(NOTE, f"timeout de leitura ({self._read_tmo_ms} ms)")
            raise GpibTimeout(f"sem resposta em {self._read_tmo_ms} ms")
        text = _clean(raw)
        self.traffic.record(RECV, text if len(text) < 400 else f"{text[:400]}… [{len(text)} car.]")
        return text

    def query(self, cmd: str) -> str:
        self.write(cmd)
        return self.read()

    def read_block(self) -> bytes:
        """Bloco binário IEEE 488.2 definido: ``#<n><len><dados>``."""
        self.raw("++read eoi")
        tmo = self._read_tmo_ms / 1000 + self.link.read_margin
        head = self.link.read_exact(2, tmo)
        if len(head) < 2:
            raise GpibTimeout("sem cabeçalho de bloco")
        if head[:1] != b"#" or not head[1:2].isdigit():
            rest = self.link.read_line(0.5, 0.5) or b""
            text = _clean(head + rest)
            self.traffic.record(RECV, text[:400])
            raise GpibError(f"resposta não é bloco binário: {text[:40]!r}")
        ndig = int(head[1:2])
        length = int(self.link.read_exact(ndig, tmo))
        data = self.link.read_exact(length, max(tmo, 5.0))
        self.link.read_line(0.2, 0.2)  # LF final, se houver
        self.traffic.record(RECV, f"#{ndig}{length:0{ndig}d}<{len(data)} bytes binários>")
        if len(data) != length:
            raise GpibError(f"bloco truncado: {len(data)}/{length} bytes")
        return data

    def query_block(self, cmd: str) -> bytes:
        self.write(cmd)
        return self.read_block()

    def spoll(self) -> int | None:
        text = self.interface_query("++spoll", timeout=self._read_tmo_ms / 1000 + self.link.read_margin)
        try:
            return int(text) if text else None
        except ValueError:
            return None

    def find_listeners(self) -> list[int]:
        """``++fndl``: endereços que respondem no barramento."""
        text = self.interface_query("++fndl", timeout=5.0) or ""
        return [int(t) for t in text.replace(",", " ").split() if t.isdigit()]

    def device_clear(self) -> None:
        self.raw("++clr")

    def set_read_timeout(self, ms: int) -> None:
        ms = max(1, min(int(ms), MAX_READ_TMO_MS))
        if ms != self._read_tmo_ms:
            self.raw(f"++read_tmo_ms {ms}")
            self._read_tmo_ms = ms

    @property
    def read_timeout_ms(self) -> int:
        return self._read_tmo_ms

    @contextmanager
    def read_timeout(self, ms: int) -> Iterator[None]:
        old = self._read_tmo_ms
        self.set_read_timeout(ms)
        try:
            yield
        finally:
            self.set_read_timeout(old)
