"""Gera os ícones do SIGMA Studio a partir do logo-mark desenhado em ui/main_window.

``sigma-studio.ico`` para o Windows e ``sigma-studio.png`` (256) para o .desktop
do Linux.

O ícone não é arquivo de arte: é o mesmo gradiente radial que a janela usa,
então muda junto com os tokens. Roda sem tela (QT_QPA_PLATFORM=offscreen).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

#: o Windows pede o jogo completo; a barra de tarefas usa 32 e 48
SIZES = (16, 24, 32, 48, 64, 128, 256)


def ico(images: list[bytes], sizes: tuple[int, ...]) -> bytes:
    """Container ICO com um PNG por tamanho (aceito desde o Vista)."""
    import struct

    head = struct.pack("<HHH", 0, 1, len(images))
    offset = len(head) + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in zip(sizes, images):
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    return head + entries + blobs


def main() -> int:
    from PySide6.QtCore import QBuffer, QSize
    from PySide6.QtWidgets import QApplication

    from ia4294.ui import theme
    from ia4294.ui.main_window import app_icon

    QApplication([])
    # o ícone do executável fica no terreno escuro: o fundo dele é a câmara,
    # e é o que se lê tanto na barra clara quanto na escura do Windows
    theme.set_terrain("escuro")
    icon = app_icon()

    pngs = []
    for size in SIZES:
        buf = QBuffer()
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        icon.pixmap(QSize(size, size)).toImage().save(buf, "PNG")
        pngs.append(bytes(buf.data()))

    out = HERE / "sigma-studio.ico"
    out.write_bytes(ico(pngs, SIZES))
    print(f"{out} — {len(SIZES)} tamanhos, {out.stat().st_size} bytes")

    png = HERE / "sigma-studio.png"  # o .desktop do Linux quer PNG
    png.write_bytes(pngs[SIZES.index(256)])
    print(f"{png} — 256×256, {png.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
