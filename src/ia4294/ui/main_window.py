"""Janela principal: barra superior, navegação numerada, páginas, rodapé."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSettings, QSize, Qt
from PySide6.QtGui import QCloseEvent, QIcon, QKeySequence, QPainter, QPixmap, QRadialGradient, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QButtonGroup, QFrame, QHBoxLayout, QMainWindow, QScrollArea, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from ..model.sweep import CompensationState
from . import theme
from .controller import Controller
from .pages.acquisition import AcquisitionPage
from .pages.calibration import CalibrationPage
from .pages.connection import ConnectionPage
from .pages.dielectric import DielectricPage
from .pages.log import LogPage
from .pages.measure import MeasurePage
from .widgets import Dot, TerrainButton, label, mono_label


class NavItem(QAbstractButton):
    """``01  Conexão`` — o numeral acende em acento quando a página está ativa."""

    def __init__(self, num: str, text: str) -> None:
        super().__init__()
        self.num, self.text_ = num, text
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setMinimumHeight(40)
        self.setAccessibleName(f"{num} {text}")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(200, 40)

    _kbd = False

    def focusInEvent(self, e) -> None:  # noqa: N802
        self._kbd = e.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason)
        super().focusInEvent(e)

    def focusOutEvent(self, e) -> None:  # noqa: N802
        self._kbd = False
        super().focusOutEvent(e)

    def enterEvent(self, e) -> None:  # noqa: N802
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isChecked() or self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("bg-3"))
            p.drawRoundedRect(r, 5, 5)
        if self.hasFocus() and self._kbd:
            p.setPen(theme.color("accent"))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 5, 5)
        p.setFont(theme.mono_font(11, 0.2, 500))
        p.setPen(theme.color("accent") if self.isChecked() else theme.color("ink-faint"))
        p.drawText(self.rect().adjusted(14, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, self.num)
        p.setFont(theme.body_font(13.5, 500 if self.isChecked() else 400))
        p.setPen(theme.color("ink") if self.isChecked() or self.underMouse() else theme.color("ink-dim"))
        p.drawText(self.rect().adjusted(50, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, self.text_)


def app_icon() -> QIcon:
    """O logo-mark: fonte pontual de luz (gradiente radial num círculo)."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(theme.color("bg"))
    p.drawEllipse(2, 2, 60, 60)
    g = QRadialGradient(32, 32, 26)
    g.setColorAt(0.0, theme.color("ink"))
    g.setColorAt(0.25, theme.color("accent-glow"))
    g.setColorAt(0.6, theme.color("accent"))
    g.setColorAt(1.0, theme.color("bg"))
    p.setBrush(g)
    p.drawEllipse(6, 6, 52, 52)
    p.end()
    return QIcon(pm)


class _PageLayout(QVBoxLayout):
    """Sem height-for-width: senão o QScrollArea dimensiona a página pela altura
    *preferida* (gráficos de 480 px) em vez da mínima, e tudo rola à toa."""

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return False


PAGES = [("01", "Conexão"), ("02", "Medida"), ("03", "Calibração"),
         ("04", "Aquisição"), ("05", "Dielétrico"), ("06", "Log")]


class MainWindow(QMainWindow):
    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        self.setWindowTitle(f"{APP_NAME} — HP 4294A")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(960, 600)
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        if avail is not None and (avail.width() < 1360 or avail.height() < 900):
            # telas como 1366×768: ocupa tudo; o conteúdo rola onde precisar
            self.resize(avail.width(), avail.height())
            self._maximize = True
        else:
            self.resize(1320, 860)
            self._maximize = False

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ── barra superior ──
        top = QFrame()
        top.setObjectName("topbar")
        top.setFixedHeight(46)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(14, 0, 20, 0)
        tl.setSpacing(2)
        self.source_dot = Dot(6, on=True)
        tl.addWidget(self.source_dot)
        tl.addWidget(mono_label(APP_NAME, 11, 0.24, "value"))
        tl.addSpacing(18)
        tl.addWidget(mono_label("HP 4294A · 16451B · AR488", 10, 0.18))
        tl.addStretch(1)
        self.conn_meta = mono_label("desconectado", 10, 0.18)
        tl.addWidget(self.conn_meta)
        tl.addSpacing(12)
        self.terrain_btn = TerrainButton()
        self.terrain_btn.clicked.connect(self.toggle_terrain)
        tl.addWidget(self.terrain_btn)
        v.addWidget(top)

        # ── navegação + páginas ──
        mid = QHBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(0)
        v.addLayout(mid, 1)

        nav = QFrame()
        nav.setObjectName("sidenav")
        nav.setFixedWidth(206)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(10, 22, 10, 16)
        nl.setSpacing(2)
        head = mono_label("Instrumento", 10, 0.18)
        head.setContentsMargins(8, 0, 0, 10)
        nl.addWidget(head)
        self.group = QButtonGroup(self)
        self.nav_items: list[NavItem] = []
        for i, (num, text) in enumerate(PAGES):
            item = NavItem(num, text)
            self.group.addButton(item, i)
            self.nav_items.append(item)
            nl.addWidget(item)
        nl.addStretch(1)
        foot = QFrame()
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(8, 12, 8, 0)
        fl.setSpacing(6)
        fl.addWidget(mono_label("Compensação", 10, 0.18))
        self.comp_side = label("", "value", theme.mono_font(10.5, 0.06, 500, caps=False), wrap=True)
        fl.addWidget(self.comp_side)
        fl.addSpacing(8)
        fl.addWidget(mono_label(f"v {__version__} · SP · BR", 10, 0.15))
        nl.addWidget(foot)
        mid.addWidget(nav)

        self.stack = QStackedWidget()
        self.pages = [ConnectionPage(ctl), MeasurePage(ctl), CalibrationPage(ctl),
                      AcquisitionPage(ctl), DielectricPage(ctl), LogPage(ctl)]
        names = ["connection", "measure", "calibration", "acquisition", "dielectric", "log"]
        for page, name in zip(self.pages, names):
            page.setObjectName(name)
            holder = QWidget()
            hl = _PageLayout(holder)
            hl.setContentsMargins(26, 18, 26, 12)
            hl.addWidget(page)
            scroll = QScrollArea()  # nunca espreme: abaixo do mínimo, rola
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(holder)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.stack.addWidget(scroll)
        mid.addWidget(self.stack, 1)

        # ── rodapé ──
        bar = QFrame()
        bar.setObjectName("statusbar")
        bar.setFixedHeight(30)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 0, 16, 0)
        self.status_msg = label("pronto", "meta", theme.mono_font(10.5, 0.04, 400, caps=False))
        bl.addWidget(self.status_msg, 1)
        self.job = mono_label("", 10, 0.15)
        bl.addWidget(self.job)
        bl.addSpacing(18)
        self.comp_status = mono_label("", 10, 0.15, "value")
        bl.addWidget(self.comp_status)
        v.addWidget(bar)

        self.group.idClicked.connect(self.show_page)
        ctl.connection_changed.connect(self.on_connection)
        ctl.status.connect(self.on_status)
        ctl.busy_changed.connect(self.on_busy)
        ctl.compensation_changed.connect(self.on_comp)
        for i in range(len(PAGES)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self.show_page(i))
        QShortcut(QKeySequence("Esc"), self, activated=self._escape)
        QShortcut(QKeySequence("Ctrl+T"), self, activated=self.toggle_terrain)
        self.terrain_btn.restyle()

        self.on_comp(ctl.compensation)
        self.source_dot.set_on(False)
        self.show_page(0)

    # ── terreno ─────────────────────────────────────────────────────────
    def toggle_terrain(self) -> None:
        self.apply_terrain("claro" if theme.terrain() == "escuro" else "escuro")

    def apply_terrain(self, name: str, save: bool = True) -> str:
        """Troca o terreno com a janela aberta e repinta o que o QSS não alcança."""
        theme.set_terrain(name)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet())
        self.setWindowIcon(app_icon())
        for w in self.findChildren(QWidget):
            restyle = getattr(w, "restyle", None)
            if callable(restyle):
                restyle()
            w.update()
        self.update()
        if save:
            QSettings("ia4294", "ia4294").setValue("ui/terreno", theme.terrain())
        return theme.terrain()

    def show_page(self, i: int) -> None:
        self.nav_items[i].setChecked(True)
        self.stack.setCurrentIndex(i)

    def _escape(self) -> None:
        if self.ctl.busy:
            self.ctl.abort()

    def on_connection(self, connected: bool, desc: str) -> None:
        addr = self.pages[0].addr.value()
        if connected:
            tag = "simulador" if self.ctl.simulated else desc
            self.conn_meta.setText(f"gpib {addr} · {tag} · conectado")
        else:
            self.conn_meta.setText("desconectado")
        self.source_dot.set_on(connected)

    def on_status(self, level: str, text: str) -> None:
        self.status_msg.setText(text)
        self.status_msg.setProperty("role", "error" if level == "erro" else "meta")
        self.status_msg.style().unpolish(self.status_msg)
        self.status_msg.style().polish(self.status_msg)

    def on_busy(self, busy: bool, name: str) -> None:
        self.job.setText(f"// {name}" if busy else "")
        sweeping = busy and any(k in name for k in ("aquisição", "calibração", "probe"))
        self.source_dot.pulse(sweeping)  # pulso = fonte ativa

    def on_comp(self, st: CompensationState) -> None:
        self.comp_status.setText(st.text())
        self.comp_side.setText(st.text().replace(" · ", "\n"))

    def closeEvent(self, e: QCloseEvent) -> None:  # noqa: N802
        if self.ctl.busy:
            self.ctl.abort()
        self.ctl.shutdown()
        super().closeEvent(e)
