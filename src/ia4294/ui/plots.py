"""Dois gráficos empilhados com X ligado e um cursor de leitura comum."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .widgets import axis_text, cursor_pen, data_pen, paint_plot, si_axes, style_plot

pg.setConfigOptions(antialias=True)


class DualPlot(QWidget):
    #: índice do ponto sob o cursor (−1 sem dados)
    cursor_moved = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.plots = [pg.PlotWidget(axisItems=si_axes()), pg.PlotWidget(axisItems=si_axes())]
        self.curves = []
        self.cursors = []
        for pw in self.plots:
            style_plot(pw, "", "")
            curve = pw.plot([], [], pen=data_pen())
            line = pg.InfiniteLine(angle=90, movable=True, pen=cursor_pen())
            line.setVisible(False)
            pw.addItem(line)
            line.sigPositionChanged.connect(self._on_line)
            self.curves.append(curve)
            self.cursors.append(line)
            pw.setMinimumSize(240, 120)
            lay.addWidget(pw, 1)
            pw.scene().sigMouseClicked.connect(lambda ev, w=pw: self._on_click(ev, w))
        self.plots[1].setXLink(self.plots[0])
        self.x = np.empty(0)
        self.logx = True
        self._logy = [False, False]
        self._busy = False

    def restyle(self) -> None:
        """Troca de terreno: pyqtgraph guarda as canetas, então refaz todas."""
        for pw, curve, line in zip(self.plots, self.curves, self.cursors):
            paint_plot(pw)
            curve.setPen(data_pen())
            line.setPen(cursor_pen())

    def set_x(self, name: str, unit: str) -> None:
        for pw in self.plots:
            pw.getPlotItem().setLabel("bottom", axis_text(name, unit))

    def set_labels(self, a: tuple[str, str], b: tuple[str, str]) -> None:
        for pw, (name, unit) in zip(self.plots, (a, b)):
            pw.getPlotItem().setLabel("left", axis_text(name, unit))

    def set_data(self, x: np.ndarray, ya: np.ndarray, yb: np.ndarray,
                 logy: tuple[bool, bool] = (False, False)) -> None:
        order = np.argsort(x)
        self.x = np.asarray(x, float)[order]
        for k, (pw, curve, y, ly) in enumerate(zip(self.plots, self.curves, (ya, yb), logy)):
            y = np.asarray(y, float)[order]
            self._logy[k] = ly = ly and bool(np.all(y > 0))
            pw.setLogMode(x=self.logx, y=ly)
            curve.setData(self.x, y)
        if self.x.size:
            for line in self.cursors:
                line.setVisible(True)
            self.place_cursor(int(self.x.size // 2))

    def set_logx(self, on: bool) -> None:
        i = self.index()  # antes de trocar o espaço do cursor
        self.logx = on
        for pw, ly in zip(self.plots, self._logy):
            pw.setLogMode(x=on, y=ly)
        if i >= 0:
            self.place_cursor(i)

    def set_autoscale(self, on: bool) -> None:
        for pw in self.plots:
            if on:
                pw.enableAutoRange()
            else:
                pw.disableAutoRange()

    def _to_view(self, xv: float) -> float:
        return float(np.log10(xv)) if self.logx and xv > 0 else xv

    def _from_view(self, pos: float) -> float:
        return float(10**pos) if self.logx else pos

    def index(self) -> int:
        if not self.x.size:
            return -1
        xv = self._from_view(self.cursors[0].value())
        return int(np.argmin(np.abs(self.x - xv)))

    def place_cursor(self, i: int) -> None:
        if not self.x.size:
            return
        i = max(0, min(i, self.x.size - 1))
        self._busy = True
        for line in self.cursors:
            line.setValue(self._to_view(self.x[i]))
        self._busy = False
        self.cursor_moved.emit(i)

    def _on_line(self, line: pg.InfiniteLine) -> None:
        if self._busy:
            return
        self._busy = True
        for other in self.cursors:
            if other is not line:
                other.setValue(line.value())
        self._busy = False
        self.cursor_moved.emit(self.index())

    def _on_click(self, ev, pw: pg.PlotWidget) -> None:
        if not self.x.size or ev.button() != pg.QtCore.Qt.MouseButton.LeftButton:
            return
        vb = pw.getPlotItem().getViewBox()
        if not vb.sceneBoundingRect().contains(ev.scenePos()):
            return
        p = vb.mapSceneToView(ev.scenePos())
        self.cursors[0].setValue(p.x())
