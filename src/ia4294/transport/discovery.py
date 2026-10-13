"""Achar a interface e o instrumento sozinho, no Linux e no Windows.

O palpite por VID/descrição (``guess_ar488_port``) erra quando há dois
conversores USB-serial na mesa, e não diz nada sobre velocidade nem sobre o
endereço GPIB. Aqui a resposta não é palpite: cada porta candidata é **aberta e
interrogada**, e só é aceita quem responder ``++ver`` como AR488.

A ordem é a que gasta menos tempo do usuário:

1. as portas entram ranqueadas — quem tem VID de Arduino/CH340/FTDI primeiro;
2. para cada porta, as velocidades prováveis, começando por 115200 (o padrão
   do firmware). Quem responde ``++ver`` é a interface, e a velocidade que
   funcionou é a velocidade — o enquadramento é sempre 8N1;
3. achada a interface, ``++eos 2`` entra antes de qualquer conversa com o
   instrumento: com CR/CRLF o 4294A ignora calado e a varredura de endereço
   daria "ninguém em casa" em todos os 31;
4. ``++fndl`` lista quem está no barramento; se o firmware não tiver o comando,
   varre os endereços de 1 a 30 perguntando ``*IDN?``;
5. cada endereço achado ganha um ``*IDN?``, e quem disser **4294A** é o alvo.

Nada aqui é Qt e nada abre porta sozinho: quem chama decide quando varrer, e é
a thread da porta (``PortWorker``) que executa.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol

from . import links as _links
from .ar488 import AR488Session, AR488Settings
from .links import Link, SerialLink
from .traffic import NOTE, TrafficLog

#: velocidades que valem tentar, na ordem. 115200 é o padrão do AR488; os
#: outros aparecem em builds antigas e em clones reconfigurados.
BAUDS = (115200, 57600, 9600)

#: faixa de endereços GPIB varrida quando ++fndl não responde
ADDR_RANGE = range(1, 31)

#: o que confirma que o alvo é o analisador
TARGET = "4294A"


class LinkFactory(Protocol):
    def __call__(self, port: str, baudrate: int) -> Link: ...


@dataclass(slots=True)
class Device:
    """Um endereço que respondeu no barramento."""

    address: int
    idn: str = ""

    @property
    def is_target(self) -> bool:
        return TARGET in self.idn.upper()

    def text(self) -> str:
        return f"{self.address} · {self.idn}" if self.idn else str(self.address)


@dataclass(slots=True)
class Discovery:
    """O que a varredura encontrou. ``ok`` quer dizer interface achada."""

    port: str = ""
    baudrate: int = 0
    firmware: str = ""
    framing: str = "8N1"
    devices: list[Device] = field(default_factory=list)
    scanned: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.port)

    @property
    def target(self) -> Device | None:
        """O 4294A, se ele estiver lá; senão o primeiro que respondeu."""
        for d in self.devices:
            if d.is_target:
                return d
        return self.devices[0] if self.devices else None

    def summary(self) -> str:
        if not self.ok:
            return "nenhuma interface AR488 encontrada"
        alvo = self.target
        onde = f"{self.port} · {self.baudrate} 8N1"
        if alvo is None:
            return f"{onde} · interface ok, nenhum instrumento no barramento"
        marca = "4294A" if alvo.is_target else "instrumento"
        return f"{onde} · {marca} no endereço {alvo.address}"


def rank_ports(deep: bool = False) -> list[str]:
    """Portas do sistema, as mais prováveis primeiro.

    Serve tanto para ``/dev/ttyACM0`` quanto para ``COM7``: quem nomeia é o
    pyserial, e o critério é VID/descrição, não o nome.

    Sem ``deep``, portas **sem VID USB** ficam de fora. Elas são as seriais do
    chipset (``/dev/ttyS0``…``/dev/ttyS31`` numa placa comum, ``COM1`` numa
    máquina com porta de verdade): a interface é USB e nunca está ali, e tentar
    as 32 a três velocidades, com 2 s de reset cada, custaria minutos de
    espera para dar em nada.
    """
    ports = _links._comports()
    with_vid, with_word, usb, rest = [], [], [], []
    for p in ports:
        text = f"{p.description} {getattr(p, 'manufacturer', '') or ''}".lower()
        vid = getattr(p, "vid", None)
        if vid in _links._AR488_VIDS:
            with_vid.append(p.device)
        elif any(w in text for w in _links._AR488_WORDS):
            with_word.append(p.device)
        elif vid is not None:
            usb.append(p.device)
        else:
            rest.append(p.device)
    return with_vid + with_word + usb + (rest if deep else [])


def _is_ar488(text: str) -> bool:
    return "AR488" in text.upper()


def identify(link: Link, traffic: TrafficLog, settle: float = 0.25) -> str | None:
    """``++ver`` numa porta já aberta. Devolve o firmware, ou ``None``.

    Pergunta duas vezes: logo depois do reset por DTR a placa pode engolir a
    primeira linha, e um "não" barato aqui custaria a porta certa.
    """
    for tentativa in (1, 2):
        text = ""
        try:
            link.write(b"++ver\n")
            raw = link.read_line(1.2, 0.3)
            text = (raw or b"").replace(b"\x00", b"").decode("ascii", "replace").strip()
        except Exception as exc:  # noqa: BLE001 — porta ocupada, sumiu, baud errado
            traffic.record(NOTE, f"++ver falhou: {exc!r}")
            return None
        if _is_ar488(text):
            return text
        if tentativa == 1:
            time.sleep(settle)
    return None


def _ask_idn(session: AR488Session, address: int, timeout_ms: int) -> str:
    """``*IDN?`` num endereço, sem deixar exceção escapar."""
    session.raw(f"++addr {address}")
    with session.read_timeout(timeout_ms):
        try:
            return session.query("*IDN?").strip()
        except Exception:  # noqa: BLE001 — endereço vazio é o caso comum
            return ""


def find_devices(session: AR488Session, progress: Callable[[float, str], None] | None = None,
                 scan_timeout_ms: int = 400) -> tuple[list[Device], list[str]]:
    """Quem está no barramento. Tenta ``++fndl``; se não houver, varre."""
    notes: list[str] = []
    say = progress or (lambda _f, _m: None)

    say(0.55, "++fndl")
    try:
        enderecos = session.find_listeners()
    except Exception as exc:  # noqa: BLE001
        notes.append(f"++fndl falhou ({exc!r}); varrendo endereços")
        enderecos = []
    if not enderecos:
        if not notes:
            notes.append("++fndl não listou ninguém; varrendo endereços 1–30")
        achados = []
        total = len(ADDR_RANGE)
        for i, addr in enumerate(ADDR_RANGE):
            say(0.55 + 0.4 * i / total, f"endereço {addr}")
            if idn := _ask_idn(session, addr, scan_timeout_ms):
                achados.append(Device(addr, idn))
        return achados, notes

    devices: list[Device] = []
    for i, addr in enumerate(enderecos):
        say(0.8 + 0.15 * i / max(len(enderecos), 1), f"*IDN? no endereço {addr}")
        devices.append(Device(addr, _ask_idn(session, addr, max(scan_timeout_ms, 1500))))
    return devices, notes


def discover(ports: Iterable[str] | None = None, bauds: Iterable[int] = BAUDS,
             link_factory: LinkFactory | None = None, traffic: TrafficLog | None = None,
             progress: Callable[[float, str], None] | None = None, read_tmo_ms: int = 3000,
             should_abort: Callable[[], bool] | None = None, deep: bool = False,
             scan_timeout_ms: int = 400) -> Discovery:
    """Varre portas e velocidades até achar a interface, e então o instrumento.

    ``link_factory`` existe para os testes trocarem a porta real pelo
    simulador; em produção é ``SerialLink``.
    """
    traffic = traffic or TrafficLog()
    factory: LinkFactory = link_factory or (lambda port, baudrate: SerialLink(port, baudrate))
    say = progress or (lambda _f, _m: None)
    aborted = should_abort or (lambda: False)

    lista = list(ports) if ports is not None else rank_ports(deep)
    found = Discovery(scanned=list(lista))
    if not lista:
        found.notes.append("nenhuma porta USB-serial no sistema" if not deep
                           else "nenhuma porta serial no sistema")
        return found

    tentativas = [(p, b) for p in lista for b in bauds]
    for i, (port, baud) in enumerate(tentativas):
        if aborted():
            found.notes.append("varredura abortada")
            return found
        say(0.5 * i / len(tentativas), f"{port} a {baud}")
        link = factory(port, baud)
        try:
            link.open()
        except Exception as exc:  # noqa: BLE001 — porta ocupada ou sem permissão
            found.notes.append(f"{port}: {exc}")
            continue
        try:
            if link.reset_delay:
                time.sleep(link.reset_delay)
            link.drain(quiet=0.3)  # banner do boot
            firmware = identify(link, traffic)
            if firmware is None:
                continue
            found.port, found.baudrate, found.firmware = port, baud, firmware
            say(0.5, f"AR488 em {port}")
        finally:
            if not found.ok:
                link.close()
        break

    if not found.ok:
        found.notes.append("nenhuma porta respondeu ++ver como AR488")
        return found

    # a mesma porta, agora como sessão: ++eos 2 antes de falar com o instrumento
    session = AR488Session(link, AR488Settings(read_tmo_ms=read_tmo_ms), traffic)
    try:
        for cmd in ("++mode 1", "++auto 0", "++eos 2", "++eoi 1", f"++read_tmo_ms {read_tmo_ms}"):
            session.raw(cmd)
        session.version = found.firmware
        devices, notes = find_devices(session, progress, scan_timeout_ms)
        found.devices, found.notes = devices, found.notes + notes
        if not devices:
            found.notes.append("interface ok, mas ninguém respondeu no barramento — "
                               "confira o cabo GPIB e se o 4294A está ligado")
        elif found.target is not None and not found.target.is_target:
            found.notes.append(f"respondeu {found.target.idn!r}, que não é um {TARGET}")
    finally:
        link.close()
    say(1.0, found.summary())
    return found
