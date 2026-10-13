import threading

import numpy as np
import pytest

from ia4294.instrument.capabilities import Capabilities
from ia4294.instrument.hp4294a import HP4294A, Aborted
from ia4294.instrument.parser import parse_savdasc
from ia4294.sim.ar488 import SimLink
from ia4294.sim.hp4294a import Sim4294A
from ia4294.transport.ar488 import AR488Session, AR488Settings, GpibTimeout


def test_banner_discarded_and_version(session):
    assert "AR488" in session.banner
    assert "0.53.46" in session.version


def test_idn(session):
    assert session.query("*IDN?").startswith("HEWLETT-PACKARD,4294A")


@pytest.mark.parametrize("eos", [0, 1, 3])
def test_wrong_eos_is_silent(sim, eos):
    s = AR488Session(SimLink(sim), AR488Settings(read_tmo_ms=100, eos=eos))
    s.open()
    with pytest.raises(GpibTimeout):
        s.query("*IDN?")


def test_wrong_address_times_out(sim):
    s = AR488Session(SimLink(sim), AR488Settings(read_tmo_ms=100, address=5))
    s.open()
    with pytest.raises(GpibTimeout):
        s.query("*IDN?")


def test_unknown_command_goes_to_error_queue(session):
    drv = HP4294A(session)
    rep = drv.block("x", "FOOBAR 1;POIN 99999;MEAS XYZ")
    assert [c for c, _ in rep.errors] == [-113, -222, -141]
    assert drv.drain_errors() == []


def test_query_of_unknown_is_timeout(session):
    with pytest.raises(GpibTimeout):
        session.query("OUTPSWPRMP?")


def test_state_roundtrip(session):
    session.write("STAR 1E3;STOP 2E6;POIN 51;MEAS CPD;DCO ON")
    assert float(session.query("STAR?")) == 1e3
    assert session.query("POIN?") == "51"
    assert session.query("MEAS?") == "CPD"
    assert session.query("DCO?") == "1"


def test_comp_on_requires_measurement(session, sim):
    drv = HP4294A(session)
    rep = drv.block("c", "COMSTA ON")
    assert rep.errors and rep.errors[0][0] == 11
    drv.comp_measure("COMA", _cfg(), threading.Event())
    assert drv.block("c", "COMSTA ON").ok
    assert drv.comp_state().open is True


@pytest.mark.parametrize("sync", ["spoll", "opc_query"])
def test_sweep_wait_strategies(session, sim, sync):
    sim.time_scale = 0.05  # ~0.15 s
    drv = HP4294A(session, Capabilities(sync=sync))
    session.write("POIN 101;BWFACT 3")
    seen = []
    n0 = sim.sweep_count
    drv.run_and_wait("SING", 0.2, threading.Event(), lambda f, m: seen.append(f))
    assert sim.sweep_count == n0 + 1 and not sim.busy
    assert seen[-1] == 1.0


def test_abort_stops_long_sweep(session, sim):
    sim.time_scale = 50.0  # varredura de minutos
    drv = HP4294A(session)
    session.write("POIN 801;BWFACT 5")
    abort = threading.Event()
    threading.Timer(0.3, abort.set).start()
    with pytest.raises(Aborted):
        drv.run_and_wait("SING", 60, abort)
    assert not sim.busy


def test_numg_runs_n_sweeps(session, sim):
    drv = HP4294A(session)
    n0 = sim.sweep_count
    drv.run_and_wait("NUMG 4", 0.1, threading.Event())
    assert sim.sweep_count == n0 + 4


def test_binary_transfer(session):
    session.write("POIN 11;FORM3")
    from ia4294.instrument.parser import parse_block
    v = parse_block(session.query_block("OUTPSWPRM?"), "FORM3")
    assert v.size == 11
    session.write("FORM4")


def test_savdasc_file_parses(session, sim):
    session.write("MEAS CPD;SWPT LOG;STAR 1E3;STOP 1E6;POIN 21;STOD MEMO")
    assert HP4294A(session).save_ascii("amostra 1").ok
    text = sim.files["MEMO:AMOSTRA1.TXT"]
    f = parse_savdasc(text)
    assert f.header["NUMBER of POINTS"] == "21"
    assert np.allclose(f.traces["A"].frequency, np.geomspace(1e3, 1e6, 21))


def _cfg():
    from ia4294.model.config import MeasurementConfig
    return MeasurementConfig(points=21, bw=1)


def test_savdasc_import_matches_gpib_read(session, sim, tmp_path):
    from ia4294.instrument import savdasc
    from ia4294.model.config import MeasurementConfig

    cfg = MeasurementConfig(meas="CPD", points=21, sweep_type="LOG", start=1e3, stop=1e6, bw=1)
    drv = HP4294A(session)
    gpib, _ = drv.acquire(cfg, threading.Event())
    drv.save_ascii("RUN1")
    p = tmp_path / "RUN1.TXT"
    p.write_text(sim.files["MEMO:RUN1.TXT"], encoding="latin-1")
    imported = savdasc.load(p, MeasurementConfig(meas="IMPH"))
    assert imported.config.meas == "CPD" and imported.source == "savdasc"
    assert np.allclose(imported.x, gpib.x, rtol=1e-9)
    assert np.allclose(imported.trace_a, gpib.trace_a, rtol=1e-5)
    assert np.allclose(imported.trace_b, gpib.trace_b, rtol=1e-5)


def test_find_listeners(session):
    assert session.find_listeners() == [17]
