"""05 / Dielétrico — ε′ = Cp·t/(ε0·A) e tan δ = D versus frequência."""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QHBoxLayout, QVBoxLayout, QWidget

from ...model import dielectric, export
from ...model.params import DIELECTRIC_PARAMS, MEAS_PARAMS
from ...model.sweep import SweepResult
from ...model.units import format_eng
from .. import theme
from ..controller import Controller
from ..plots import DualPlot
from ..widgets import Metric, PageHeader, Panel, button, form_grid, form_row, label, mono_label

# Eletrodos de medição do 16451B (método de contato). Confira na etiqueta.
ELECTRODES = [("A", "Eletrodo A · 38 mm", 38.0), ("B", "Eletrodo B · 5 mm", 5.0), ("X", "Outro diâmetro", None)]


def _mm(v: float, lo: float, hi: float, decimals: int = 3) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setValue(v)
    s.setSuffix(" mm")
    s.setFont(theme.mono_font(12, 0.03, 400, caps=False))
    return s


class DielectricPage(QWidget):
    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        self.current: dielectric.DielectricResult | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        lay.addWidget(PageHeader(
            "05", "Dielétrico", f"Permissividade da {theme.serif_span('amostra')}",
            "Placas paralelas com eletrodo de guarda. Precisa de uma varredura em Cp-D "
            "(ou Cp-G, Cp-Q, Cp-Rp, convertidos para D)."))

        top = QHBoxLayout()
        top.setSpacing(16)
        geo = Panel("Geometria", "16451B")
        g = form_grid()
        self.thick = _mm(1.0, 0.001, 10.0)
        form_row(g, 0, "Espessura · t", self.thick, "medida com micrômetro")
        self.electrode = QComboBox()
        for key, text, _d in ELECTRODES:
            self.electrode.addItem(text, key)
        form_row(g, 1, "Eletrodo", self.electrode)
        self.diam = _mm(38.0, 0.1, 100.0, 2)
        form_row(g, 2, "Diâmetro · d", self.diam)
        geo.body.addLayout(g)
        geo.body.addWidget(mono_label("ε′ = Cp·t / (ε0·A)    A = π(d/2)²    tan δ = D", 11, 0.06, "value",
                                      caps=False))
        b = QHBoxLayout()
        self.calc_btn = button("Calcular", "primary")
        self.export_btn = button("Exportar CSV + ε′")
        b.addWidget(self.calc_btn)
        b.addWidget(self.export_btn)
        b.addStretch(1)
        geo.body.addLayout(b)
        self.msg = label("", "meta", theme.body_font(12.5), wrap=True)
        geo.body.addWidget(self.msg)
        top.addWidget(geo, 2)

        m = Panel("Leitura no cursor")
        mm = QHBoxLayout()
        mm.setSpacing(36)
        self.m_f = Metric("eixo", caps=False)
        self.m_eps = Metric("ε′ relativa", caps=False)
        self.m_tan = Metric("tan δ", caps=False)
        for w in (self.m_f, self.m_eps, self.m_tan):
            mm.addWidget(w)
        mm.addStretch(1)
        m.body.addLayout(mm)
        self.m_range = mono_label("", 10.5, 0.06, caps=False)
        m.body.addWidget(self.m_range)
        m.body.addStretch(1)
        top.addWidget(m, 3)
        lay.addLayout(top)

        self.plot = DualPlot()
        self.plot.set_labels(("ε′", ""), ("tan δ", ""))
        lay.addWidget(self.plot, 1)

        self.electrode.currentIndexChanged.connect(self._preset)
        self.calc_btn.clicked.connect(self.calculate)
        self.export_btn.clicked.connect(self.export)
        self.plot.cursor_moved.connect(self.on_cursor)
        ctl.result_ready.connect(self.on_result)
        self._enable()

    def _preset(self) -> None:
        d = ELECTRODES[self.electrode.currentIndex()][2]
        if d is not None:
            self.diam.setValue(d)
        self.diam.setEnabled(d is None)

    def geometry(self) -> dielectric.Geometry:
        return dielectric.Geometry(self.thick.value() * 1e-3, self.diam.value() * 1e-3)

    def on_result(self, r: SweepResult) -> None:
        self._enable()
        if r.config.meas in DIELECTRIC_PARAMS:
            self.calculate()
        else:
            self.msg.setText(f"última varredura em {MEAS_PARAMS[r.config.meas].label}; "
                             f"meça em {', '.join(MEAS_PARAMS[k].label for k in DIELECTRIC_PARAMS)}")

    def calculate(self) -> None:
        r = self.ctl.result
        if r is None:
            return
        try:
            self.current = dielectric.compute(r, self.geometry())
        except ValueError as exc:
            self.current = None
            self.msg.setText(str(exc))
            self._enable()
            return
        d = self.current
        ax = d.axis
        self.plot.set_logx(ax.is_frequency)  # ε′ × bias é linear e pode ter V < 0
        self.plot.set_x(ax.label, ax.unit)
        self.m_f.set_title(ax.label.lower())
        self.plot.set_data(d.x, d.eps_real, d.tan_delta, (False, bool(np.all(d.tan_delta > 0))))
        g = d.geometry
        fixed = "" if d.cw_freq_hz is None else f"   curva levantada em {format_eng(d.cw_freq_hz, 'Hz')}"
        self.msg.setText(f"A = {g.area_m2 * 1e6:.4g} mm²   C0 = ε0·A/t = "
                         f"{dielectric.EPS0 * g.area_m2 / g.thickness_m * 1e12:.4g} pF   "
                         f"fonte: {MEAS_PARAMS[r.config.meas].label}{fixed}")
        self.m_range.setText(f"ε′ {np.nanmin(d.eps_real):.4g} – {np.nanmax(d.eps_real):.4g}    "
                             f"tan δ {np.nanmin(d.tan_delta):.3g} – {np.nanmax(d.tan_delta):.3g}")
        self._enable()

    def on_cursor(self, i: int) -> None:
        d = self.current
        if d is None or i < 0:
            return
        k = int(np.argsort(d.x)[i])
        self.m_f.set(d.x[k], d.axis.unit, 6)
        self.m_eps.set(d.eps_real[k], "", 5)
        self.m_tan.set(d.tan_delta[k], "", 4)

    def export(self) -> None:
        if self.ctl.result is None or self.current is None:
            return
        page = self.window().findChild(QWidget, "acquisition")
        directory = getattr(page, "export_dir", None)
        from ... import paths

        files = export.export_run(self.ctl.result, directory or paths.data_dir(), ("csv",), self.current)
        self.ctl.status.emit("info", f"exportado: {files[0].name}")
        self.msg.setText(str(files[0]))

    def _enable(self) -> None:
        r = self.ctl.result
        self.calc_btn.setEnabled(r is not None and r.config.meas in DIELECTRIC_PARAMS)
        self.export_btn.setEnabled(self.current is not None)
