"""04 / Aquisição — disparo, progresso, traços A e B, cursor, tabela, exportação."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QSizePolicy, QHBoxLayout, QHeaderView, QInputDialog, QProgressBar, QSplitter, QTableView,
    QVBoxLayout, QWidget,
)

from ... import paths
from ...instrument import savdasc
from ...instrument.parser import ParseError
from ...model import export
from ...model.sweep import SweepResult
from ...model.units import format_eng
from .. import theme
from ..controller import Controller
from ..plots import DualPlot
from ..widgets import Metric, PageHeader, button, label, mono_label


class PointsModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self.result: SweepResult | None = None
        self.font = theme.mono_font(11, 0.02, 400, caps=False)
        self.head_font = theme.mono_font(10, 0.15, 500, caps=False)

    def set_result(self, r: SweepResult | None) -> None:
        self.beginResetModel()
        self.result = r
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if self.result is None else self.result.points

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 3

    def headerData(self, s, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.FontRole:
            return self.head_font
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Vertical:
            return str(s + 1)
        if self.result is None:
            return ("Eixo", "A", "B")[s]
        p = self.result.param
        return (self.result.axis.label, p.a.symbol, p.b.symbol)[s]

    def data(self, idx: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        r = self.result
        if r is None:
            return None
        if role == Qt.ItemDataRole.FontRole:
            return self.font
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        i, c = idx.row(), idx.column()
        p = r.param
        if c == 0:
            return format_eng(r.x[i], r.axis.unit, 6)
        q, arr = (p.a, r.trace_a) if c == 1 else (p.b, r.trace_b)
        return format_eng(arr[i], q.unit, 6)


class AcquisitionPage(QWidget):
    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        self.export_dir = paths.data_dir()
        self._job: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(PageHeader(
            "04", "Aquisição", f"Varredura de {theme.serif_span('impedância')}",
            "HOLD → configura → SING (ou NUMG com média) → espera o status byte → lê os dois traços."))

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.trigger_btn = button("Disparar", "primary")
        self.abort_btn = button("Abortar")
        self.apply_cb = QCheckBox("Aplicar perfil antes")
        self.apply_cb.setChecked(True)
        self.repeat_cb = QCheckBox("Repetir")
        self.logx_cb = QCheckBox("X log")
        self.logx_cb.setChecked(True)
        self.auto_cb = QCheckBox("Autoescala")
        self.auto_cb.setChecked(True)
        for w in (self.trigger_btn, self.abort_btn, self.apply_cb, self.repeat_cb):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(self.logx_cb)
        bar.addWidget(self.auto_cb)
        lay.addLayout(bar)

        prog = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress_msg = mono_label("pronto", 10, 0.12, caps=False)
        self.progress_msg.setMinimumWidth(200)
        self.progress_msg.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.progress.setMinimumWidth(200)
        prog.addWidget(self.progress, 1)
        prog.addWidget(self.progress_msg)
        lay.addLayout(prog)

        metrics = QHBoxLayout()
        metrics.setSpacing(40)
        self.m_f = Metric("cursor · eixo", caps=False)
        self._logx_freq = True  # preferência do usuário quando o eixo é frequência
        self.m_a = Metric("traço A", caps=False)
        self.m_b = Metric("traço B", caps=False)
        self.m_n = Metric("pontos", caps=False)
        for m in (self.m_f, self.m_a, self.m_b, self.m_n):
            metrics.addWidget(m)
        metrics.addStretch(1)
        lay.addLayout(metrics)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.plot = DualPlot()
        split.addWidget(self.plot)
        self.model = PointsModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.verticalHeader().setFont(theme.mono_font(10, 0.05, 400))
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        split.addWidget(self.table)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([700, 380])
        split.setMinimumHeight(250)
        self.table.setMinimumWidth(260)
        lay.addWidget(split, 1)

        out = QHBoxLayout()
        out.setSpacing(10)
        self.csv_btn = button("Exportar CSV")
        self.pq_btn = button("Exportar Parquet")
        self.dir_btn = button("Pasta…", small=True)
        self.savdasc_btn = button("SAVDASC no instrumento", small=True)
        self.import_btn = button("Importar .TXT do 4294A", small=True)
        for w in (self.csv_btn, self.pq_btn, self.dir_btn):
            out.addWidget(w)
        self.out_label = label(str(self.export_dir), "meta", theme.mono_font(10.5, 0.03, 400, caps=False))
        self.out_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        out.addWidget(self.out_label, 1)
        out.addWidget(self.savdasc_btn)
        out.addWidget(self.import_btn)
        lay.addLayout(out)

        self.trigger_btn.clicked.connect(self.trigger)
        self.abort_btn.clicked.connect(self.abort)
        self.logx_cb.toggled.connect(self._logx_toggled)
        self.auto_cb.toggled.connect(self.plot.set_autoscale)
        self.plot.cursor_moved.connect(self.on_cursor)
        self.table.clicked.connect(lambda i: self.plot.place_cursor(i.row()))
        self.csv_btn.clicked.connect(lambda: self.export(("csv",)))
        self.pq_btn.clicked.connect(lambda: self.export(("parquet",)))
        self.dir_btn.clicked.connect(self.choose_dir)
        self.savdasc_btn.clicked.connect(self.save_on_instrument)
        self.import_btn.clicked.connect(self.import_txt)
        ctl.progress.connect(self.on_progress)
        ctl.busy_changed.connect(lambda *_: self._enable())
        ctl.connection_changed.connect(lambda *_: self._enable())
        ctl.result_ready.connect(self.show_result)
        self._enable()

    # ── disparo ─────────────────────────────────────────────────────────
    def trigger(self) -> None:
        cfg = self.ctl.config
        apply = self.apply_cb.isChecked()
        self.progress.setValue(0)

        def job(ctx):
            return ctx.driver.acquire(cfg, ctx.abort, ctx.progress, apply=apply)

        def done(r):
            result, _reports = r
            self._job = None
            self.progress.setValue(0)
            self.ctl.set_result(result)
            fixed = "" if result.axis.is_frequency else f" · em {format_eng(result.config.cw_freq_hz, 'Hz')}"
            self.progress_msg.setText(f"{result.points} pontos lidos{fixed} · {result.compensation.text()}")
            if self.repeat_cb.isChecked():
                self.apply_cb.setChecked(False)  # perfil já está no instrumento
                self.trigger()

        def fail(err, aborted):
            self._job = None
            self.progress.setValue(0)
            self.progress_msg.setText("abortado — HOLD enviado" if aborted else f"falhou: {err}")

        self._job = self.ctl.run("aquisição", job, done, fail)

    def abort(self) -> None:
        self.repeat_cb.setChecked(False)
        self.ctl.abort()

    def on_progress(self, frac: float, msg: str) -> None:
        if self._job is None:
            return
        self.progress.setValue(int(frac * 1000))
        self.progress_msg.setText(msg)

    # ── resultado ───────────────────────────────────────────────────────
    def _logx_toggled(self, on: bool) -> None:
        if self.logx_cb.isEnabled():
            self._logx_freq = on
        self.plot.set_logx(on)

    def show_result(self, r: SweepResult) -> None:
        p = r.param
        ax = r.axis
        # X log só faz sentido em frequência; bias pode ser negativo
        self.logx_cb.setEnabled(ax.is_frequency)
        self.logx_cb.setChecked(self._logx_freq if ax.is_frequency else False)
        self.plot.set_logx(self.logx_cb.isChecked())
        self.plot.set_x(ax.label, ax.unit)
        self.m_f.set_title(f"cursor · {ax.label.lower()}")
        self.plot.set_labels((p.a.symbol, p.a.unit), (p.b.symbol, p.b.unit))
        self.plot.set_data(r.x, r.trace_a, r.trace_b,
                           (r.config.fmt_a == "LOGY", r.config.fmt_b == "LOGY"))
        self.model.set_result(r)
        self.m_a.set_title(f"traço A · {p.a.symbol}")
        self.m_b.set_title(f"traço B · {p.b.symbol}")
        self.m_n.value.setText(f"{r.points}")
        self._enable()

    def on_cursor(self, i: int) -> None:
        r = self.ctl.result
        if r is None or i < 0:
            return
        order = np.argsort(r.x)
        k = int(order[i])
        p = r.param
        self.m_f.set(r.x[k], r.axis.unit, 6)
        self.m_a.set(r.trace_a[k], p.a.unit)
        self.m_b.set(r.trace_b[k], p.b.unit)
        self.table.selectRow(k)

    # ── saída ───────────────────────────────────────────────────────────
    def export(self, formats: tuple[str, ...]) -> None:
        r = self.ctl.result
        if r is None:
            return
        try:
            files = export.export_run(r, self.export_dir, formats)
        except (OSError, ValueError) as exc:
            self.ctl.status.emit("erro", f"exportação: {exc}")
            return
        self.out_label.setText(str(files[0]))
        self.out_label.setToolTip(str(files[0]))
        self.ctl.status.emit("info", f"exportado: {files[0].name}")

    def choose_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Pasta de exportação", str(self.export_dir))
        if d:
            self.export_dir = Path(d)
            self.out_label.setText(d)

    def save_on_instrument(self) -> None:
        name, ok = QInputDialog.getText(self, "SAVDASC", "Nome do arquivo no 4294A (até 8 caracteres):",
                                        text="IA4294")
        if not ok:
            return
        storage, ok = QInputDialog.getItem(self, "SAVDASC", "Armazenamento (STOD):", ["MEMO", "FLASH", "DISK"], 0,
                                           False)
        if not ok:
            return

        def done(rep):
            if rep.ok:
                self.ctl.status.emit("info", f"SAVDASC gravado em {storage}: {rep.message.split('SAVDASC ')[-1]}")
            else:
                self.ctl.status.emit("erro", "SAVDASC: " + ", ".join(f"{c} {m}" for c, m in rep.errors))

        self.ctl.run("SAVDASC", lambda ctx: ctx.driver.save_ascii(name, storage), done)

    def import_txt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Arquivo ASCII do 4294A", str(Path.home()),
                                              "4294A ASCII (*.TXT *.txt);;Todos (*)")
        if not path:
            return
        try:
            result = savdasc.load(Path(path), self.ctl.config)
        except (OSError, ParseError, ValueError) as exc:
            self.ctl.status.emit("erro", f"importação: {exc}")
            return
        self.ctl.set_result(result)
        self.ctl.status.emit("info", f"importado {Path(path).name}: {result.points} pontos")

    def _enable(self) -> None:
        busy, conn = self.ctl.busy, self.ctl.connected
        self.trigger_btn.setEnabled(conn and not busy)
        self.abort_btn.setEnabled(busy)
        self.savdasc_btn.setEnabled(conn and not busy)
        has = self.ctl.result is not None
        self.csv_btn.setEnabled(has)
        self.pq_btn.setEnabled(has)
