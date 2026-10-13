from __future__ import annotations

import pytest

from ia4294.sim.ar488 import SimLink
from ia4294.sim.hp4294a import Sim4294A
from ia4294.transport.ar488 import AR488Session, AR488Settings
from ia4294.transport.traffic import TrafficLog


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("IA4294_HOME", str(tmp_path / "home"))


@pytest.fixture
def sim() -> Sim4294A:
    return Sim4294A(time_scale=0.002, seed=7)


@pytest.fixture
def session(sim, tmp_path) -> AR488Session:
    s = AR488Session(SimLink(sim), AR488Settings(read_tmo_ms=300), TrafficLog(tmp_path / "trafego.log"))
    s.open()
    yield s
    s.close()
