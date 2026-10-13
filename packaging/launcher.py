"""Entrada do executável congelado: o mesmo ``main`` do pacote.

Existe porque o PyInstaller precisa de um script, não de um entry point — e
porque é aqui que o modo congelado ganha o que o venv dava de graça.
"""

from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()  # sem isto, qualquer fork reabre a janela
    from ia4294.__main__ import main as run

    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
