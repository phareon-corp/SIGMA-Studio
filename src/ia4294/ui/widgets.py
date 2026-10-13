"""Componentes Phareon em Qt: cabeçalho de seção, painel, botões, leituras."""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Property, QPointF, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)

from ..model.units import format_eng, parse_eng
from . import theme


def label(text: str = "", role: str | None = None, font=None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    if font is not None:
        lb.setFont(font)
    lb.setWordWrap(wrap)
    lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lb


def mono_label(text: str = "", px: float = 10, tracking: float = 0.2, role: str = "meta",
               caps: bool = True) -> QLabel:
    lb = label(text, role, theme.mono_font(px, tracking, 500, caps))
    return lb


def button(text: str, kind: str = "ghost", small: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setProperty("kind", kind)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFont(theme.body_font(12.5 if small else 13, 500))
    b.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    return b


class Dot(QWidget):
    """Ponto de 6–7px. Aceso = acento com halo (estado ativo); apagado = contorno."""

    def __init__(self, size: int = 7, on: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self._on = on
        self._level = 1.0
        self.setFixedSize(size + 12, size + 12)
        self._anim: QPropertyAnimation | None = None

    def set_on(self, on: bool) -> None:
        self._on = on
        self.update()

    def _get_level(self) -> float:
        return self._level

    def _set_level(self, v: float) -> None:
        self._level = v
        self.update()

    level = Property(float, _get_level, _set_level)

    def pulse(self, active: bool) -> None:
        """Pulso de 3 s = fonte ativa (P5: movimento tem causa)."""
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self._set_level(1.0)
        if not active or theme.reduced_motion():
            return
        a = QPropertyAnimation(self, b"level", self)
        a.setDuration(3000)
        a.setKeyValueAt(0.0, 1.0)
        a.setKeyValueAt(0.5, 0.35)
        a.setKeyValueAt(1.0, 1.0)
        a.setEasingCurve(theme.ease())
        a.setLoopCount(-1)
        a.start()
        self._anim = a

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.rect().center()
        r = self._size / 2
        if self._on:
            glow = theme.color("accent")
            for i, alpha in ((6, 18), (4, 40), (2, 80)):
                g = QColor(glow)
                g.setAlpha(round(alpha * self._level))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(g)
                p.drawEllipse(c, r + i, r + i)
            core = theme.color("accent")
            core.setAlphaF(0.55 + 0.45 * self._level)
            p.setBrush(core)
            p.drawEllipse(c, r, r)
        else:
            p.setPen(theme.color("ink-faint"))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, r - 0.5, r - 0.5)


class TerrainButton(QAbstractButton):
    """Sol ou lua: o desenho é o do terreno para onde o clique leva.

    Traço só, com a espessura da hairline do sistema — o sol não é um disco
    cheio porque não é fonte de sinal; sinal aqui é o laranja.
    """

    SIZE = 30

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._kbd = False

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

    def target(self) -> str:
        """O terreno do outro lado do clique."""
        return "claro" if theme.terrain() == "escuro" else "escuro"

    def restyle(self) -> None:
        alvo = self.target()
        self.setToolTip(f"Ctrl+T — terreno {alvo}")
        self.setAccessibleName(f"mudar para o terreno {alvo}")
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hot = self.underMouse() or (self.hasFocus() and self._kbd)
        if hot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("bg-3"))
            p.drawEllipse(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        if self.hasFocus() and self._kbd:
            p.setPen(theme.color("accent"))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        ink = theme.color("ink" if hot else "ink-faint")
        pen = p.pen()
        pen.setColor(ink)
        pen.setWidthF(1.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        c = QRectF(self.rect()).center()
        if self.target() == "escuro":
            self._moon(p, c, ink)
        else:
            self._sun(p, c)

    @staticmethod
    def _sun(p: QPainter, c) -> None:
        r = 4.0
        p.drawEllipse(c, r, r)
        for i in range(8):
            a = math.radians(i * 45)
            dx, dy = math.cos(a), math.sin(a)
            p.drawLine(QPointF(c.x() + dx * (r + 2.4), c.y() + dy * (r + 2.4)),
                       QPointF(c.x() + dx * (r + 4.6), c.y() + dy * (r + 4.6)))

    @staticmethod
    def _moon(p: QPainter, c, ink: QColor) -> None:
        """Crescente = disco menos disco deslocado; o recorte é o próprio fundo."""
        r = 7.0
        full = QPainterPath()
        full.addEllipse(c, r, r)
        bite = QPainterPath()
        bite.addEllipse(QPointF(c.x() + r * 0.62, c.y() - r * 0.34), r * 0.92, r * 0.92)
        p.fillPath(full.subtracted(bite), ink)


class Eyebrow(QWidget):
    """Dot de 6px + etiqueta mono em caixa alta."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        lay.addWidget(Dot(6, on=True))
        lay.addWidget(mono_label(text, 11, 0.18))
        lay.addStretch(1)


class PageHeader(QWidget):
    """``01 /`` + eyebrow + título display + lead (≤60ch)."""

    def __init__(self, num: str, eyebrow: str, title_html: str, lead: str = "") -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 10)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(14)
        accent = theme.color("accent").name()
        n = QLabel(f"<span style='color:{accent}'>{num}</span> /")
        n.setFont(theme.mono_font(11, 0.2, 500))
        n.setProperty("role", "meta")
        top.addWidget(n)
        top.addWidget(Eyebrow(eyebrow), 1)
        lay.addLayout(top)
        t = QLabel(title_html)
        t.setTextFormat(Qt.TextFormat.RichText)
        t.setFont(theme.display_font(30))
        t.setProperty("role", "title")
        lay.addWidget(t)
        if lead:
            ld = label(lead, "lead", theme.body_font(13.5), wrap=True)
            ld.setMaximumWidth(680)  # ~60ch
            ld.setMinimumHeight(ld.heightForWidth(680))
            lay.addWidget(ld)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.rule = QFrame()
        self.rule.setFixedHeight(1)
        lay.addSpacing(4)
        lay.addWidget(self.rule)
        self.restyle()

    def restyle(self) -> None:
        """Cor fora do QSS: tem de ser refeita quando o terreno troca."""
        self.rule.setStyleSheet(f"background: {theme.qss_color('line')}")


class Panel(QFrame):
    def __init__(self, title: str, meta: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QFrame()
        head.setObjectName("panelhead")
        head.setFixedHeight(38)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.addWidget(mono_label(title, 10.5, 0.2))
        hl.addStretch(1)
        self.meta = mono_label(meta, 10, 0.15)
        hl.addWidget(self.meta)
        outer.addWidget(head)
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(16, 14, 16, 16)
        self.body.setSpacing(10)
        outer.addWidget(body, 1)


class Notice(QFrame):
    """Aviso que não pode ficar escondido no código (borda de acento = estado)."""

    def __init__(self, eyebrow: str, html: str) -> None:
        super().__init__()
        self.setObjectName("notice")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(8)
        lay.addWidget(Eyebrow(eyebrow))
        t = label(html, None, theme.body_font(13.5), wrap=True)
        t.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(t)
        self.text = t
        self.restyle()

    def restyle(self) -> None:
        self.text.setStyleSheet(f"color: {theme.qss_color('ink')}")


def form_grid() -> QGridLayout:
    g = QGridLayout()
    g.setHorizontalSpacing(12)
    g.setVerticalSpacing(8)
    g.setColumnStretch(1, 1)
    return g


def form_row(grid: QGridLayout, row: int, text: str, widget: QWidget, hint: str = "") -> None:
    lb = label(text, None, theme.body_font(13))
    grid.addWidget(lb, row, 0)
    grid.addWidget(widget, row, 1)
    if hint:
        grid.addWidget(mono_label(hint, 10, 0.12, caps=False), row, 2)


class KeyValues(QWidget):
    """Linhas rótulo → valor mono, como a ficha de um equipamento."""

    def __init__(self) -> None:
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(9)
        self.grid.setColumnStretch(1, 1)
        self._values: dict[str, QLabel] = {}

    def set(self, key: str, value: str) -> None:
        if key not in self._values:
            row = len(self._values)
            self.grid.addWidget(label(key, None, theme.body_font(13)), row, 0, Qt.AlignmentFlag.AlignTop)
            v = label("", "value", theme.mono_font(11.5, 0.04, 500, caps=False))
            v.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            self.grid.addWidget(v, row, 1)
            self._values[key] = v
        self._values[key].setText(value)
        self._values[key].setToolTip(value)


class Metric(QWidget):
    """Rótulo mono 10px + valor display; unidade em serifa itálica (metric-value sub)."""

    def __init__(self, title: str, caps: bool = True) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.title = mono_label(title, 10, 0.2, caps=caps)
        lay.addWidget(self.title)
        self.value = QLabel("—")
        self.value.setTextFormat(Qt.TextFormat.RichText)
        self.value.setFont(theme.display_font(28, 400))
        self.value.setProperty("role", "value")
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.value)

    def set(self, value: float | None, unit: str, digits: int = 5) -> None:
        if value is None or not np.isfinite(value):
            self.value.setText("—")
            return
        text = format_eng(value, unit, digits)
        num, _, u = text.partition(" ")
        self.value.setText(f"{num} {theme.serif_span(u)}" if u else num)

    def set_title(self, t: str) -> None:
        self.title.setText(t)


class EngEdit(QLineEdit):
    """Campo numérico com prefixo SI ("10M", "500m", "100E9")."""

    valueChanged = Signal(float)

    def __init__(self, value: float = 0.0, unit: str = "", lo: float | None = None,
                 hi: float | None = None) -> None:
        super().__init__()
        self.unit = unit
        self.lo, self.hi = lo, hi
        self._value = value
        self.setFont(theme.mono_font(12, 0.03, 400, caps=False))
        self.setValue(value)
        self.editingFinished.connect(self._commit)
        self.textEdited.connect(self._check)

    def value(self) -> float:
        self._commit()
        return self._value

    def setValue(self, v: float) -> None:  # noqa: N802
        self._value = float(v)
        self.setText(format_eng(self._value, self.unit, 6) if self.unit else f"{self._value:g}")
        self._mark(False)

    def _parse(self) -> float | None:
        try:
            v = parse_eng(self.text())
        except ValueError:
            return None
        if (self.lo is not None and v < self.lo) or (self.hi is not None and v > self.hi):
            return None
        return v

    def _mark(self, bad: bool) -> None:
        self.setProperty("invalid", "true" if bad else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def _check(self) -> None:
        self._mark(self._parse() is None)

    def _commit(self) -> None:
        v = self._parse()
        if v is None:
            self._mark(True)
            return
        changed = v != self._value
        self.setValue(v)
        if changed:
            self.valueChanged.emit(v)


# ── gráficos ────────────────────────────────────────────────────────────
class SIAxis(pg.AxisItem):
    """Ticks com prefixo SI do valor real ("1k", "10M", "50p"), também em log."""

    def __init__(self, orientation: str) -> None:
        super().__init__(orientation)
        self.enableAutoSIPrefix(False)

    def tickStrings(self, values, scale, spacing):  # noqa: N802
        out = []
        lo, hi = self.range
        sparse = self.logMode and hi - lo > 1.2  # menos de uma década: rotula tudo
        for v in values:
            x = 10 ** v if self.logMode else v * scale
            if sparse and abs(v - round(v)) > 1e-6:
                mant = x / 10 ** np.floor(np.log10(x))
                if round(mant) not in (2, 5):  # só 2× e 5× entre as décadas
                    out.append("")
                    continue
            if abs(x) < 1e-300:
                out.append("0")
                continue
            s = format_eng(float(x), "_", 3).replace(" ", "").replace("_", "")
            out.append(s)
        return out


def si_axes() -> dict[str, SIAxis]:
    return {"left": SIAxis("left"), "bottom": SIAxis("bottom")}


def _label_style() -> dict[str, str]:
    return {"color": theme.color("ink-dim").name(), "font-family": theme.F_MONO, "font-size": "10px"}


def paint_plot(pw: pg.PlotWidget) -> None:
    """Só as cores: fundo, eixos, grade, moldura — e os rótulos que já existem.

    Chamada de novo a cada troca de terreno; o texto dos eixos vem do próprio
    AxisItem para não desfazer o que a página escreveu.
    """
    pw.setBackground(theme.color("bg"))
    item = pw.getPlotItem()
    item.showGrid(x=True, y=True, alpha=0.10)
    lab = _label_style()
    for side in ("left", "bottom"):
        ax = item.getAxis(side)
        ax.setPen(pg.mkPen(theme.color("line-strong")))
        ax.setTextPen(pg.mkPen(theme.color("ink-dim")))
        ax.setTickFont(theme.mono_font(10, 0.04, 400, caps=False))
        item.setLabel(side, ax.labelText, **lab)
    item.getViewBox().setBorder(pg.mkPen(theme.color("line")))


def style_plot(pw: pg.PlotWidget, y_label: str, y_unit: str, x_label: str = "Frequência",
               x_unit: str = "Hz") -> None:
    paint_plot(pw)
    item = pw.getPlotItem()
    lab = _label_style()
    item.setLabel("left", axis_text(y_label, y_unit), **lab)
    item.setLabel("bottom", axis_text(x_label, x_unit), **lab)


def axis_text(name: str, unit: str) -> str:
    return f"{name} · {unit}" if unit else name


def data_pen() -> pg.QtGui.QPen:
    """O dado medido: ciano --beam no escuro (ADR-004 proposto), tinta no claro."""
    return pg.mkPen(theme.color("data"), width=1.6)


def cursor_pen() -> pg.QtGui.QPen:
    """Cursor de leitura em acento: é o "valor lido" do espectrômetro."""
    return pg.mkPen(theme.color("accent"), width=1, style=Qt.PenStyle.DashLine)


def h_spacer() -> QWidget:
    w = QWidget()
    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return w
