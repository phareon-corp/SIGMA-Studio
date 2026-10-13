"""Descobre quais comandos de transferência de array o 4294A aceita.

O Programming Manual — que define OUTPDTRC?, FORM4 & cia. — não está à mão.
O probe testa candidatos pela convenção HP, confere OUTPERRO? e o formato de
cada resposta, e grava o que funcionou num arquivo de capacidades.

ATENÇÃO: o probe muda a configuração do instrumento (varredura LIN de
11 pontos, 1 kHz – 1 MHz, BW 1, sem média). Reaplique seu perfil depois.

Uso:  ia4294-probe --port /dev/ttyACM0      (ou --sim; sem --port, procura a placa)
"""

from __future__ import annotations

import argparse
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

from .. import paths
from ..transport.ar488 import AR488Session, AR488Settings, GpibError, GpibTimeout
from ..transport.links import guess_ar488_port
from ..transport.traffic import TrafficLog
from .capabilities import Capabilities
from .hp4294a import HP4294A
from .parser import ParseError, parse_block, parse_numbers

TRACE_CANDIDATES = ("OUTPDTRC?", "OUTPDATA?", "OUTPMTRC?", "OUTPMEMO?")
SWEEP_CANDIDATES = ("OUTPSWPRM?", "OUTPSWPRMP?")
FORMATS = ("FORM4", "FORM3", "FORM2", "FORM5")
BINARY = ("FORM3", "FORM2", "FORM5")

PROBE_SETUP = "HOLD;MEAS CPD;SWPP FREQ;SWPT LIN;STAR 1E3;STOP 1E6;POIN 11;SWED UP;BWFACT 1;AVER OFF;PAVER OFF"
PROBE_POINTS = 11
PROBE_AXIS = np.linspace(1e3, 1e6, PROBE_POINTS)

Report = Callable[[str], None]


def _try_query(drv: HP4294A, q: str) -> dict:
    try:
        text = drv.s.query(q)
    except GpibTimeout:
        return {"ok": False, "reason": "timeout", "errors": drv.drain_errors()}
    errors = drv.drain_errors()
    try:
        vals = parse_numbers(text)
    except ParseError as exc:
        return {"ok": False, "reason": str(exc), "errors": errors, "raw": text[:80]}
    return {"ok": not errors, "count": int(vals.size), "values": vals,
            "sample": [float(v) for v in vals[:4]], "errors": errors}


def probe(session: AR488Session, report: Report = print,
          abort: threading.Event | None = None) -> Capabilities:
    abort = abort or threading.Event()
    drv = HP4294A(session, Capabilities())
    caps = Capabilities(probed=True)
    caps.idn = session.query("*IDN?").strip()
    report(f"instrumento: {caps.idn}")
    session.write("*CLS")
    drv.drain_errors()

    rep = drv.block("probe:setup", PROBE_SETUP)
    report(f"configuração do probe: {'ok' if rep.ok else rep.errors}")

    for f in FORMATS:
        rep = drv.block(f"probe:{f}", f)
        caps.formats[f] = rep.ok
        report(f"{f:<6} {'aceito' if rep.ok else f'recusado {rep.errors}'}")
    if not caps.formats.get("FORM4"):
        report("FORM4 recusado — mantendo FORM4 mesmo assim; leitura ASCII pode falhar")
    session.write("FORM4")

    # estratégias de espera
    for strat in ("spoll", "opc_query"):
        drv.caps.sync = strat
        try:
            drv.run_and_wait("SING", 1.0, abort, label=f"probe:{strat}", max_wait_s=33.0)
            caps.sync_tests[strat] = not drv.drain_errors()
        except (TimeoutError, GpibError) as exc:
            caps.sync_tests[strat] = False
            report(f"espera {strat}: falhou ({exc})")
            session.device_clear()
        report(f"espera {strat:<9} {'funciona' if caps.sync_tests[strat] else 'não funciona'}")
    caps.sync = next((s for s in ("spoll", "opc_query") if caps.sync_tests.get(s)), "spoll")

    # traço
    caps.trace_query = ""
    for q in TRACE_CANDIDATES:
        per_trace = {}
        for tr in ("A", "B"):
            session.write(f"TRAC {tr}")
            per_trace[tr] = _try_query(drv, q)
        a, b = per_trace["A"], per_trace["B"]
        ok = a["ok"] and b["ok"] and a["count"] in (PROBE_POINTS, 2 * PROBE_POINTS)
        depends = ok and not np.allclose(a["values"], b["values"])
        caps.queries[q] = {
            "ok": bool(ok), "count": a.get("count"), "per_point": (a.get("count") or 0) // PROBE_POINTS,
            "depends_on_trace": bool(depends), "sample_A": a.get("sample"), "sample_B": b.get("sample"),
            "errors": a.get("errors", []) + b.get("errors", []), "reason": a.get("reason") or b.get("reason"),
        }
        verdict = ("serve como traço" if depends else "responde, mas igual em A e B") if ok else "não serve"
        report(f"{q:<12} {verdict} ({caps.queries[q]})")
        if depends and not caps.trace_query:
            caps.trace_query = q
    session.write("TRAC A")
    if not caps.trace_query:
        caps.trace_query = "OUTPDTRC?"
        report("nenhum candidato de traço confirmado — usando OUTPDTRC? por convenção")

    # eixo de varredura (necessário só em LIST)
    caps.sweep_query = None
    for q in SWEEP_CANDIDATES:
        r = _try_query(drv, q)
        match = r["ok"] and r["count"] in (PROBE_POINTS, 2 * PROBE_POINTS) and np.allclose(
            r["values"][:: r["count"] // PROBE_POINTS], PROBE_AXIS, rtol=1e-4)
        caps.queries[q] = {"ok": bool(r["ok"]), "count": r.get("count"), "matches_axis": bool(match),
                           "sample": r.get("sample"), "errors": r.get("errors", []), "reason": r.get("reason")}
        report(f"{q:<12} {'eixo confere' if match else 'não confere'} ({caps.queries[q]})")
        if match and not caps.sweep_query:
            caps.sweep_query = q

    # binário: só registra; o app usa ASCII salvo edição manual de binary_format
    ref = _try_query(drv, caps.trace_query)
    for f in BINARY:
        if not caps.formats.get(f):
            continue
        session.write(f)
        try:
            vals = parse_block(session.query_block(caps.trace_query), f)
            same = ref["ok"] and vals.size == ref["count"] and np.allclose(vals, ref["values"], rtol=1e-5)
        except (GpibError, ParseError, ValueError) as exc:
            same = False
            report(f"{f} bloco: {exc}")
            session.device_clear()
        caps.queries[f"{f} {caps.trace_query}"] = {"ok": bool(same)}
        report(f"{f} binário {'confere com FORM4' if same else 'não confere'}")
        drv.drain_errors()
    session.write("FORM4")

    caps.probed_at = datetime.now().isoformat(timespec="seconds")
    report(f"resultado: {caps.summary()}")
    return caps


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ia4294-probe", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default=None,
                    help="porta serial; sem isto procura a interface (COM* ou /dev/ttyACM*)")
    ap.add_argument("--sim", action="store_true", help="usa o simulador em vez da porta")
    ap.add_argument("--addr", type=int, default=17)
    ap.add_argument("--read-tmo-ms", type=int, default=None,
                    help="timeout de leitura do AR488 (padrão 3000; 300 no simulador)")
    ap.add_argument("--out", type=Path, default=paths.capabilities_file())
    args = ap.parse_args(argv)
    if args.port is None:
        args.port = guess_ar488_port() or ("COM3" if paths.WINDOWS else "/dev/ttyACM0")

    if args.sim:
        from ..sim.ar488 import SimLink
        from ..sim.hp4294a import Sim4294A

        link = SimLink(Sim4294A(time_scale=0.02))
    else:
        from ..transport.links import SerialLink

        link = SerialLink(args.port)
    traffic = TrafficLog.for_session(paths.log_dir())
    tmo = args.read_tmo_ms or (300 if args.sim else 3000)
    session = AR488Session(link, AR488Settings(address=args.addr, read_tmo_ms=tmo), traffic)
    session.open()
    try:
        caps = probe(session)
    except GpibTimeout:
        found = session.find_listeners()
        print(f"\nO endereço {args.addr} não respondeu ao *IDN?.")
        print(f"++fndl encontrou no barramento: {found or 'nenhum instrumento'}")
        if found:
            print(f"Tente: ia4294-probe --port {args.port} --addr {found[0]}")
        return 1
    finally:
        session.close()
        traffic.close()
    caps.save(args.out)
    print(f"capacidades gravadas em {args.out}")
    print(f"tráfego em {traffic.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
