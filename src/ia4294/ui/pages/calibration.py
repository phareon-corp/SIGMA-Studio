"""03 / Calibração — setup do adaptador, compensação do fixture, calibração de usuário.

Os procedimentos são dados (model/calibration.py). Aqui só existe um
assistente genérico de passos e o estado lido do instrumento.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QLabel, QStackedWidget,
    QVBoxLayout, QWidget,
)

from ...model import calibration as cal
from ...model.calibration import CalStep, Procedure
from ...model.config import ADAPTERS
from ...model.sweep import CompensationState
from .. import theme
from ..controller import Controller
from ..widgets import Dot, EngEdit, Notice, PageHeader, Panel, button, form_grid, form_row, label, mono_label


# ── peças ───────────────────────────────────────────────────────────────
class StageTab(QAbstractButton):
    """Seletor de procedimento: letra + título + quando fazer."""

    def __init__(self, letter: str, title: str, when: str) -> None:
        super().__init__()
        self.letter, self.title, self.when = letter, title, when
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(56)
        self.setAccessibleName(f"{letter} {title}")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(240, 56)

    def set_when(self, when: str) -> None:
        self.when = when
        self.update()

    def enterEvent(self, e) -> None:  # noqa: N802
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        on = self.isChecked()
        p.setPen(theme.color("line-strong") if on else theme.color("line"))
        p.setBrush(theme.color("bg-3") if on or self.underMouse() else theme.color("bg-2"))
        p.drawRoundedRect(r, 6, 6)
        if on:
            p.fillRect(r.left() + 1, r.bottom() - 1, r.width() - 1, 2, theme.color("accent"))
        p.setFont(theme.mono_font(11, 0.2, 500))
        p.setPen(theme.color("accent") if on else theme.color("ink-faint"))
        p.drawText(r.adjusted(14, 9, 0, 0), Qt.AlignmentFlag.AlignTop, self.letter)
        p.setFont(theme.body_font(14, 500))
        p.setPen(theme.color("ink") if on else theme.color("ink-dim"))
        p.drawText(r.adjusted(36, 7, -8, 0), Qt.AlignmentFlag.AlignTop, self.title)
        p.setFont(theme.mono_font(10, 0.1, 400, caps=False))
        p.setPen(theme.color("ink-dim") if on else theme.color("ink-faint"))
        p.drawText(r.adjusted(36, 31, -8, 0), Qt.AlignmentFlag.AlignTop, self.when)


class StepRow(QFrame):
    """Linha de passo; a barra de acento à esquerda marca o passo ativo."""

    def __init__(self, num: int, step: CalStep) -> None:
        super().__init__()
        self.active = False
        self.setFixedHeight(52)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 6, 12, 6)
        lay.setSpacing(12)
        lay.addWidget(mono_label(f"{num:02d}", 11, 0.2), 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label(step.key + (" · opcional" if step.optional else ""), "value", theme.body_font(14, 500)))
        col.addWidget(mono_label(f"envia {step.command}", 10, 0.12, caps=False))
        lay.addLayout(col, 1)
        self.badge = mono_label("", 10, 0.15)
        lay.addWidget(self.badge)

    def set_state(self, active: bool, status: str) -> None:
        self.active = active
        self.badge.setText(status)
        self.badge.setProperty("role", "error" if status in ("erro", "conferir") else ("value" if status else "meta"))
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), theme.color("bg-3") if self.active else theme.color("bg-2"))
        p.fillRect(0, self.height() - 1, self.width(), 1, theme.color("line"))
        if self.active:
            p.fillRect(0, 0, 2, self.height(), theme.color("accent"))
        p.end()
        super().paintEvent(ev)


class StateItem(QWidget):
    def __init__(self, name: str) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.dot = Dot(7)
        lay.addWidget(self.dot)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(mono_label(name, 9.5, 0.15))
        self.value = label("—", "value", theme.body_font(13, 500))
        col.addWidget(self.value)
        lay.addLayout(col)

    def set(self, text: str, on: bool | None) -> None:
        self.value.setText(text)
        self.dot.set_on(bool(on))


# ── assistente genérico ─────────────────────────────────────────────────
class Wizard(QWidget):
    """Lista de passos à esquerda, passo atual à direita."""

    finished = Signal(str)  # chave do procedimento

    def __init__(self, ctl: Controller, provider: Callable[[], Procedure],
                 extra: QWidget | None = None) -> None:
        super().__init__()
        self.ctl = ctl
        self.provider = provider
        self.proc = provider()
        self.index = 0
        self.status: dict[str, str] = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        col = QVBoxLayout()
        col.setSpacing(12)
        left = Panel("Passos")
        left.body.setContentsMargins(0, 0, 0, 0)
        left.body.setSpacing(0)
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(0)
        left.body.addLayout(self.rows_box)
        col.addWidget(left)
        if extra is not None:
            col.addWidget(extra)
        col.addStretch(1)
        holder = QWidget()
        holder.setLayout(col)
        holder.setFixedWidth(330)
        col.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(holder)

        right = QVBoxLayout()
        right.setSpacing(12)
        det = Panel("Passo atual")
        self.step_title = QLabel()
        self.step_title.setFont(theme.display_font(22))
        self.step_title.setProperty("role", "title")
        det.body.addWidget(self.step_title)
        self.step_text = label("", "lead", theme.body_font(13.5), wrap=True)
        det.body.addWidget(self.step_text)
        self.step_cmd = mono_label("", 11, 0.06, "value", caps=False)
        self.step_cmd.setWordWrap(True)
        det.body.addWidget(self.step_cmd)
        b = QHBoxLayout()
        self.run_btn = button("Executar", "primary")
        self.back_btn = button("Voltar")
        self.skip_btn = button("Pular")
        self.abort_btn = button("Abortar")
        for w in (self.run_btn, self.back_btn, self.skip_btn, self.abort_btn):
            b.addWidget(w)
        b.addStretch(1)
        det.body.addLayout(b)
        self.result = label("", "meta", theme.mono_font(11, 0.02, 400, caps=False), wrap=True)
        det.body.addWidget(self.result)
        right.addWidget(det)
        self.blocked = Notice("indisponível", "")
        self.blocked.setVisible(False)
        right.addWidget(self.blocked)
        self.notes = label("", "meta", theme.body_font(12.5), wrap=True)
        self.notes.setTextFormat(Qt.TextFormat.RichText)
        right.addWidget(self.notes)
        right.addStretch(1)
        lay.addLayout(right, 1)

        self.run_btn.clicked.connect(self.run_step)
        self.back_btn.clicked.connect(lambda: self.goto(self.index - 1))
        self.skip_btn.clicked.connect(lambda: self.goto(self.index + 1))
        self.abort_btn.clicked.connect(ctl.abort)
        ctl.busy_changed.connect(lambda *_: self._enable())
        ctl.connection_changed.connect(lambda *_: self._enable())
        self.rebuild()

    # ── estrutura ───────────────────────────────────────────────────────
    def rebuild(self, keep_status: bool = False) -> None:
        self.proc = self.provider()
        while self.rows_box.count():
            w = self.rows_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.rows = [StepRow(i + 1, s) for i, s in enumerate(self.proc.steps)]
        for r in self.rows:
            self.rows_box.addWidget(r)
        if not keep_status:
            self.status.clear()
        self.blocked.setVisible(not self.proc.available)
        if not self.proc.available:
            self.blocked.text.setText(self.proc.unavailable_reason)
        self.notes.setText("<br>".join(f"— {n}" for n in self.proc.notes))
        self.goto(0)

    def refresh(self) -> None:
        """Opções mudaram (valores dos padrões): só os textos."""
        self.proc = self.provider()
        self.goto(self.index)

    def goto(self, i: int) -> None:
        steps = self.proc.steps
        self.index = max(0, min(i, len(steps)))
        for j, r in enumerate(self.rows):
            r.set_state(j == self.index, self.status.get(steps[j].key, ""))
        if self.index < len(steps):
            s = steps[self.index]
            self.step_title.setText(f"Passo {self.index + 1:02d} — {s.key}")
            self.step_text.setText(s.instruction)
            pre = f"   antes: {self.proc.pre}" if self.index == 0 and self.proc.pre else ""
            self.step_cmd.setText(f"comando: {s.command}{pre}")
        else:
            self.step_title.setText("Concluído")
            self.step_text.setText("Todos os passos foram executados. O estado lido do instrumento "
                                   "aparece na faixa acima.")
            self.step_cmd.setText("")
        self._enable()

    # ── execução ────────────────────────────────────────────────────────
    def run_step(self) -> None:
        if self.index >= len(self.proc.steps):
            return
        step = self.proc.steps[self.index]
        proc = self.proc
        first = self.index == 0
        cfg = self.ctl.config
        if proc.key == "fixture" and cfg.osc_mode == "VOLT" and cfg.osc_level > cal.COMP_MAX_OSC_V:
            cfg = replace(cfg, osc_level=cal.COMP_MAX_OSC_V)

        def job(ctx):
            refused = []
            if first and proc.key == "fixture":
                refused = [r for r in ctx.driver.apply(cfg) if not r.ok]
            if first and proc.pre and not refused:
                rep = ctx.driver.block("padrões", proc.pre)
                if not rep.ok:
                    refused.append(rep)
            if refused:
                return refused, [], 0.0
            errs, secs = ctx.driver.cal_step(step.command, step.measures, step.estimate_s,
                                             ctx.abort, ctx.progress)
            return [], errs, secs

        def done(r):
            refused, errs, secs = r
            if refused:
                self.status[step.key] = "erro"
                self.result.setText("configuração recusada — " + " · ".join(
                    f"{b.name}: " + ", ".join(cal.explain_error(c, m) for c, m in b.errors) for b in refused))
                self.goto(self.index)
            elif errs:
                self.status[step.key] = "erro"
                self.result.setText(f"{step.command}: OUTPERRO? → " +
                                    "; ".join(cal.explain_error(c, m) for c, m in errs))
                self.goto(self.index)
            elif step.measures and step.estimate_s >= 60 and secs < 3:
                self.status[step.key] = "conferir"
                self.result.setText(f"o 4294A declarou fim em {secs:.1f} s — rápido demais para {step.key}. "
                                    "Confira na tela se o rótulo mostra [DONE] antes de seguir.")
                self.goto(self.index + 1)
            else:
                self.status[step.key] = "ok"
                self.result.setText(f"{step.key}: {step.command} concluído em {secs:.1f} s · OUTPERRO? = 0")
                self.goto(self.index + 1)
            if self.index >= len(self.proc.steps):
                self.finished.emit(proc.key)

        def fail(e, aborted):
            self.result.setText("abortado — HOLD enviado" if aborted else f"falhou: {e}")

        self.result.setText(f"executando {step.command}…")
        self.ctl.run(f"calibração {step.key}", job, done, fail)

    def _enable(self) -> None:
        ok = self.ctl.connected and not self.ctl.busy and self.proc.available
        steps = self.proc.steps
        inside = self.index < len(steps)
        self.run_btn.setEnabled(ok and inside)
        self.run_btn.setText("Medir" if inside and steps[self.index].measures else "Executar")
        self.back_btn.setEnabled(not self.ctl.busy and self.index > 0)
        self.skip_btn.setVisible(inside and steps[self.index].optional)
        self.skip_btn.setEnabled(not self.ctl.busy)
        self.abort_btn.setEnabled(self.ctl.busy)


# ── a página ────────────────────────────────────────────────────────────
class CalibrationPage(QWidget):
    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        self.adapter = ctl.config.adapter
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        lay.addWidget(PageHeader(
            "03", "Calibração", "Calibração 16451B",
            "Primeiro o setup do adaptador (uma vez), depois a compensação do fixture a cada montagem. "
            "Calibração de usuário só existe com 42942A ou 42941A."))

        # estado lido do instrumento
        st = QFrame()
        st.setObjectName("panel")
        sl = QHBoxLayout(st)
        sl.setContentsMargins(14, 10, 14, 10)
        sl.setSpacing(22)
        self.s_adapter = StateItem("adaptador · E4TP")
        self.s_open = StateItem("fixture OPEN")
        self.s_short = StateItem("fixture SHORT")
        self.s_load = StateItem("fixture LOAD")
        self.s_user = StateItem("cal. usuário · CALST")
        for w in (self.s_adapter, self.s_open, self.s_short, self.s_load, self.s_user):
            sl.addWidget(w)
        sl.addStretch(1)
        self.read_btn = button("Ler do instrumento", small=True)
        sl.addWidget(self.read_btn)
        lay.addWidget(st)

        # seletor de procedimento
        tabs = QHBoxLayout()
        tabs.setSpacing(10)
        self.tab_a = StageTab("A", "Setup do adaptador", "uma vez · PHASE COMP")
        self.tab_b = StageTab("B", "Compensação do fixture", "a cada montagem · OPEN SHORT LOAD")
        self.tab_c = StageTab("C", "Calibração de usuário", "só 42942A / 42941A")
        self.group = QButtonGroup(self)
        for i, t in enumerate((self.tab_a, self.tab_b, self.tab_c)):
            self.group.addButton(t, i)
            tabs.addWidget(t, 1)
        lay.addLayout(tabs)

        # opções do fixture
        opts = Panel("Padrões do fixture", "DCAL…")
        top = QHBoxLayout()
        self.include_load = QCheckBox("Incluir LOAD (teclas invertidas)")
        top.addWidget(self.include_load)
        top.addStretch(1)
        opts.body.addLayout(top)
        g = form_grid()
        self.short_r = EngEdit(0.0, "Ω")
        self.short_l = EngEdit(0.0, "H")
        self.load_c = EngEdit(10e-12, "F", 0, 1)
        self.load_g = EngEdit(0.0, "S", 0, 1e3)
        form_row(g, 0, "SHORT R", self.short_r)
        form_row(g, 1, "SHORT L", self.short_l)
        form_row(g, 2, "Carga Cp", self.load_c)
        form_row(g, 3, "Carga G", self.load_g)
        opts.body.addLayout(g)
        self.load_notice = Notice(
            "16451B · caminho LOAD",
            "O 4294A define padrões como <b>R-L série</b>; o 16451B precisa de <b>C-G paralelo</b> (p. 136). "
            "Com LOAD:<br>"
            "• eletrodos em <b>OPEN</b> → <code>COMC</code> (tecla LOAD)<br>"
            "• <b>padrão de carga</b> → <code>COMA</code> (tecla OPEN)<br>"
            "• <code>DCALLOADR 100E9</code> e <code>DCALLOADL 0</code> descrevem o OPEN<br>"
            "• <code>DCALOPENC</code> / <code>DCALOPENG</code> recebem o Cp e o G da carga")
        opts.body.addWidget(self.load_notice)

        self.stack = QStackedWidget()
        self.w_adapter = Wizard(ctl, lambda: cal.adapter_setup(self.ctl.config.adapter))
        self.w_fixture = Wizard(ctl, self._fixture_proc, opts)
        self.w_user = Wizard(ctl, lambda: cal.user_calibration(self.adapter))
        for w in (self.w_adapter, self.w_fixture, self.w_user):
            self.stack.addWidget(w)
        lay.addWidget(self.stack, 1)

        # sinais
        self.group.idClicked.connect(self.stack.setCurrentIndex)
        self.include_load.toggled.connect(self._load_toggled)
        for w in (self.short_r, self.short_l, self.load_c, self.load_g):
            w.valueChanged.connect(lambda _v: self.w_fixture.refresh())
        self.read_btn.clicked.connect(self.read_state)
        for w in (self.w_adapter, self.w_fixture, self.w_user):
            w.finished.connect(lambda _k: self.read_state())
        ctl.compensation_changed.connect(self.show_comp)
        ctl.connection_changed.connect(self._on_connection)
        ctl.busy_changed.connect(lambda *_: self.read_btn.setEnabled(ctl.connected and not ctl.busy))

        self.tab_b.setChecked(True)
        self.stack.setCurrentIndex(1)
        self._load_toggled(False)
        self.show_comp(ctl.compensation)
        self.read_btn.setEnabled(False)

    def _fixture_proc(self) -> Procedure:
        return cal.fixture_compensation(self.include_load.isChecked(), self.short_r.value(),
                                        self.short_l.value(), self.load_c.value(), self.load_g.value())

    def _load_toggled(self, on: bool) -> None:
        self.load_c.setEnabled(on)
        self.load_g.setEnabled(on)
        self.load_notice.setVisible(on)
        self.w_fixture.rebuild()

    def _on_connection(self, connected: bool, _d: str) -> None:
        self.read_btn.setEnabled(connected and not self.ctl.busy)
        if connected:
            self.read_state()

    def read_state(self) -> None:
        def job(ctx):
            d = ctx.driver
            return d.adapter(), d.comp_state(), d.user_cal_on()

        def done(r):
            adapter, comp, user = r
            self.adapter = adapter
            self.s_adapter.set(ADAPTERS.get(adapter, adapter), adapter == self.ctl.config.adapter)
            self.ctl.set_compensation(comp)
            self.s_user.set("indisponível" if adapter not in cal.USER_CAL_ADAPTERS else
                            ("?" if user is None else ("ON" if user else "OFF")), user)
            self.tab_c.set_when("só 42942A / 42941A" if adapter not in cal.USER_CAL_ADAPTERS
                                else "kit padrão · OPEN SHORT LOAD")
            self.w_user.rebuild(keep_status=True)

        self.ctl.run("ler calibração", job, done)

    def show_comp(self, st: CompensationState) -> None:
        f = lambda v: "?" if v is None else ("ON" if v else "OFF")  # noqa: E731
        self.s_open.set(f(st.open), st.open)
        self.s_short.set(f(st.short), st.short)
        self.s_load.set(f(st.load), st.load)

