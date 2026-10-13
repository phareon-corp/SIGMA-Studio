"""Varredura mais longa que a estimativa: o app espera o 4294A, não desiste."""

import threading

from ia4294.instrument.hp4294a import HP4294A
from ia4294.model.config import MeasurementConfig
from ia4294.model.sweep import SweepTimer, estimate_sweep_seconds, timing_key


def test_sweep_longer_than_estimate_completes(session, sim):
    sim.time_scale = 0.5  # ~0.6 s reais
    drv = HP4294A(session)
    session.write("POIN 101;BWFACT 3")
    msgs = []
    secs = drv.run_and_wait("SING", 0.05, threading.Event(), lambda f, m: msgs.append(m))
    assert secs > 0.4 and not sim.busy
    assert any("passou da estimativa" in m for m in msgs)
    assert msgs[-1].endswith(f"concluído em {secs:.1f} s")


def test_probe_ceiling_still_raises(session, sim):
    sim.time_scale = 50.0
    drv = HP4294A(session)
    session.write("POIN 101")
    try:
        drv.run_and_wait("SING", 0.05, threading.Event(), max_wait_s=0.3)
    except TimeoutError:
        pass
    else:
        raise AssertionError("teto do probe não disparou")


def test_timer_learns_and_persists(tmp_path):
    cfg = MeasurementConfig(sweep_param="DCB", sweep_type="LIN", start=-5, stop=10, points=300,
                            cw_freq_hz=100.0, bw=3)
    t = SweepTimer(tmp_path / "tempos.json")
    assert t.estimate(cfg) == estimate_sweep_seconds(cfg)
    t.record(cfg, 120.3)  # o que o 4294A levou de verdade
    assert abs(t.estimate(cfg) - 120.3) < 1e-9
    again = SweepTimer(tmp_path / "tempos.json")
    assert abs(again.estimate(cfg) - 120.3) < 1e-9
    # mesma combinação com mais pontos: escala por ponto
    assert abs(again.estimate(MeasurementConfig(**{**cfg.to_dict(), "points": 600})) - 240.3) < 1e-6
    # outra década de CWFREQ: chave diferente
    assert timing_key(cfg) != timing_key(MeasurementConfig(**{**cfg.to_dict(), "cw_freq_hz": 1e6}))


def test_trigger_records_real_time(session, sim):
    cfg = MeasurementConfig(points=51, bw=1, sweep_type="LIN", start=1e3, stop=1e6)
    drv = HP4294A(session)
    drv.acquire(cfg, threading.Event())
    assert timing_key(cfg) in drv.timer.sec_per_point
