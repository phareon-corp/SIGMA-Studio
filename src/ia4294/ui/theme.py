"""Tema Phareon para Qt.

Os tokens vêm de ``assets/phareon-tokens.css``, cópia literal de
``~/Documentos/Phareon/Design/tokens/tokens.css`` — a fonte da verdade.
Nenhuma cor é escrita aqui: o QSS só referencia tokens por nome.

Dois **terrenos**, no vocabulário do design (brand/01-cor.md): ``claro``
(``--bg-light``) e ``escuro`` (``--bg``). O sistema Phareon nasce escuro; a
bancada trabalha com luz acesa, então **o app abre no claro** e guarda a
escolha de quem mexeu no botão.
Não há "tema": o QSS pede nomes semânticos (``bg``, ``ink``, ``line``) e o
terreno escolhe qual token responde — por isso a troca não toca em componente.
Laranja ``--accent`` é o único token que não inverte: estado e ação nos dois
terrenos (≤8% da tela). O dado medido pede o alias ``data``: ciano ``--beam``
no escuro (ADR-004 proposto, docs/ADR-004-beam-dado-medido.md), tinta
``--ink-dark`` no claro — ciano sobre papel dá ~1,9:1 e não se lê.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtCore import QEasingCurve

ASSETS = Path(__file__).parent / "assets"
TOKENS_CSS = ASSETS / "phareon-tokens.css"

F_DISPLAY = "Bricolage Grotesque"
F_BODY = "Geist"
F_MONO = "Geist Mono"
F_SERIF = "Instrument Serif"

_DECL = re.compile(r"--([\w-]+)\s*:\s*([^;]+);")
_RGBA = re.compile(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)")


@lru_cache(maxsize=1)
def tokens() -> dict[str, QColor]:
    """Só os tokens de cor do primeiro bloco ``:root``."""
    css = TOKENS_CSS.read_text(encoding="utf-8")
    root = css[css.index(":root") : css.index("}", css.index(":root"))]
    root = re.sub(r"/\*.*?\*/", "", root, flags=re.S)
    out: dict[str, QColor] = {}
    for name, value in _DECL.findall(root):
        value = value.strip()
        if value.startswith("#"):
            out[name] = QColor(value)
        elif m := _RGBA.match(value):
            r, g, b, a = m.groups()
            out[name] = QColor(int(r), int(g), int(b), round(float(a) * 255))
    return out


# ── terrenos ────────────────────────────────────────────────────────────
#: nome semântico → token, por terreno. O que não está aqui vale como token
#: literal (``accent``, ``accent-glow``, ``accent-soft``, ``ink-dark``…).
TERRAINS: dict[str, dict[str, str]] = {
    # o padrão: câmara escura. Os nomes já são os tokens.
    "escuro": {
        "data": "beam",
        "data-soft": "beam-soft",
        "accent-text": "accent",
    },
    # a inversão. O claro tem duas superfícies, não três: ``bg`` e ``bg-2``
    # caem no mesmo papel e a hierarquia fica com as linhas, como nas seções
    # claras do site; ``bg-3`` (hover) é o único degrau.
    "claro": {
        "bg": "bg-light",
        "bg-2": "bg-light",
        "bg-3": "bg-light-2",
        "ink": "ink-dark",
        "ink-dim": "ink-dark-2",
        "ink-faint": "ink-dark-3",
        "line": "line-dark",
        "line-mid": "line-dark-mid",
        "line-strong": "line-dark-strong",
        "data": "ink-dark",
        "data-soft": "line-dark-strong",
        # #FF4A1C sobre #EFECE4 dá ~2,8:1: não carrega texto. O estado fica na
        # barra de acento do QSS e o texto volta para a tinta.
        "accent-text": "ink-dark",
    },
}
#: o padrão do app (não o do design: lá o terreno de origem é o escuro).
DEFAULT_TERRAIN = "claro"

#: terreno em vigor; quem decide na abertura é ``__main__`` (--tema,
#: IA4294_TERRENO, preferência salva) e depois ``MainWindow.apply_terrain``.
_terrain = DEFAULT_TERRAIN


def system_terrain() -> str:
    """O que a mesa de trabalho pede: ``color-scheme`` no GNOME, registro no Windows."""
    if sys.platform.startswith("win"):
        try:
            import winreg

            key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                light, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return "claro" if light else "escuro"
        except OSError:
            return DEFAULT_TERRAIN
    try:
        r = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                           capture_output=True, text=True, timeout=1)
        return "escuro" if "prefer-dark" in r.stdout else "claro"
    except (OSError, subprocess.SubprocessError):
        return DEFAULT_TERRAIN


def resolve_terrain(name: str | None) -> str:
    """``sistema`` consulta a mesa; nome desconhecido cai no padrão."""
    name = (name or "").strip().lower()
    if name == "sistema":
        return system_terrain()
    return name if name in TERRAINS else DEFAULT_TERRAIN


def terrain() -> str:
    return _terrain


def set_terrain(name: str | None) -> str:
    """Troca o terreno e devolve o que ficou valendo."""
    global _terrain
    _terrain = resolve_terrain(name)
    return _terrain


@lru_cache(maxsize=len(TERRAINS))
def palette(terrain_name: str) -> dict[str, QColor]:
    """Tokens do terreno, já com os nomes semânticos resolvidos."""
    raw = tokens()
    out = dict(raw)
    out.update({name: raw[token] for name, token in TERRAINS[terrain_name].items()})
    return out


def color(name: str) -> QColor:
    return QColor(palette(_terrain)[name])


def qss_color(name: str) -> str:
    """``#AARRGGBB`` — o QSS do Qt não entende alfa fracionário em rgba()."""
    return palette(_terrain)[name].name(QColor.NameFormat.HexArgb)


# ── movimento ───────────────────────────────────────────────────────────
def ease() -> QEasingCurve:
    """--ease: cubic-bezier(.2,.8,.2,1) — resposta de instrumento."""
    c = QEasingCurve(QEasingCurve.Type.BezierSpline)
    c.addCubicBezierSegment(QPointF(0.2, 0.8), QPointF(0.2, 1.0), QPointF(1.0, 1.0))
    return c


@lru_cache(maxsize=1)
def reduced_motion() -> bool:
    if os.environ.get("IA4294_REDUCED_MOTION"):
        return True
    try:
        r = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "enable-animations"],
                           capture_output=True, text=True, timeout=1)
        return r.stdout.strip() == "false"
    except (OSError, subprocess.SubprocessError):
        return False


# ── tipografia ──────────────────────────────────────────────────────────
def load_fonts() -> None:
    for f in sorted((ASSETS / "fonts").glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(f))


def _features(font: QFont) -> QFont:
    # body roda com ss01 e cv11 — senão o 1, o a e o l mudam de forma
    try:
        font.setFeature(QFont.Tag("ss01"), 1)
        font.setFeature(QFont.Tag("cv11"), 1)
    except (AttributeError, TypeError):
        pass
    return font


def body_font(px: float = 14, weight: int = 400) -> QFont:
    f = QFont(F_BODY)
    f.setPixelSize(round(px))
    f.setWeight(QFont.Weight(weight))
    return _features(f)


def mono_font(px: float = 11, tracking_em: float = 0.18, weight: int = 500, caps: bool = True) -> QFont:
    """Mono ≤13px, sempre com tracking positivo — a etiqueta do instrumento."""
    px = min(px, 13)
    f = QFont(F_MONO)
    f.setPixelSize(round(px))
    f.setWeight(QFont.Weight(weight))
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, max(px * tracking_em, 0.4))
    if caps:
        f.setCapitalization(QFont.Capitalization.AllUppercase)
    return f


def display_font(px: float = 34, weight: int = 500) -> QFont:
    """A lei do tracking: quanto maior o display, mais negativo."""
    f = QFont(F_DISPLAY)
    f.setPixelSize(round(px))
    f.setWeight(QFont.Weight(weight))
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -px * (0.035 if px >= 30 else 0.02))
    return f


def serif_span(text: str) -> str:
    """Itálico serifado — só onde a frase toca a física, uma vez por título."""
    return f"<span style=\"font-family:'{F_SERIF}'; font-style:italic; font-weight:400\">{text}</span>"


# ── QSS ─────────────────────────────────────────────────────────────────
_QSS = """
* { color: @ink-dim; outline: none; }
QMainWindow, QWidget#root, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget { background: @bg; }
QToolTip { background: @bg-3; color: @ink; border: 1px solid @line-strong; padding: 6px 8px; }

#topbar { background: @bg-2; border-bottom: 1px solid @line; }
#sidenav { background: @bg-2; border-right: 1px solid @line; }
#statusbar { background: @bg-2; border-top: 1px solid @line; }


QPushButton#navitem { text-align: left; border: none; border-radius: 5px; padding: 10px 12px;
    background: transparent; color: @ink-dim; }
QPushButton#navitem:hover { background: @bg-3; color: @ink; }
QPushButton#navitem:checked { background: @bg-3; color: @ink; }
QPushButton#navitem:focus { border: 1px solid @accent; }

QLabel { background: transparent; }
QLabel[role="title"] { color: @ink; }
QLabel[role="lead"] { color: @ink-dim; }
QLabel[role="meta"] { color: @ink-faint; }
QLabel[role="value"] { color: @ink; }
QLabel[role="error"] { color: @accent-text; border-left: 2px solid @accent; padding-left: 7px; }
QLabel[role="ok"] { color: @ink; }

#panel { background: @bg-2; border: 1px solid @line; border-radius: 6px; }
#panelhead { border-bottom: 1px solid @line; }
#notice { background: @bg-2; border: 1px solid @line-strong; border-left: 2px solid @accent; border-radius: 4px; }

QPushButton { border-radius: 17px; padding: 8px 18px; min-height: 18px; }
QPushButton[kind="primary"] { background: @accent; color: @ink-dark; border: 1px solid @accent; }
QPushButton[kind="primary"]:hover { background: @accent-glow; border-color: @accent-glow; }
QPushButton[kind="primary"]:focus { border: 2px solid @ink; }
QPushButton[kind="ghost"] { background: transparent; color: @ink; border: 1px solid @line-strong; }
QPushButton[kind="ghost"]:hover { background: @ink; color: @bg; border-color: @ink; }
QPushButton[kind="ghost"]:focus { border: 1px solid @accent; }
QPushButton:disabled, QPushButton[kind="primary"]:disabled, QPushButton[kind="ghost"]:disabled {
    background: transparent; color: @ink-faint; border: 1px solid @line; }

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: @bg; color: @ink; border: 1px solid @line-strong; border-radius: 4px;
    padding: 5px 8px; min-height: 18px; selection-background-color: @accent-soft; selection-color: @ink; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid @accent; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color: @ink-faint; border-color: @line; }
QLineEdit[invalid="true"] { border: 1px solid @accent; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: @bg-2; color: @ink; border: 1px solid @line-strong;
    selection-background-color: @bg-3; selection-color: @ink; outline: none; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 16px; border: none; }

QCheckBox { color: @ink-dim; spacing: 8px; }
QCheckBox:focus { color: @ink; }
QCheckBox::indicator { width: 13px; height: 13px; border: 1px solid @line-strong; border-radius: 3px; background: @bg; }
QCheckBox::indicator:checked { background: @ink; border-color: @ink; }
QCheckBox::indicator:focus { border-color: @accent; }
QCheckBox:disabled { color: @ink-faint; }

QProgressBar { background: @bg-3; border: none; border-radius: 1px; max-height: 3px; min-height: 3px; }
QProgressBar::chunk { background: @accent; border-radius: 1px; }

QPlainTextEdit, QTextEdit { background: @bg; color: @ink-dim; border: 1px solid @line; border-radius: 4px;
    selection-background-color: @accent-soft; selection-color: @ink; }

QTableView { background: @bg-2; alternate-background-color: @bg-3; color: @ink; gridline-color: @line;
    border: 1px solid @line; border-radius: 4px; selection-background-color: @accent-soft; selection-color: @ink; }
QHeaderView::section { background: @bg-2; color: @ink-faint; border: none; border-bottom: 1px solid @line-strong;
    padding: 6px 8px; }
QTableCornerButton::section { background: @bg-2; border: none; }

QSplitter::handle { background: @line; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 0; }
QScrollBar::handle { background: @line-strong; border-radius: 4px; min-height: 24px; min-width: 24px; }
QScrollBar::handle:hover { background: @ink-faint; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { background: none; border: none; height: 0; width: 0; }
QMessageBox, QDialog { background: @bg-2; }
QMessageBox QLabel { color: @ink; }
"""


def stylesheet() -> str:
    def repl(m: re.Match[str]) -> str:
        return qss_color(m.group(1))

    return re.sub(r"@([a-z0-9-]+)", repl, _QSS)
