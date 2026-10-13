# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller: SIGMA Studio em pasta única (one-dir), sem console.

Roda no Windows, com o venv do projeto ativo:

    pyinstaller --noconfirm packaging/sigma-studio.spec

Sai em ``dist/sigma-studio/``, que é o que o Inno Setup empacota. One-dir e não
one-file porque o one-file descompacta tudo no %TEMP% a cada abertura — num
app que fica aberto o dia inteiro na bancada isso só atrasa o primeiro uso e
confunde o antivírus.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
ASSETS = ROOT / "src" / "ia4294" / "ui" / "assets"
ICON = SPEC_DIR / "sigma-studio.ico"

datas = [
    (str(ASSETS / "phareon-tokens.css"), "ia4294/ui/assets"),
    (str(ASSETS / "fonts"), "ia4294/ui/assets/fonts"),
]

hiddenimports = [
    "pyqtgraph.graphicsItems",
    *collect_submodules("serial.tools"),
]

# o que não entra: Qt de web/3D/multimídia e a cadeia científica que o app não
# usa. Se algo quebrar em runtime, tire o nome daqui antes de procurar culpado.
excludes = [
    "tkinter", "matplotlib", "scipy", "IPython", "jupyter", "notebook",
    "PyQt5", "PyQt6", "PySide2",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtPositioning",
    "PySide6.QtSensors", "PySide6.QtSerialBus", "PySide6.QtWebSockets",
]

a = Analysis(
    [str(SPEC_DIR / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="sigma-studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX em DLL do Qt é receita de falso positivo no antivírus
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="sigma-studio",
)
