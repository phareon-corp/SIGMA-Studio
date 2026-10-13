"""06 / Log — tráfego GPIB bruto, com timestamp, e um console manual."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLineEdit, QPlainTextEdit, QSizePolicy, QVBoxLayout, QWidget

from ...transport.ar488 import GpibTimeout
from ...transport.traffic import TrafficEntry
from .. import theme
from ..controller import Controller
from ..widgets import PageHeader, button, label, mono_label

MAX_SHOWN = 600  # caracteres por linha na tela; o arquivo guarda tudo


class LogPage(QWidget):
    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        self.entries: list[TrafficEntry] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(PageHeader(
            "06", "Log", "Tráfego GPIB",
            "> host → interface   < interface → host   ! evento do app. "
            "Tudo também vai para o arquivo da sessão."))

        bar = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("filtrar (ex.: OUTPERRO, ++read, !)")
        self.follow = QCheckBox("Seguir")
        self.follow.setChecked(True)
        self.clear_btn = button("Limpar tela", small=True)
        self.open_btn = button("Abrir pasta dos logs", small=True)
        bar.addWidget(self.filter, 1)
        bar.addWidget(self.follow)
        bar.addWidget(self.clear_btn)
        bar.addWidget(self.open_btn)
        lay.addLayout(bar)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(theme.mono_font(11.5, 0.02, 400, caps=False))
        self.view.setMaximumBlockCount(20000)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        lay.addWidget(self.view, 1)

        con = QHBoxLayout()
        con.addWidget(mono_label("console", 10, 0.2))
        self.cmd = QLineEdit()
        self.cmd.setFont(theme.mono_font(12, 0.02, 400, caps=False))
        self.cmd.setPlaceholderText("mnemônico HP (ex.: POIN?) ou comando ++ da interface")
        self.send_btn = button("Enviar")
        self.query_btn = button("Enviar e ler", "primary")
        con.addWidget(self.cmd, 1)
        con.addWidget(self.send_btn)
        con.addWidget(self.query_btn)
        lay.addLayout(con)
        self.path = label(str(ctl.traffic_log.path), "meta", theme.mono_font(10.5, 0.03, 400, caps=False))
        self.path.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.path)

        ctl.traffic.connect(self.append)
        self.filter.textChanged.connect(self.refilter)
        self.clear_btn.clicked.connect(self.clear)
        self.open_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(ctl.traffic_log.path.parent))))
        self.send_btn.clicked.connect(lambda: self.send(read=False))
        self.query_btn.clicked.connect(lambda: self.send(read=True))
        self.cmd.returnPressed.connect(lambda: self.send(read=self.cmd.text().strip().endswith("?")))
        ctl.busy_changed.connect(lambda *_: self._enable())
        ctl.connection_changed.connect(lambda *_: self._enable())
        self._enable()

    @staticmethod
    def _line(e: TrafficEntry) -> str:
        text = e.text if len(e.text) <= MAX_SHOWN else e.text[:MAX_SHOWN] + "…"
        return f"{e.timestamp:%H:%M:%S.%f}"[:-3] + f"  {e.direction}  {text}"

    def _match(self, e: TrafficEntry) -> bool:
        f = self.filter.text().strip()
        return not f or f.lower() in f"{e.direction} {e.text}".lower()

    def append(self, e: TrafficEntry) -> None:
        self.entries.append(e)
        if len(self.entries) > 40000:
            del self.entries[:10000]
        if self._match(e):
            self.view.appendPlainText(self._line(e))
            if self.follow.isChecked():
                self.view.moveCursor(QTextCursor.MoveOperation.End)

    def refilter(self) -> None:
        self.view.setPlainText("\n".join(self._line(e) for e in self.entries if self._match(e)))
        self.view.moveCursor(QTextCursor.MoveOperation.End)

    def clear(self) -> None:
        self.entries.clear()
        self.view.clear()

    def send(self, read: bool) -> None:
        text = self.cmd.text().strip()
        if not text:
            return

        def job(ctx):
            s = ctx.session
            if text.startswith("++"):
                return s.interface_query(text) if read else s.raw(text)
            s.write(text)
            if read:
                try:
                    return s.read()
                except GpibTimeout:
                    return "(timeout)"
            return None

        self.ctl.run(f"console: {text}", job)

    def _enable(self) -> None:
        ok = self.ctl.connected and not self.ctl.busy
        self.send_btn.setEnabled(ok)
        self.query_btn.setEnabled(ok)
