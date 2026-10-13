import threading

from ia4294.instrument.hp4294a import HP4294A
from ia4294.instrument.worker import PortWorker
from ia4294.model.config import MeasurementConfig
from ia4294.sim.ar488 import SimLink
from ia4294.sim.hp4294a import Sim4294A
from ia4294.transport.ar488 import AR488Session, AR488Settings
from ia4294.transport.traffic import TrafficLog


class Recorder:
    def __init__(self):
        self.events = []
        self.done = threading.Event()

    def job_started(self, i, n): self.events.append(("start", n))
    def job_progress(self, i, f, m): self.events.append(("prog", f))
    def job_done(self, i, n, r):
        self.events.append(("done", n, r))
        if n == "fim":
            self.done.set()
    def job_failed(self, i, n, e, aborted):
        self.events.append(("fail", n, e, aborted))
        if n == "fim":
            self.done.set()
    def connection_changed(self, c, d): self.events.append(("conn", c))


def test_queue_runs_in_order_on_one_thread(tmp_path):
    rec = Recorder()
    traffic = TrafficLog(tmp_path / "t.log")
    w = PortWorker(rec, traffic)
    w.start()
    sim = Sim4294A(time_scale=0.002)
    w.connect(AR488Session(SimLink(sim), AR488Settings(read_tmo_ms=200)))
    threads = []
    w.submit("idn", lambda ctx: (threads.append(threading.current_thread().name), ctx.session.query("*IDN?"))[1])
    w.submit("medir", lambda ctx: ctx.driver.acquire(MeasurementConfig(points=11), ctx.abort, ctx.progress)[0].points)
    w.submit("fim", lambda ctx: threads.append(threading.current_thread().name))
    assert rec.done.wait(10)
    w.stop()
    done = [e for e in rec.events if e[0] == "done"]
    assert [d[1] for d in done] == ["conectar", "idn", "medir", "fim"]
    assert done[1][2].startswith("HEWLETT-PACKARD") and done[2][2] == 11
    assert set(threads) == {"porta-gpib"}
    assert ("conn", True) in rec.events and ("conn", False) in rec.events
    log = (tmp_path / "t.log").read_text()
    assert "> ++eos 2" in log and "> ++read eoi" in log and "< HEWLETT-PACKARD" in log


def test_abort_running_and_queued(tmp_path):
    rec = Recorder()
    w = PortWorker(rec, TrafficLog())
    w.start()
    sim = Sim4294A(time_scale=100.0)
    w.connect(AR488Session(SimLink(sim), AR488Settings(read_tmo_ms=200)))
    started = threading.Event()

    def long(ctx):
        started.set()
        ctx.driver.run_and_wait("SING", 100, ctx.abort)

    w.submit("longa", long)
    w.submit("depois", lambda ctx: 1)
    assert started.wait(5)
    w.abort()
    w.submit("fim", lambda ctx: None)
    assert rec.done.wait(10)
    w.stop()
    fails = {e[1]: e for e in rec.events if e[0] == "fail"}
    assert fails["longa"][3] is True and fails["depois"][2] == "cancelado"
    assert not sim.busy


def test_job_without_connection_fails_cleanly():
    rec = Recorder()
    w = PortWorker(rec, TrafficLog())
    w.start()
    w.submit("fim", lambda ctx: ctx.session.query("*IDN?"))
    assert rec.done.wait(5)
    w.stop()
    assert rec.events[-1][:3] == ("fail", "fim", "sem conexão")
