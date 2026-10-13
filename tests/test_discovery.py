"""Descoberta automática: achar a porta, a velocidade e o endereço sozinho.

Cada porta falsa é um ``Link`` — a descoberta nunca sabe se do outro lado há
um Mega 2560 ou um mouse, ela só pergunta ``++ver`` e escuta.
"""

from __future__ import annotations

import pytest

from ia4294.sim.ar488 import SimLink
from ia4294.sim.hp4294a import Sim4294A
from ia4294.transport import discovery, links
from ia4294.transport.discovery import Device, Discovery, discover, rank_ports


class Mudo:
    """Uma porta que abre e nunca responde: conversor USB-serial de outra coisa."""

    reset_delay = 0.0
    read_margin = 0.1

    def __init__(self, port: str = "/dev/ttyUSB9", baudrate: int = 115200) -> None:
        self.description = port
        self.baudrate = baudrate
        self._open = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def write(self, data: bytes) -> None:
        pass

    def read_line(self, first_timeout: float, gap_timeout: float):
        return None

    def read_exact(self, n: int, timeout: float) -> bytes:
        return b""

    def drain(self, quiet: float) -> bytes:
        return b""


class Ruido(Mudo):
    """Velocidade errada: chegam bytes, mas não são texto nenhum."""

    def read_line(self, first_timeout: float, gap_timeout: float):
        return b"\xfe\x00\xff\x9c\n"


class Trancada(Mudo):
    """A porta existe mas é de outro processo (ou falta dialout)."""

    def open(self) -> None:
        raise PermissionError("[Errno 13] could not open port")


def fabrica(mapa: dict[str, object]):
    """Porta → enlace; o que não estiver no mapa é uma porta muda."""

    def factory(port: str, baudrate: int):
        return mapa.get(port) or Mudo(port, baudrate)

    return factory


@pytest.fixture
def ar488():
    """Um AR488 de verdade (simulado) com o 4294A no endereço 19."""
    return SimLink(Sim4294A(time_scale=0.002, seed=3), reset_delay=0.0, address=19)


def test_acha_porta_velocidade_e_endereco(ar488):
    found = discover(ports=["/dev/ttyUSB0", "/dev/ttyACM0"],
                     link_factory=fabrica({"/dev/ttyACM0": ar488}))
    assert found.ok
    assert found.port == "/dev/ttyACM0"
    assert found.baudrate == 115200 and found.framing == "8N1"
    assert "AR488" in found.firmware
    alvo = found.target
    assert alvo is not None and alvo.address == 19
    assert alvo.is_target and "4294A" in alvo.idn
    assert "endereço 19" in found.summary()


def test_porta_muda_nao_vira_interface():
    found = discover(ports=["/dev/ttyUSB0"], link_factory=fabrica({}))
    assert not found.ok
    assert found.target is None
    assert "++ver" in found.notes[-1]


def test_ruido_de_baud_errado_nao_engana():
    found = discover(ports=["/dev/ttyUSB0"], link_factory=fabrica({"/dev/ttyUSB0": Ruido()}))
    assert not found.ok


def test_porta_trancada_vira_nota_e_a_varredura_segue(ar488):
    found = discover(ports=["/dev/ttyUSB0", "/dev/ttyACM0"],
                     link_factory=fabrica({"/dev/ttyUSB0": Trancada(), "/dev/ttyACM0": ar488}))
    assert found.ok and found.port == "/dev/ttyACM0"
    assert any("Errno 13" in n for n in found.notes)


def test_varre_enderecos_quando_fndl_nao_responde(monkeypatch):
    """Firmware sem ++fndl: o endereço tem de sair da varredura, não de um chute."""
    link = SimLink(Sim4294A(time_scale=0.002, seed=3), reset_delay=0.0, address=12)
    real = link.ar488.__class__._interface

    def sem_fndl(self, cmd: str) -> None:
        if cmd.strip() == "fndl":
            self._reply("Unrecognized command")
            return
        real(self, cmd)

    monkeypatch.setattr(link.ar488.__class__, "_interface", sem_fndl)
    found = discover(ports=["/dev/ttyACM0"], link_factory=fabrica({"/dev/ttyACM0": link}),
                     scan_timeout_ms=60)
    assert found.ok
    alvo = found.target
    assert alvo is not None and alvo.address == 12 and alvo.is_target
    assert any("varrendo" in n for n in found.notes)


def test_interface_sem_instrumento_no_barramento(monkeypatch):
    """O cabo GPIB solto não pode virar "não achei a interface"."""
    link = SimLink(Sim4294A(time_scale=0.002, seed=3), reset_delay=0.0, address=19)
    link.ar488 = None  # recriado no open()
    found_ports = {"/dev/ttyACM0": link}

    def sem_barramento(self, cmd: str) -> None:
        name = cmd.split()[0] if cmd else ""
        if name == "ver":
            self._reply("AR488 GPIB controller, ver. 0.53.46 (simulador)")
        elif name == "fndl":
            self._reply("")
        # qualquer outra coisa: silêncio, como barramento vazio

    from ia4294.sim.ar488 import SimulatedAR488

    monkeypatch.setattr(SimulatedAR488, "_interface", sem_barramento)
    found = discover(ports=["/dev/ttyACM0"], link_factory=fabrica(found_ports), scan_timeout_ms=30)
    assert found.ok and found.devices == []
    assert "cabo GPIB" in found.notes[-1]


def test_sem_portas_no_sistema():
    found = discover(ports=[], link_factory=fabrica({}))
    assert not found.ok and "nenhuma porta" in found.notes[-1]


def test_abortar_interrompe_a_varredura(ar488):
    found = discover(ports=["/dev/ttyACM0"], link_factory=fabrica({"/dev/ttyACM0": ar488}),
                     should_abort=lambda: True)
    assert not found.ok and "abortada" in found.notes[-1]


# ── ranqueamento: a porta do chipset não entra na fila ──────────────────────
class _Porta:
    def __init__(self, device, vid=None, description="", manufacturer=""):
        self.device, self.vid = device, vid
        self.description, self.manufacturer = description, manufacturer


def test_ranking_poe_o_arduino_na_frente_e_deixa_ttyS_de_fora(monkeypatch):
    monkeypatch.setattr(links, "_comports", lambda: [
        _Porta("/dev/ttyS0"),
        _Porta("/dev/ttyUSB1", vid=0x10C4, description="CP2102"),
        _Porta("/dev/ttyACM0", vid=0x2341, description="Arduino Mega 2560"),
    ])
    assert rank_ports() == ["/dev/ttyACM0", "/dev/ttyUSB1"]
    assert rank_ports(deep=True) == ["/dev/ttyACM0", "/dev/ttyUSB1", "/dev/ttyS0"]


def test_resumo_sem_nada():
    assert Discovery().summary() == "nenhuma interface AR488 encontrada"
    d = Discovery(port="COM7", baudrate=115200, devices=[Device(19, "HEWLETT-PACKARD,4294A,X,REV1.11")])
    assert d.summary() == "COM7 · 115200 8N1 · 4294A no endereço 19"
