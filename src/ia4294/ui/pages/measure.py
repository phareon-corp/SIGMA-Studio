"""02 / Medida — todos os parâmetros, perfis JSON, envio com OUTPERRO? por bloco."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QInputDialog, QMessageBox, QPlainTextEdit,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ... import paths
from ...model.config import ADAPTERS, DC_RANGES, F_MAX, F_MIN, SWEEP_TYPES_FOR, MeasurementConfig, bias_range, osc_range
from ...model.params import MEAS_PARAMS
from .. import theme
from ..controller import Controller
from ...model.units import format_eng
from ..widgets import EngEdit, Metric, Notice, PageHeader, Panel, button, form_grid, form_row, label, mono_label


def _combo(items: list[tuple[str, str]]) -> QComboBox:
    c = QComboBox()
    for data, text in items:
        c.addItem(text, data)
    return c


def _set(c: QComboBox, data: str) -> None:
    i = c.findData(data)
    if i >= 0:
        c.setCurrentIndex(i)


# faixa inicial de STAR/STOP ao trocar de parâmetro, por (SWPP, modo)
_DEFAULT_RANGE = {
    ("FREQ", ""): (1e3, 10e6),
    ("OLEV", "VOLT"): (0.01, 0.5), ("OLEV", "CURR"): (1e-3, 10e-3),
    ("DCB", "VOLT"): (0.0, 10.0), ("DCB", "CURR"): (0.0, 10e-3),
}

BIAS_WARNING = (
    "Desligue o bias (<b>DCO OFF</b>) antes de conectar ou desconectar qualquer acessório: o manual "
    "do 4294A avisa que o bias pode <b>destruir o dispositivo</b> (cap. 4). "
    "O envelope tensão × corrente do bias não é retangular — confira a Figura 10-1 antes de combinar "
    "tensão alta com corrente alta. Que o <b>16451B aceita bias DC</b> precisa ser confirmado no "
    "manual do fixture, que ainda não temos aqui.")


def _spin(lo: int, hi: int, v: int) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(v)
    return s


class MeasurePage(QWidget):
    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(PageHeader(
            "02", "Medida", "Parâmetros de medida",
            "Cada grupo vira um bloco de mnemônicos HP separados por ponto e vírgula. "
            "Depois de cada bloco o app pergunta OUTPERRO? e mostra o erro aqui."))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        scroll.setWidget(inner)
        grid = QGridLayout(inner)
        grid.setContentsMargins(0, 0, 8, 0)
        grid.setSpacing(14)
        outer.addWidget(scroll, 1)

        # estado / fixture
        p = Panel("Estado / fixture", "E4TP · CALP")
        g = form_grid()
        self.adapter = _combo([(k, f"{v}  ·  E4TP {k}") for k, v in ADAPTERS.items()])
        form_row(g, 0, "Adaptador", self.adapter, "16451B → 4TP 1M")
        self.calp = _combo([("FIXED", "FIXED"), ("USER", "USER")])
        form_row(g, 1, "Pontos de compensação", self.calp, "CALP")
        p.body.addLayout(g)
        self.pres_btn = button("PRES — reset do instrumento", small=True)
        p.body.addWidget(self.pres_btn)
        p.body.addStretch(1)  # conteúdo no topo, mesmo com o vizinho mais alto
        grid.addWidget(p, 0, 0)

        # medida
        p = Panel("Medida", "MEAS · FMT")
        g = form_grid()
        self.meas = _combo([(k, f"{v.label}  ·  {k}") for k, v in MEAS_PARAMS.items()])
        form_row(g, 0, "Parâmetro (A-B)", self.meas)
        fmts = [("LINY", "linear · LINY"), ("LOGY", "log · LOGY")]
        self.fmt_a = _combo(fmts)
        self.fmt_b = _combo(fmts)
        form_row(g, 1, "Formato traço A", self.fmt_a)
        form_row(g, 2, "Formato traço B", self.fmt_b)
        p.body.addLayout(g)
        p.body.addStretch(1)  # conteúdo no topo, mesmo com o vizinho mais alto
        grid.addWidget(p, 0, 1)

        # varredura
        p = Panel("Varredura", "SWPP · SWPT")
        self.sweep_panel = p
        g = form_grid()
        self.swpp = _combo([("FREQ", "frequência · FREQ"), ("DCB", "bias DC · DCB"),
                            ("OLEV", "nível do oscilador · OLEV")])
        form_row(g, 0, "Varre · SWPP", self.swpp)
        self.cw = EngEdit(1e6, "Hz", F_MIN, F_MAX)
        self.cw_hint = mono_label("", 10, 0.12, caps=False)
        form_row(g, 1, "Frequência fixa · CWFREQ", self.cw)
        g.addWidget(self.cw_hint, 1, 2)
        self.swpt = _combo([("LOG", "log · LOG"), ("LIN", "linear · LIN"), ("LIST", "lista · LIST")])
        form_row(g, 2, "Tipo · SWPT", self.swpt)
        self.start = EngEdit(1e3, "Hz", F_MIN, F_MAX)
        self.stop = EngEdit(10e6, "Hz", F_MIN, F_MAX)
        self.range_hint = mono_label("", 10, 0.12, caps=False)
        form_row(g, 3, "Início · STAR", self.start)
        g.addWidget(self.range_hint, 3, 2)
        form_row(g, 4, "Fim · STOP", self.stop)
        self.points = _spin(2, 801, 201)
        form_row(g, 5, "Pontos · POIN", self.points)
        self.swed = _combo([("UP", "crescente · UP"), ("DOWN", "decrescente · DOWN")])
        form_row(g, 6, "Direção · SWED", self.swed)
        p.body.addLayout(g)
        p.body.addStretch(1)  # conteúdo no topo, mesmo com o vizinho mais alto
        grid.addWidget(p, 1, 0)
        self._ranges: dict[tuple[str, str], tuple[float, float]] = {}
        self._range_key = ("FREQ", "")

        # fonte
        p = Panel("Fonte", "POWMOD · DC")
        g = form_grid()
        self.powmod = _combo([("VOLT", "tensão · VOLT"), ("CURR", "corrente · CURR")])
        form_row(g, 0, "Oscilador", self.powmod)
        self.powe = EngEdit(0.5, "V", *osc_range("VOLT"))
        self.powe_hint = mono_label("5 mV–1 V", 10, 0.12, caps=False)
        form_row(g, 1, "Nível · POWE", self.powe)
        g.addWidget(self.powe_hint, 1, 2)
        self.dco = QCheckBox("Bias DC ligado · DCO")
        form_row(g, 2, "", self.dco)
        self.dcmode = _combo([("VOLT", "tensão · DCMOD VOLT"), ("CURR", "corrente · DCMOD CURR")])
        form_row(g, 3, "Fonte de bias", self.dcmode)
        self.dclevel = EngEdit(0.0, "V", *bias_range("VOLT"))
        self.dclevel_hint = mono_label("±40 V / ±100 mA", 10, 0.12, caps=False)
        form_row(g, 4, "Nível · DCV/DCI", self.dclevel)
        g.addWidget(self.dclevel_hint, 4, 2)
        self.dcrng = _combo([(k, f"{v} · DCRNG {k}") for k, v in DC_RANGES.items()])
        form_row(g, 5, "Faixa de corrente", self.dcrng, "erro 137 → suba")
        p.body.addLayout(g)
        self.bias_notice = Notice("bias DC · segurança", BIAS_WARNING)
        p.body.addWidget(self.bias_notice)
        self.bias_off_btn = button("Desligar bias agora · DCO OFF", small=True)
        p.body.addWidget(self.bias_off_btn)
        p.body.addStretch(1)  # conteúdo no topo, mesmo com o vizinho mais alto
        grid.addWidget(p, 1, 1)

        # exatidão
        p = Panel("Exatidão", "BWFACT · AVER · PAVER")
        g = form_grid()
        self.bw = _spin(1, 5, 3)
        form_row(g, 0, "Banda · BWFACT", self.bw, "1 rápido · 5 preciso")
        self.aver = QCheckBox("Média de varredura · AVER")
        form_row(g, 1, "", self.aver)
        self.averfact = _spin(1, 256, 4)
        form_row(g, 2, "AVERFACT", self.averfact, "dispara NUMG n")
        self.paver = QCheckBox("Média por ponto · PAVER")
        form_row(g, 3, "", self.paver)
        self.paverfact = _spin(1, 256, 4)
        form_row(g, 4, "PAVERFACT", self.paverfact)
        p.body.addLayout(g)
        p.body.addStretch(1)  # conteúdo no topo, mesmo com o vizinho mais alto
        grid.addWidget(p, 2, 0)

        # disparo + estimativa
        p = Panel("Disparo", "TRGS")
        g = form_grid()
        self.trgs = _combo([("INT", "interno · INT"), ("BUS", "GPIB · BUS"), ("EXT", "externo · EXT"),
                            ("MAN", "manual · MAN")])
        form_row(g, 0, "Fonte", self.trgs)
        p.body.addLayout(g)
        self.estimate = Metric("Tempo estimado da varredura")
        p.body.addWidget(self.estimate)
        p.body.addWidget(label("Estimativa só para a barra de progresso. O fim real vem do status byte "
                               "do instrumento, nunca de uma espera fixa.", "meta", theme.body_font(12), wrap=True))
        p.body.addStretch(1)  # conteúdo no topo, mesmo com o vizinho mais alto
        grid.addWidget(p, 2, 1)

        # comandos
        p = Panel("Mensagens que serão enviadas", "uma por bloco")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(theme.mono_font(11, 0.02, 400, caps=False))
        self.preview.setFixedHeight(130)
        p.body.addWidget(self.preview)
        self.result = label("", "meta", theme.mono_font(11, 0.02, 400, caps=False), wrap=True)
        p.body.addWidget(self.result)
        p.body.addStretch(1)  # conteúdo no topo, mesmo com o vizinho mais alto
        grid.addWidget(p, 3, 0, 1, 2)

        # barra de ações
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 14, 0, 0)
        self.profile = QComboBox()
        self.profile.setMinimumWidth(200)
        self.load_btn = button("Carregar perfil")
        self.save_btn = button("Salvar perfil")
        self.import_btn = button("Abrir JSON…", small=True)
        self.apply_btn = button("Aplicar ao instrumento", "primary")
        bar.addWidget(label("Perfil", None, theme.body_font(13)))
        bar.addWidget(self.profile)
        bar.addWidget(self.load_btn)
        bar.addWidget(self.save_btn)
        bar.addWidget(self.import_btn)
        bar.addStretch(1)
        bar.addWidget(self.apply_btn)
        outer.addLayout(bar)

        # sinais
        self.swpp.currentIndexChanged.connect(self._sweep_param_changed)
        for w in (self.adapter, self.calp, self.meas, self.fmt_a, self.fmt_b, self.swpt, self.swed,
                  self.powmod, self.dcmode, self.trgs, self.dcrng):
            w.currentIndexChanged.connect(self._changed)
        for w in (self.points, self.bw, self.averfact, self.paverfact):
            w.valueChanged.connect(self._changed)
        for w in (self.dco, self.aver, self.paver):
            w.toggled.connect(self._changed)
        for w in (self.start, self.stop, self.powe, self.cw, self.dclevel):
            w.valueChanged.connect(self._changed)
        self.powmod.currentIndexChanged.connect(self._units)
        self.dcmode.currentIndexChanged.connect(self._units)
        self.powmod.currentIndexChanged.connect(self._sweep_param_changed)
        self.dcmode.currentIndexChanged.connect(self._sweep_param_changed)
        self.bias_off_btn.clicked.connect(self.bias_off)
        self.apply_btn.clicked.connect(self.apply)
        self.save_btn.clicked.connect(self.save_profile)
        self.load_btn.clicked.connect(self.load_profile)
        self.import_btn.clicked.connect(self.import_profile)
        self.pres_btn.clicked.connect(self.preset)
        ctl.busy_changed.connect(lambda *_: self._enable())
        ctl.connection_changed.connect(lambda *_: self._enable())

        self.show_config(ctl.config)
        self.refresh_profiles()
        self._enable()

    # ── config ↔ widgets ────────────────────────────────────────────────
    def read_config(self) -> MeasurementConfig:
        return MeasurementConfig(
            adapter=self.adapter.currentData(), cal_point=self.calp.currentData(),
            meas=self.meas.currentData(), fmt_a=self.fmt_a.currentData(), fmt_b=self.fmt_b.currentData(),
            sweep_param=self.swpp.currentData(),
            sweep_type=self.swpt.currentData(), start=self.start.value(), stop=self.stop.value(),
            points=self.points.value(), direction=self.swed.currentData(),
            osc_mode=self.powmod.currentData(), osc_level=self.powe.value(), cw_freq_hz=self.cw.value(),
            dc_bias_on=self.dco.isChecked(), dc_bias_mode=self.dcmode.currentData(),
            dc_bias_level=self.dclevel.value(), dc_range=self.dcrng.currentData(), bw=self.bw.value(),
            averaging_on=self.aver.isChecked(), averaging_factor=self.averfact.value(),
            point_avg_on=self.paver.isChecked(), point_avg_factor=self.paverfact.value(),
            trigger_source=self.trgs.currentData(),
        )

    def show_config(self, c: MeasurementConfig) -> None:
        self._loading = True
        _set(self.adapter, c.adapter)
        _set(self.calp, c.cal_point)
        _set(self.meas, c.meas)
        _set(self.fmt_a, c.fmt_a)
        _set(self.fmt_b, c.fmt_b)
        _set(self.powmod, c.osc_mode)
        _set(self.dcmode, c.dc_bias_mode)
        _set(self.swpp, c.sweep_param)
        self._apply_axis()
        _set(self.swpt, c.sweep_type)
        self.start.setValue(c.start)
        self.stop.setValue(c.stop)
        self.points.setValue(c.points)
        _set(self.swed, c.direction)
        self.powe.setValue(c.osc_level)
        self.cw.setValue(c.cw_freq_hz)
        self.dco.setChecked(c.dc_bias_on)
        _set(self.dcrng, c.dc_range)
        self.dclevel.setValue(c.dc_bias_level)
        self.bw.setValue(c.bw)
        self.aver.setChecked(c.averaging_on)
        self.averfact.setValue(c.averaging_factor)
        self.paver.setChecked(c.point_avg_on)
        self.paverfact.setValue(c.point_avg_factor)
        _set(self.trgs, c.trigger_source)
        self._loading = False
        self._units()
        self._changed()

    def _units(self) -> None:
        mode = self.powmod.currentData()
        self.powe.unit = "V" if mode == "VOLT" else "A"
        self.powe.lo, self.powe.hi = osc_range(mode)
        self.powe.setValue(max(self.powe.lo, min(self.powe._value, self.powe.hi)))
        dmode = self.dcmode.currentData()
        self.dclevel.unit = "V" if dmode == "VOLT" else "A"
        self.dclevel.lo, self.dclevel.hi = bias_range(dmode)
        self.dclevel.setValue(max(self.dclevel.lo, min(self.dclevel._value, self.dclevel.hi)))

    # ── parâmetro varrido ───────────────────────────────────────────────
    def _axis_key(self) -> tuple[str, str]:
        p = self.swpp.currentData()
        mode = {"FREQ": "", "OLEV": self.powmod.currentData(), "DCB": self.dcmode.currentData()}[p]
        return (p, mode)

    def _apply_axis(self) -> None:
        """Unidade e limites de STAR/STOP, tipos permitidos, campos que a varredura comanda."""
        p, mode = key = self._axis_key()
        if p == "FREQ":
            unit, (lo, hi) = "Hz", (F_MIN, F_MAX)
        elif p == "OLEV":
            unit, (lo, hi) = ("V" if mode == "VOLT" else "A"), osc_range(mode)
        else:
            unit, (lo, hi) = ("V" if mode == "VOLT" else "A"), bias_range(mode)
        for e in (self.start, self.stop):
            e.unit, e.lo, e.hi = unit, lo, hi
        self.range_hint.setText(f"{format_eng(lo, unit)} – {format_eng(hi, unit)}")
        self.sweep_panel.meta.setText(f"SWPP {p} · STAR/STOP em {unit}")
        self._range_key = key

        # log e list só varrendo frequência (cap. 10)
        allowed = SWEEP_TYPES_FOR[p]
        model = self.swpt.model()
        for i in range(self.swpt.count()):
            model.item(i).setEnabled(self.swpt.itemData(i) in allowed)
        if self.swpt.currentData() not in allowed:
            _set(self.swpt, "LIN")

        fixed = p != "FREQ"
        self.cw.setEnabled(fixed)
        self.cw_hint.setText("mede todos os pontos aqui" if fixed else "só em DCB / OLEV")
        self.cw_hint.setProperty("role", "value" if fixed else "meta")
        self.cw_hint.style().unpolish(self.cw_hint)
        self.cw_hint.style().polish(self.cw_hint)
        # o nível que a varredura comanda não é um campo fixo
        self.powe.setEnabled(p != "OLEV")
        self.powe_hint.setText("varrido por STAR/STOP" if p == "OLEV" else
                               ("5 mV–1 V" if self.powmod.currentData() == "VOLT" else "200 µA–20 mA"))
        self.dclevel.setEnabled(p != "DCB")
        self.dclevel_hint.setText("varrido por STAR/STOP" if p == "DCB" else
                                  ("±40 V" if self.dcmode.currentData() == "VOLT" else "±100 mA"))
        if p == "DCB":
            self.dco.setChecked(True)
        self.dco.setEnabled(p != "DCB")

    def _sweep_param_changed(self, *_a) -> None:
        if self._loading:
            return
        old = self._range_key
        self._ranges[old] = (self.start._value, self.stop._value)
        self._loading = True
        self._apply_axis()
        new = self._range_key
        if new != old:
            a, b = self._ranges.get(new, _DEFAULT_RANGE[new])
            self.start.setValue(a)
            self.stop.setValue(b)
        self._loading = False
        self._changed()

    def bias_off(self) -> None:
        def done(rep):
            self._show_result("DCO OFF enviado — bias desligado" if rep.ok else
                              "DCO OFF: " + ", ".join(f"{c} {m}" for c, m in rep.errors), error=not rep.ok)

        self.ctl.run("DCO OFF", lambda ctx: ctx.driver.block("bias", "DCO OFF"), done)

    def _changed(self, *_a) -> None:
        if self._loading:
            return
        cfg = self.read_config()
        problems = cfg.validate()
        self.preview.setPlainText("\n".join(f"{n:<10} {m}" for n, m in cfg.command_blocks()))
        # tempo aprendido das varreduras anteriores, se houver
        self.estimate.set(self.ctl.worker.timer.estimate(cfg), "s", 3)
        self.averfact.setEnabled(cfg.averaging_on)
        self.paverfact.setEnabled(cfg.point_avg_on)
        self.bias_notice.setVisible(cfg.bias_active)
        self.dcrng.setEnabled(cfg.bias_active)
        if problems:
            self._show_result("; ".join(problems), error=True)
        else:
            self._show_result("")
            self.ctl.set_config(cfg)

    def _show_result(self, text: str, error: bool = False) -> None:
        self.result.setText(text)
        self.result.setProperty("role", "error" if error else "meta")
        self.result.style().unpolish(self.result)
        self.result.style().polish(self.result)

    # ── ações ───────────────────────────────────────────────────────────
    def apply(self) -> None:
        cfg = self.read_config()
        problems = cfg.validate()
        if problems:
            self._show_result("; ".join(problems), error=True)
            return
        self.ctl.set_config(cfg)

        def done(reports):
            bad = [r for r in reports if not r.ok]
            if bad:
                self._show_result(" · ".join(f"{r.name}: " + ", ".join(f"{c} {m}" for c, m in r.errors)
                                             for r in bad), error=True)
            else:
                self._show_result(f"aplicado — {len(reports)} blocos, OUTPERRO? = 0 em todos")

        self.ctl.run("aplicar configuração", lambda ctx: ctx.driver.apply(cfg), done)

    def preset(self) -> None:
        if QMessageBox.question(self, "PRES", "Resetar o 4294A para o estado de fábrica?") != QMessageBox.StandardButton.Yes:
            return
        self.ctl.run("PRES", lambda ctx: ctx.driver.block("PRES", "PRES"),
                     lambda r: self._show_result("PRES enviado" if r.ok else f"PRES: {r.errors}", not r.ok))

    def refresh_profiles(self) -> None:
        self.profile.clear()
        for p in sorted(paths.profiles_dir().glob("*.json")):
            self.profile.addItem(p.stem, str(p))

    def save_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "Salvar perfil", "Nome do perfil:", text=self.profile.currentText())
        if not ok or not name.strip():
            return
        safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in name.strip())
        self.read_config().save(paths.profiles_dir() / f"{safe}.json")
        self.refresh_profiles()
        self.profile.setCurrentText(safe)
        self._show_result(f"perfil salvo em {paths.profiles_dir() / (safe + '.json')}")

    def load_profile(self) -> None:
        path = self.profile.currentData()
        if path:
            self._load(path)

    def import_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Abrir perfil", str(paths.profiles_dir()), "Perfil (*.json)")
        if path:
            self._load(path)

    def _load(self, path: str) -> None:
        from pathlib import Path

        try:
            cfg = MeasurementConfig.load(Path(path))
        except (OSError, ValueError, TypeError) as exc:
            self._show_result(f"perfil ilegível: {exc}", error=True)
            return
        self.show_config(cfg)
        self._show_result(f"perfil carregado: {Path(path).name} — clique em Aplicar para enviar")

    def _enable(self) -> None:
        ok = self.ctl.connected and not self.ctl.busy
        self.apply_btn.setEnabled(ok)
        self.pres_btn.setEnabled(ok)
        self.bias_off_btn.setEnabled(ok)
