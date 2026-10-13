"""SerialLink sobre o loopback do pyserial (loop://): sem hardware."""

import pytest

pytest.importorskip("serial")

from ia4294.transport.ar488 import _clean  # noqa: E402
from ia4294.transport.links import SerialLink  # noqa: E402


@pytest.fixture
def link():
    lk = SerialLink("loop://")
    lk.open()
    yield lk
    lk.close()


def test_lines_and_partial(link):
    link.write(b"+1.0E+003,+2.0E+003\n0,\"No error\"\r\n")
    assert link.read_line(1.0, 0.2) == b"+1.0E+003,+2.0E+003\n"
    assert _clean(link.read_line(1.0, 0.2)) == '0,"No error"'
    assert link.read_line(0.1, 0.1) is None  # nada chegou: timeout
    link.write(b"sem LF")
    assert link.read_line(0.5, 0.1) == b"sem LF"  # EOI sem LF


def test_nulls_are_noise(link):
    link.write(b"HEWLETT\x00-PACKARD\n")
    assert _clean(link.read_line(1.0, 0.2)) == "HEWLETT-PACKARD"


def test_binary_exact_and_drain(link):
    body = bytes(range(256)) * 2  # contém \n e \x00, que não podem ser tocados
    link.write(b"#6000512" + body + b"\n")
    assert link.read_exact(8, 1.0) == b"#6000512"
    assert link.read_exact(512, 1.0) == body
    link.write(b"AR488 banner\r\n")
    assert link.drain(0.1) == b"\nAR488 banner\r\n"


# ── achar a interface: no Windows não há /dev/ttyACM0 para chutar ───────────
class _Port:
    def __init__(self, device, vid=None, description="", manufacturer=""):
        self.device, self.vid = device, vid
        self.description, self.manufacturer = description, manufacturer


def _ports(monkeypatch, *ports):
    from ia4294.transport import links

    monkeypatch.setattr(links, "_comports", lambda: list(ports))


def test_acha_a_placa_pelo_vid(monkeypatch):
    from ia4294.transport.links import guess_ar488_port

    _ports(monkeypatch, _Port("COM1", description="Porta de Comunicação"),
           _Port("COM7", vid=0x2341, description="Arduino Mega 2560"))
    assert guess_ar488_port() == "COM7"


def test_acha_o_clone_pela_descricao(monkeypatch):
    from ia4294.transport.links import guess_ar488_port

    _ports(monkeypatch, _Port("COM1", description="Porta de Comunicação"),
           _Port("COM4", vid=0xDEAD, description="USB-SERIAL CH340"))
    assert guess_ar488_port() == "COM4"


def test_sem_pista_so_chuta_se_a_porta_for_unica(monkeypatch):
    from ia4294.transport.links import guess_ar488_port

    _ports(monkeypatch, _Port("COM1", description="Bluetooth"), _Port("COM2", description="Bluetooth"))
    assert guess_ar488_port() is None
    _ports(monkeypatch, _Port("/dev/ttyUSB0", description="?"))
    assert guess_ar488_port() == "/dev/ttyUSB0"
    _ports(monkeypatch)
    assert guess_ar488_port() is None
