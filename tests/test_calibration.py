import threading

from ia4294.instrument.hp4294a import HP4294A
from ia4294.model import calibration as cal


def test_adapter_setup_is_phase_comp_then_done():
    p = cal.adapter_setup("M1")
    assert [s.command for s in p.steps] == ["E4TP M1", "ECALP", "ECALDON"]
    assert [s.measures for s in p.steps] == [False, True, False]


def test_fixture_load_path_inverts_keys():
    p = cal.fixture_compensation(True, load_c=12e-12, load_g=1e-9)
    assert [s.command for s in p.steps] == ["COMC", "COMB", "COMA"]
    assert "DCALLOADR 100E9;DCALLOADL 0;DCALOPENC 1.2e-11;DCALOPENG 1e-09" in p.pre
    assert [s.command for s in cal.fixture_compensation(False).steps] == ["COMA", "COMB"]


def test_user_cal_blocked_on_4tp1m():
    assert not cal.user_calibration("M1").available
    assert "p. 147" in cal.user_calibration("M1").unavailable_reason
    assert cal.user_calibration("APC7").available


def test_sim_adapter_setup(session, sim):
    drv = HP4294A(session)
    ev = threading.Event()
    errs, _ = drv.cal_step("ECALDON", False, 0, ev)
    assert errs and errs[0][0] == 10  # sem PHASE COMP
    for st in cal.adapter_setup("M1").steps:
        errs, _ = drv.cal_step(st.command, st.measures, 0.1, ev)
        assert errs == [], st.command
    assert sim.adapter_setup_done and drv.adapter() == "M1"


def test_sim_fixture_comp_turns_on_by_itself(session):
    drv = HP4294A(session)
    for st in cal.fixture_compensation(False).steps:
        assert drv.cal_step(st.command, True, 0.1, threading.Event())[0] == []
    c = drv.comp_state()
    assert (c.open, c.short, c.load) == (True, True, False)


def test_sim_user_cal(session):
    drv = HP4294A(session)
    ev = threading.Event()
    assert drv.cal_step("CALA", True, 0.1, ev)[0][0][0] == -224  # 4TP 1M recusa
    drv.block("a", "E4TP APC7")
    for st in cal.user_calibration("APC7").steps:
        assert drv.cal_step(st.command, st.measures, 0.1, ev)[0] == [], st.command
    assert drv.user_cal_on() is True
