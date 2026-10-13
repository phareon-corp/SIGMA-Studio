"""ia4294 — abre a janela. ``python -m ia4294 --sim`` conecta direto no simulador."""

from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ia4294")
    ap.add_argument("--sim", action="store_true", help="conecta no simulador ao abrir")
    ap.add_argument("--sim-speed", type=float, default=0.1,
                    help="escala de tempo do simulador (1 = tempo real estimado)")
    ap.add_argument("--page", type=int, default=1, help="página inicial (1–6)")
    ap.add_argument("--tema", choices=("escuro", "claro", "sistema"),
                    help="terreno da interface; sem isto vale o último escolhido na janela")
    ap.add_argument("--screenshot", metavar="PNG", help="(dev) salva a janela e sai")
    ap.add_argument("--acquire", action="store_true", help="(dev) dispara uma varredura ao conectar")
    ap.add_argument("--size", metavar="LxA", help="(dev) tamanho fixo da janela, ex. 1366x700")
    args = ap.parse_args(argv)

    from PySide6.QtCore import QSettings, QTimer
    from PySide6.QtWidgets import QApplication

    from .ui import theme
    from .ui.controller import Controller
    from .ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("ia4294")
    app.setStyle("Fusion")
    # o terreno antes do QSS: a folha nasce com as cores já resolvidas
    pref = args.tema or os.environ.get("IA4294_TERRENO") \
        or QSettings("ia4294", "ia4294").value("ui/terreno", theme.DEFAULT_TERRAIN)
    theme.set_terrain(str(pref))
    theme.load_fonts()
    app.setFont(theme.body_font(13))
    app.setStyleSheet(theme.stylesheet())

    ctl = Controller(simulator_time_scale=args.sim_speed)
    win = MainWindow(ctl)
    win.show_page(max(0, min(args.page - 1, 5)))
    if args.size:
        w, h = (int(v) for v in args.size.lower().split("x"))
        win.resize(w, h)
        win.show()
    else:
        win.showMaximized() if win._maximize else win.show()

    if args.sim:
        conn = win.pages[0]
        conn.port.setCurrentText("SIMULADOR")
        after = (lambda _v: (conn.test_idn(), win.pages[3].trigger())) if args.acquire else (lambda _v: conn.test_idn())
        ctl.connect_port("SIMULADOR", conn.addr.value(), conn.tmo.value(), conn.sync.currentData(), on_done=after)

    if args.screenshot:
        def shoot() -> None:
            if ctl.busy:
                QTimer.singleShot(300, shoot)
                return
            if "{page}" in args.screenshot:
                for i in range(6):
                    win.show_page(i)
                    QApplication.processEvents()
                    win.grab().save(args.screenshot.format(page=i + 1))
            else:
                win.grab().save(args.screenshot)
            win.close()

        QTimer.singleShot(2500, shoot)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
