"""01 / Conexão — porta, endereço, *IDN?, estado da interface, probe."""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPlainTextEdit, QScrollArea, QSpinBox, QVBoxLayout, QWidget

from ... import paths
from ...instrument.capabilities import Capabilities
from ...instrument.probe import probe
from ...transport.links import guess_ar488_port, list_serial_ports
from .. import theme
from ..controller import Controller
from ..widgets import KeyValues, Notice, PageHeader, Panel, button, form_grid, form_row, label

SIM = "SIMULADOR"
SYNC_OPTIONS = [("spoll", "serial poll do status byte (++spoll)"),
                ("opc_query", "*OPC? com ++read_tmo_ms elevado")]


class ConnectionPage(QWidget):
    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        lay.addWidget(PageHeader(
            "01", "Conexão", "Interface GPIB",
            "AR488 num Arduino Mega 2560, 115 200 8N1. A placa reseta ao abrir a porta; "
            "o app espera o boot, descarta o banner e configura ++addr, ++eos 2, ++eoi 1 e ++read_tmo_ms."))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        scroll.setWidget(inner)
        row = QHBoxLayout(inner)
        row.setContentsMargins(0, 0, 8, 0)
        row.setSpacing(16)
        lay.addWidget(scroll, 1)

        # ── porta ──
        left = Panel("Porta", "COM*" if paths.WINDOWS else "/dev/ttyACM*")
        g = form_grid()
        self.port = QComboBox()
        self.port.setEditable(True)
        self.refresh_btn = button("Atualizar", small=True)
        pr = QHBoxLayout()
        pr.addWidget(self.port, 1)
        pr.addWidget(self.refresh_btn)
        pw = QWidget()
        pw.setLayout(pr)
        pr.setContentsMargins(0, 0, 0, 0)
        form_row(g, 0, "Porta", pw)
        self.addr = QSpinBox()
        self.addr.setRange(0, 30)
        self.addr.setValue(17)
        form_row(g, 1, "Endereço GPIB", self.addr, "++fndl acha")
        self.tmo = QSpinBox()
        self.tmo.setRange(100, 32000)
        self.tmo.setSingleStep(500)
        self.tmo.setValue(3000)
        self.tmo.setSuffix(" ms")
        form_row(g, 2, "++read_tmo_ms", self.tmo)
        self.sync = QComboBox()
        for key, text in SYNC_OPTIONS:
            self.sync.addItem(text, key)
        form_row(g, 3, "Espera da varredura", self.sync)
        left.body.addLayout(g)
        btns = QHBoxLayout()
        self.connect_btn = button("Conectar", "primary")
        self.idn_btn = button("Testar *IDN?")
        btns.addWidget(self.connect_btn)
        btns.addWidget(self.idn_btn)
        btns.addStretch(1)
        left.body.addLayout(btns)
        left.body.addWidget(Notice(
            "++eos 2 · obrigatório",
            "O 4294A só reconhece mensagens terminadas em <b>LF puro</b>. Com CR ou CRLF ele "
            "ignora o comando em silêncio — nenhum erro, só timeout. O app sempre envia "
            "<code>++eos 2</code> ao conectar."))
        left.body.addStretch(1)
        row.addWidget(left, 1)

        # ── estado ──
        right = QVBoxLayout()
        right.setSpacing(16)
        st = Panel("Estado da interface")
        self.kv = KeyValues()
        st.body.addWidget(self.kv)
        right.addWidget(st)

        cp = Panel("Capacidades", "probe")
        self.caps_kv = KeyValues()
        cp.body.addWidget(self.caps_kv)
        pb = QHBoxLayout()
        self.probe_btn = button("Rodar probe", small=True)
        pb.addWidget(self.probe_btn)
        pb.addWidget(label("Muda a configuração do instrumento; reaplique o perfil depois.", "meta",
                           theme.body_font(12), wrap=True), 1)
        cp.body.addLayout(pb)
        self.probe_log = QPlainTextEdit()
        self.probe_log.setReadOnly(True)
        self.probe_log.setFont(theme.mono_font(11, 0.02, 400, caps=False))
        self.probe_log.setMinimumHeight(140)
        cp.body.addWidget(self.probe_log, 1)
        right.addWidget(cp, 1)
        row.addLayout(right, 1)

        # sinais
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.idn_btn.clicked.connect(self.test_idn)
        self.probe_btn.clicked.connect(self.run_probe)
        ctl.connection_changed.connect(self.on_connection)
        ctl.busy_changed.connect(lambda busy, _n: self._enable())
        ctl.caps_changed.connect(self.show_caps)

        self.settings = QSettings("ia4294", "ia4294")
        self.addr.setValue(int(self.settings.value("gpib/address", 17)))
        self.tmo.setValue(int(self.settings.value("gpib/read_tmo_ms", 3000)))
        self.refresh_ports()
        last = self.settings.value("gpib/port", "")
        if last and self.port.findText(last) >= 0:
            self.port.setCurrentText(last)
        self.sync.setCurrentIndex(max(0, [k for k, _ in SYNC_OPTIONS].index(ctl.caps.sync)))
        self.show_state()
        self.show_caps(ctl.caps)
        self._enable()

    # ── ações ───────────────────────────────────────────────────────────
    def refresh_ports(self) -> None:
        current = self.port.currentText()
        self.port.clear()
        ports = list_serial_ports()
        self.port.addItems(ports + [SIM])
        guess = guess_ar488_port()
        if current:
            self.port.setCurrentText(current)
        elif guess:
            self.port.setCurrentText(guess)
        else:
            self.port.setCurrentText(SIM if not ports else ports[0])

    def toggle_connection(self) -> None:
        if self.ctl.connected:
            self.ctl.disconnect_port()
            return
        port = self.port.currentText().strip()
        self.settings.setValue("gpib/port", port)
        self.settings.setValue("gpib/address", self.addr.value())
        self.settings.setValue("gpib/read_tmo_ms", self.tmo.value())
        self.kv.set("Estado", "abrindo porta, aguardando reset da placa…")
        self.ctl.connect_port(port, self.addr.value(), self.tmo.value(), self.sync.currentData(),
                              on_done=lambda _v: self.test_idn())

    def test_idn(self) -> None:
        def job(ctx):
            return ctx.session.query("*IDN?").strip(), ctx.driver.drain_errors()

        def done(r):
            idn, errs = r
            self.ctl.idn = idn
            self.kv.set("Instrumento", idn)
            self.ctl.status.emit("info", f"*IDN? → {idn}")
            self.ctl.refresh_compensation()

        def fail(e, _a):
            self.kv.set("Instrumento", f"sem resposta no endereço {self.addr.value()} — procurando com ++fndl…")
            self.ctl.run("++fndl", lambda ctx: ctx.session.find_listeners(), found)

        def found(addrs):
            hint = (f"o barramento tem instrumento em {', '.join(map(str, addrs))}: desconecte, "
                    f"troque o endereço e conecte de novo") if addrs else "++fndl não achou nenhum instrumento"
            self.kv.set("Instrumento", f"sem resposta no endereço {self.addr.value()} — {hint}")
            self.ctl.status.emit("erro", hint)

        self.ctl.run("*IDN?", job, done, fail)

    def run_probe(self) -> None:
        self.probe_log.clear()

        def job(ctx):
            lines: list[str] = []

            def report(text: str) -> None:
                lines.append(text)
                ctx.progress(min(len(lines) / 16, 0.95), text)

            caps = probe(ctx.session, report, ctx.abort)
            caps.sync = caps.sync if caps.sync_tests.get(caps.sync) else self.sync.currentData()
            caps.save(paths.capabilities_file())
            return caps, lines

        def line(_f: float, msg: str) -> None:
            self.probe_log.appendPlainText(msg)

        def finish() -> None:
            self.ctl.progress.disconnect(line)

        def done(r):
            finish()
            caps, _lines = r
            self.ctl.set_capabilities(caps)
            self.sync.setCurrentIndex([k for k, _ in SYNC_OPTIONS].index(caps.sync))

        self.ctl.progress.connect(line)
        self.ctl.run("probe", job, done, lambda _e, _a: finish())

    # ── exibição ────────────────────────────────────────────────────────
    def on_connection(self, connected: bool, desc: str) -> None:
        self.connect_btn.setText("Desconectar" if connected else "Conectar")
        self.connect_btn.setProperty("kind", "ghost" if connected else "primary")
        self.connect_btn.style().unpolish(self.connect_btn)
        self.connect_btn.style().polish(self.connect_btn)
        self.show_state()
        self._enable()

    def show_state(self) -> None:
        c = self.ctl
        self.kv.set("Estado", "conectado" if c.connected else "desconectado")
        self.kv.set("Porta", c.port_description or self.port.currentText())
        s = c.worker.session
        self.kv.set("Firmware AR488", (s.version if s else "") or "—")
        self.kv.set("Banner descartado", (s.banner if s else "") or "—")
        self.kv.set("Terminador", "++eos 2 · LF   ++eoi 1")
        self.kv.set("Endereço / timeout", f"{self.addr.value()} · {self.tmo.value()} ms")
        self.kv.set("Instrumento", c.idn or "—")
        self.kv.set("Log da sessão", str(c.traffic_log.path))

    def show_caps(self, caps: Capabilities) -> None:
        self.caps_kv.set("Situação", "probe executado " + caps.probed_at if caps.probed else "sem probe")
        self.caps_kv.set("Traço", caps.trace_query)
        self.caps_kv.set("Eixo (LIST)", caps.sweep_query or "—")
        self.caps_kv.set("Formato", caps.ascii_format + (f" · binário {caps.binary_format}" if caps.binary_format else ""))
        self.caps_kv.set("Espera", caps.sync)
        self.caps_kv.set("Arquivo", str(paths.capabilities_file()))

    def _enable(self) -> None:
        busy, conn = self.ctl.busy, self.ctl.connected
        self.connect_btn.setEnabled(not busy or conn)
        for w in (self.port, self.addr, self.tmo, self.sync, self.refresh_btn):
            w.setEnabled(not conn and not busy)
        self.idn_btn.setEnabled(conn and not busy)
        self.probe_btn.setEnabled(conn and not busy)
