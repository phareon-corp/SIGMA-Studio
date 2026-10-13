"""Enlace de bytes com a interface: porta serial real ou simulada.

O enlace não sabe nada de GPIB; ele só move bytes e separa linhas.
"""

from __future__ import annotations

import time
from typing import Protocol


class Link(Protocol):
    #: quanto esperar depois de abrir, porque o Mega reseta por DTR
    reset_delay: float
    #: folga do host além do read_tmo_ms antes de desistir de uma leitura
    read_margin: float
    description: str

    def open(self) -> None: ...
    def close(self) -> None: ...
    @property
    def is_open(self) -> bool: ...
    def write(self, data: bytes) -> None: ...

    def read_line(self, first_timeout: float, gap_timeout: float) -> bytes | None:
        """Lê até LF. ``None`` se nada chegar em ``first_timeout``.

        Depois do primeiro byte, aceita pausas de até ``gap_timeout`` entre
        pedaços: transferências longas pelo AR488 são lentas mas contínuas.
        Se a linha parar sem LF, devolve o que chegou.
        """
        ...

    def read_exact(self, n: int, timeout: float) -> bytes: ...
    def drain(self, quiet: float) -> bytes: ...


class SerialLink:
    """Porta serial real (pyserial), 115200 8N1."""

    reset_delay = 2.0
    read_margin = 1.5

    def __init__(self, port: str, baudrate: int = 115200) -> None:
        self.port = port
        self.baudrate = baudrate
        self.description = port
        self._ser = None
        self._rx = bytearray()

    def open(self) -> None:
        import serial  # importado aqui para os testes não dependerem do pyserial

        # serial_for_url aceita /dev/ttyACM0 e também loop:// (testes)
        self._ser = serial.serial_for_url(
            self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05,
            write_timeout=2.0,
        )
        self._rx.clear()

    def close(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def write(self, data: bytes) -> None:
        assert self._ser is not None
        self._ser.write(data)
        self._ser.flush()

    def _pull(self) -> bytes:
        assert self._ser is not None
        chunk = self._ser.read(self._ser.in_waiting or 1)
        self._rx += chunk
        return chunk

    def read_line(self, first_timeout: float, gap_timeout: float) -> bytes | None:
        deadline = time.monotonic() + first_timeout
        got_any = bool(self._rx)
        while True:
            i = self._rx.find(b"\n")
            if i >= 0:
                line = bytes(self._rx[: i + 1])
                del self._rx[: i + 1]
                return line
            if self._pull():
                got_any = True
                deadline = time.monotonic() + gap_timeout
            elif time.monotonic() > deadline:
                if not got_any:
                    return None
                line = bytes(self._rx)
                self._rx.clear()
                return line

    def read_exact(self, n: int, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        while len(self._rx) < n:
            if self._pull():
                deadline = time.monotonic() + timeout
            elif time.monotonic() > deadline:
                break
        out = bytes(self._rx[:n])
        del self._rx[:n]
        return out

    def drain(self, quiet: float) -> bytes:
        last = time.monotonic()
        while time.monotonic() - last < quiet:
            if self._pull():
                last = time.monotonic()
        out = bytes(self._rx)
        self._rx.clear()
        return out


def _comports() -> list:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return sorted(list_ports.comports(), key=lambda p: p.device)


def list_serial_ports() -> list[str]:
    """``/dev/ttyACM0`` no Linux, ``COM3`` no Windows — quem nomeia é o pyserial."""
    return [p.device for p in _comports()]


#: o Mega 2560 oficial e os clones com CH340/FTDI que aparecem na bancada
_AR488_VIDS = {0x2341, 0x2A03, 0x1A86, 0x0403}
_AR488_WORDS = ("arduino", "mega", "ch340", "usb-serial", "usb serial")


def guess_ar488_port() -> str | None:
    """A porta que mais parece a interface, ou ``None``.

    No Windows não existe ``/dev/ttyACM0`` para chutar: a placa pode ser COM3
    hoje e COM7 amanhã, então a escolha olha VID/USB e descrição.
    """
    ports = _comports()
    for p in ports:
        if getattr(p, "vid", None) in _AR488_VIDS:
            return p.device
    for p in ports:
        text = f"{p.description} {getattr(p, 'manufacturer', '') or ''}".lower()
        if any(w in text for w in _AR488_WORDS):
            return p.device
    return ports[0].device if len(ports) == 1 else None
