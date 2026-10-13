"""Varredura de bias DC (C-V) e de nível do oscilador, sem hardware."""

import json
import threading

import numpy as np
import pytest

from ia4294 import paths
from ia4294.instrument.hp4294a import HP4294A
from ia4294.model import dielectric, export
from ia4294.model.config import MeasurementConfig
from ia4294.model.sweep import estimate_sweep_seconds


def cv(**kw) -> MeasurementConfig:
    base = dict(meas="CPD", sweep_param="DCB", sweep_type="LIN", start=0.0, stop=40.0, points=41,
                cw_freq_hz=1e6, bw=2)
    base.update(kw)
    return MeasurementConfig(**base)


# ── configuração ────────────────────────────────────────────────────────
def test_dcb_commands_send_swpp_and_no_fixed_level():
    blocks = dict(cv(dc_bias_level=5.0, dc_bias_on=False).command_blocks())
    assert blocks["varredura"].startswith("SWPP DCB;SWPT LIN;STAR 0;STOP 40;")
    fonte = blocks["fonte"]
    assert "DCO ON" in fonte and "DCMOD VOLT" in fonte and "CWFREQ 1e+06" in fonte
    assert "DCV" not in fonte and "DCI" not in fonte  # quem manda são STAR/STOP
    names = [n for n, _ in cv().command_blocks()]
    assert names.index("fonte") < names.index("varredura")  # DCMOD antes de STAR/STOP


def test_olev_does_not_send_powe():
    c = MeasurementConfig(sweep_param="OLEV", sweep_type="LIN", start=0.01, stop=0.5)
    fonte = dict(c.command_blocks())["fonte"]
    assert "POWE" not in fonte and "DCO OFF" in fonte
    assert c.validate() == []


@pytest.mark.parametrize("param", ["DCB", "OLEV"])
@pytest.mark.parametrize("swpt", ["LOG", "LIST"])
def test_log_and_list_rejected_outside_freq(param, swpt):
    start, stop = (0.0, 10.0) if param == "DCB" else (0.01, 0.5)
    c = MeasurementConfig(sweep_param=param, sweep_type=swpt, start=start, stop=stop)
    assert any("só existe varrendo frequência" in e for e in c.validate())
    assert MeasurementConfig(sweep_type=swpt, start=1e3, stop=1e6).validate() == []


@pytest.mark.parametrize("kw,ok", [
    (dict(start=-40.0, stop=40.0), True),
    (dict(start=0.0, stop=41.0), False),
    (dict(dc_bias_mode="CURR", start=0.0, stop=0.1), True),
    (dict(dc_bias_mode="CURR", start=0.0, stop=0.2), False),
    (dict(cw_freq_hz=20.0), False),
])
def test_dcb_ranges(kw, ok):
    assert (cv(**kw).validate() == []) is ok


def test_olev_uses_oscillator_limits():
    assert MeasurementConfig(sweep_param="OLEV", sweep_type="LIN", start=0.001, stop=0.5).validate()
    assert MeasurementConfig(sweep_param="OLEV", sweep_type="LIN", osc_mode="CURR",
                             start=1e-3, stop=20e-3).validate() == []


def test_old_profile_with_start_hz_still_loads(tmp_path):
    p = tmp_path / "antigo.json"
    p.write_text(json.dumps({"ia4294_perfil": 1, "meas": "CPD", "sweep_type": "LOG",
                             "start_hz": 2e3, "stop_hz": 5e6, "points": 101}))
    c = MeasurementConfig.load(p)
    assert (c.sweep_param, c.start, c.stop, c.points) == ("FREQ", 2e3, 5e6, 101)
    assert c.validate() == []


def test_estimate_uses_cwfreq_outside_freq():
    slow = estimate_sweep_seconds(cv(cw_freq_hz=100.0))
    fast = estimate_sweep_seconds(cv(cw_freq_hz=1e6))
    assert slow > fast  # CWFREQ de 100 Hz entra na heurística de período longo
    # em DCB, STAR = 0 V não é "frequência baixa"
    assert estimate_sweep_seconds(cv(start=0.0)) == fast


# ── ciclo completo no simulador ─────────────────────────────────────────
def test_cv_cycle_configure_trigger_read_export(session, sim):
    cfg = cv()
    drv = HP4294A(session)
    result, reports = drv.acquire(cfg, threading.Event())
    assert all(r.ok for r in reports), [r.errors for r in reports if not r.ok]
    assert sim.state["SWPP"] == "DCB" and sim.state["DCO"] is True and sim.state["DCMOD"] == "VOLT"

    # eixo em volts, calculado de STAR/STOP/POIN
    assert result.axis.param == "DCB" and result.axis.unit == "V"
    assert np.allclose(result.x, np.linspace(0, 40, 41))
    assert np.allclose(result.frequency, 1e6)
    # C-V plausível: Cp cai com o bias, monotônico de 0 a 40 V
    cp = result.trace_a
    assert cp[0] > cp[-1] * 1.3
    assert np.all(np.diff(cp) < cp[0] * 0.01)

    out = export.export_run(result, paths.data_dir(), ("csv", "parquet"))
    df, meta = export.read_csv(out[0])
    assert list(df.columns) == ["dc_bias_V", "Cp_F", "D"]
    assert np.allclose(df["dc_bias_V"], np.linspace(0, 40, 41))
    assert meta["SWEEP TYPE"] == "LIN DC BIAS VOLT"
    assert meta["FIXED FREQUENCY (CWFREQ)"] == "1e+06 Hz"
    assert meta["DC BIAS"] == "SWEPT 0 to 40 Volt"
    pq_df, pq_meta = export.read_parquet(out[1])
    assert list(pq_df.columns) == list(df.columns) and pq_meta == meta


def test_cv_dielectric_against_bias(session, sim):
    result, _ = HP4294A(session).acquire(cv(), threading.Event())
    d = dielectric.compute(result, dielectric.Geometry(1e-3, 38e-3))
    assert d.axis.param == "DCB" and d.cw_freq_hz == 1e6
    assert np.allclose(d.x, np.linspace(0, 40, 41))
    assert d.eps_real[0] > d.eps_real[-1]
    out = export.export_run(result, paths.data_dir(), ("csv",), dielectric=d)
    df, meta = export.read_csv(out[0])
    assert list(df.columns)[:1] == ["dc_bias_V"] and "eps_r_real" in df.columns
    assert meta["FIXED FREQUENCY (CWFREQ)"] == "1e+06 Hz"


def test_sim_refuses_log_outside_freq(session):
    drv = HP4294A(session)
    rep = drv.block("x", "SWPP DCB;SWPT LOG")
    assert [c for c, _ in rep.errors] == [-221]
    assert session.query("SWPT?") == "LIN"


def test_current_bias_sweep(session, sim):
    result, reports = HP4294A(session).acquire(
        cv(dc_bias_mode="CURR", start=0.0, stop=0.05, points=11), threading.Event())
    assert all(r.ok for r in reports)
    assert result.axis.column == "dc_bias_A" and sim.state["DCMOD"] == "CURR"


def test_dcrng_sent_and_reset_without_bias():
    assert "DCRNG M10" in dict(cv(dc_range="M10").command_blocks())["fonte"]
    # sem bias, o manual manda 1 mA, qualquer que seja a escolha
    off = MeasurementConfig(dc_range="M100")
    assert "DCRNG M1;" in dict(off.command_blocks())["fonte"]
    assert cv(dc_range="M5").validate()


def test_overload_message_is_deduplicated_and_explained():
    from ia4294.instrument.hp4294a import InstrumentError
    e = InstrumentError("leitura", [(137, "DCBIAS OVERLOAD")] * 9 + [(-350, "Queue overflow")])
    assert "137 DCBIAS OVERLOAD ×9" in str(e) and "suba DCRNG" in str(e)


def test_dcrng_accepted_by_simulator(session, sim):
    _, reports = HP4294A(session).acquire(cv(dc_range="M10", points=11), threading.Event())
    assert all(r.ok for r in reports) and sim.state["DCRNG"] == "M10"
