"""Os dois terrenos: resolução de tokens, contraste e troca com a janela aberta."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IA4294_REDUCED_MOTION"] = "1"
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture
def theme():
    from ia4294.ui import theme as t

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])  # QColor precisa do app
    before = t.terrain()
    yield t
    t.set_terrain(before)


def ratio(fg, bg) -> float:
    def lum(c):
        ch = []
        for v in (c.redF(), c.greenF(), c.blueF()):
            ch.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]

    a, b = sorted((lum(fg), lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def test_terreno_claro_e_o_padrao(theme):
    assert theme.DEFAULT_TERRAIN == "claro"
    assert theme.resolve_terrain(None) == "claro"
    assert theme.resolve_terrain("TEMA-QUE-NAO-EXISTE") == "claro"
    assert theme.set_terrain("escuro") == "escuro"
    assert theme.set_terrain("claro") == "claro"


def test_claro_inverte_superficie_e_tinta(theme):
    theme.set_terrain("escuro")
    assert theme.color("bg").name() == "#08080b"
    assert theme.color("ink").name() == "#f4f1e9"
    theme.set_terrain("claro")
    assert theme.color("bg").name() == "#efece4"  # --bg-light
    assert theme.color("ink").name() == "#0a0a0d"  # --ink-dark
    assert theme.color("bg-3").name() == "#e5e1d7"  # hover tem degrau próprio
    assert theme.color("bg-3") != theme.color("bg-2")


def test_acento_nao_inverte(theme):
    """ADR-001: #FF4A1C é o único token que vale igual nos dois terrenos."""
    theme.set_terrain("escuro")
    escuro = [theme.color(k).name() for k in ("accent", "accent-glow", "ink-dark")]
    theme.set_terrain("claro")
    assert [theme.color(k).name() for k in ("accent", "accent-glow", "ink-dark")] == escuro


def test_dado_medido_troca_de_caneta(theme):
    """Ciano sobre papel dá ~1,9:1: no claro o traço vira tinta."""
    theme.set_terrain("escuro")
    assert theme.color("data").name() == theme.color("beam").name()
    theme.set_terrain("claro")
    assert theme.color("data").name() == theme.color("ink-dark").name()
    assert ratio(theme.color("data"), theme.color("bg")) > 7


@pytest.mark.parametrize("terreno", ["escuro", "claro"])
def test_contraste_do_texto(theme, terreno):
    theme.set_terrain(terreno)
    bg = theme.color("bg")
    assert ratio(theme.color("ink"), bg) >= 7  # AAA
    assert ratio(theme.color("ink-dim"), bg) >= 4.5  # AA
    # ink-faint/ink-dark-3 é etiqueta redundante nos dois terrenos (brand/01-cor)
    assert ratio(theme.color("ink-faint"), bg) >= 2.5
    # o texto de erro precisa ler; no claro o acento sai e entra a tinta
    assert ratio(theme.color("accent-text"), bg) >= 4.5


@pytest.mark.parametrize("terreno", ["escuro", "claro"])
def test_qss_resolve_todos_os_nomes(theme, terreno):
    theme.set_terrain(terreno)
    qss = theme.stylesheet()
    assert "@" not in qss
    assert theme.qss_color("bg").lower() in qss.lower()


def test_troca_com_a_janela_aberta(theme, tmp_path, monkeypatch):
    from ia4294.ui.controller import Controller
    from ia4294.ui.main_window import MainWindow

    monkeypatch.setenv("IA4294_HOME", str(tmp_path / "home"))
    theme.set_terrain("escuro")
    app = QtWidgets.QApplication.instance()
    app.setStyleSheet(theme.stylesheet())
    ctl = Controller()
    win = MainWindow(ctl)
    try:
        plot = win.pages[3].plot.plots[0]
        assert win.terrain_btn.target() == "claro"  # o botão desenha o sol

        assert win.apply_terrain("claro", save=False) == "claro"
        assert win.terrain_btn.target() == "escuro"  # agora a lua
        assert plot.backgroundBrush().color().name() == theme.color("bg").name() == "#efece4"
        assert win.pages[3].plot.curves[0].opts["pen"].color().name() == "#0a0a0d"
        # os rótulos dos eixos sobrevivem à repintura
        assert "Frequência" in plot.getPlotItem().getAxis("bottom").labelText

        win.apply_terrain("escuro", save=False)
        assert plot.backgroundBrush().color().name() == "#08080b"
        assert win.pages[3].plot.curves[0].opts["pen"].color().name() == "#4fe0ff"
    finally:
        win.close()
        ctl.shutdown()


def test_pastas_seguem_o_sistema(monkeypatch, tmp_path):
    """Windows escreve em %APPDATA%/%LOCALAPPDATA%/Documents, Linux no XDG."""
    from ia4294 import paths

    monkeypatch.delenv("IA4294_HOME", raising=False)
    monkeypatch.setattr(paths, "WINDOWS", True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "perfil"))
    assert paths.config_dir() == tmp_path / "Roaming" / "ia4294"
    assert paths.log_dir() == tmp_path / "Local" / "ia4294" / "logs"
    assert paths.data_dir() == tmp_path / "perfil" / "Documents" / "ia4294"

    monkeypatch.setattr(paths, "WINDOWS", False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert paths.config_dir() == tmp_path / "cfg" / "ia4294"
    assert paths.log_dir() == tmp_path / "state" / "ia4294" / "logs"
