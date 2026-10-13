"""A janela inteira contra o simulador, sem tela (QT_QPA_PLATFORM=offscreen)."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IA4294_REDUCED_MOTION"] = "1"
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    from ia4294.ui import theme

    a = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.load_fonts()
    a.setStyleSheet(theme.stylesheet())
    return a


def wait(app, cond, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    raise AssertionError("tempo esgotado")


def test_full_session(app, tmp_path):
    from ia4294.ui.controller import Controller
    from ia4294.ui.main_window import MainWindow

    ctl = Controller(simulator_time_scale=0.002)
    win = MainWindow(ctl)
    conn, measure, comp, acq, diel, log = win.pages
    try:
        ctl.connect_port("SIMULADOR", 17, 300, "spoll", on_done=lambda _v: conn.test_idn())
        wait(app, lambda: ctl.connected and ctl.idn.startswith("HEWLETT-PACKARD") and not ctl.busy)
        assert "conectado" in win.conn_meta.text()

        # perfil: Cp-D, 51 pontos
        measure.points.setValue(51)
        measure.meas.setCurrentIndex(measure.meas.findData("CPD"))
        assert ctl.config.points == 51 and ctl.config.meas == "CPD"
        measure.apply()
        wait(app, lambda: not ctl.busy and "OUTPERRO? = 0" in measure.result.text())

        # calibração A: setup do adaptador
        comp.tab_a.click()
        wa = comp.w_adapter
        for _ in range(3):
            wa.run_step()
            wait(app, lambda: not ctl.busy and "executando" not in wa.result.text())
        # simulador acelerado: PHASE COMP termina em <3 s e o app pede conferência
        assert wa.index == 3 and wa.status == {"ADAPTADOR": "ok", "PHASE COMP": "conferir", "DONE": "ok"}
        assert ctl.sim_instrument.adapter_setup_done

        # calibração B: OPEN → SHORT; o 4294A liga cada uma sozinho
        wf = comp.w_fixture
        wf.run_step()
        wait(app, lambda: not ctl.busy and wf.index == 1)
        wf.run_step()
        wait(app, lambda: not ctl.busy and wf.index == 2)
        wait(app, lambda: not ctl.busy and ctl.compensation.open and ctl.compensation.short)
        assert ctl.compensation.load is False
        assert "OPEN ON · SHORT ON · LOAD OFF" == win.comp_status.text()

        # calibração C: bloqueada no 4TP 1M
        assert not comp.w_user.proc.available and not comp.w_user.run_btn.isEnabled()

        # aquisição + dielétrico + exportação
        acq.export_dir = out = tmp_path / "export"
        acq.trigger()
        wait(app, lambda: ctl.result is not None and not ctl.busy)
        assert ctl.result.points == 51 and acq.model.rowCount() == 51
        assert diel.current is not None and 2 < diel.current.eps_real.mean() < 6
        acq.export(("csv", "parquet"))
        assert sorted(p.suffix for p in out.iterdir()) == [".csv", ".parquet"]
        assert "> ++eos 2" in "\n".join(f"{e.direction} {e.text}" for e in log.entries)
    finally:
        win.close()


def test_load_path_shows_inverted_keys(app):
    from ia4294.ui.controller import Controller
    from ia4294.ui.pages.calibration import CalibrationPage

    ctl = Controller()
    page = CalibrationPage(ctl)
    try:
        page.include_load.setChecked(True)
        plan = page.w_fixture.proc
        assert [(s.key, s.command) for s in plan.steps] == [("OPEN", "COMC"), ("SHORT", "COMB"), ("LOAD", "COMA")]
        assert not page.load_notice.isHidden()
        assert plan.pre.startswith("DCALLOADR 100E9;DCALLOADL 0;DCALOPENC")
        page.include_load.setChecked(False)
        assert [s.command for s in page.w_fixture.proc.steps] == ["COMA", "COMB"]
    finally:
        ctl.shutdown()


def test_measure_page_dcb_locks_widgets(app):
    from ia4294.ui.controller import Controller
    from ia4294.ui.pages.measure import MeasurePage

    ctl = Controller()
    page = MeasurePage(ctl)
    try:
        page.swpp.setCurrentIndex(page.swpp.findData("DCB"))
        log_item = page.swpt.model().item(page.swpt.findData("LOG"))
        assert not log_item.isEnabled() and page.swpt.currentData() == "LIN"
        assert page.start.unit == "V" and (page.start.lo, page.start.hi) == (-40, 40)
        assert page.cw.isEnabled() and not page.dclevel.isEnabled()
        assert page.dco.isChecked() and not page.dco.isEnabled()
        assert not page.bias_notice.isHidden()
        assert ctl.config.sweep_param == "DCB" and ctl.config.validate() == []
        # volta para FREQ: faixa anterior restaurada, LOG liberado
        page.swpp.setCurrentIndex(page.swpp.findData("FREQ"))
        assert page.start.unit == "Hz" and ctl.config.start == 1e3 and ctl.config.stop == 10e6
        assert log_item.isEnabled() and not page.cw.isEnabled()
    finally:
        ctl.shutdown()
