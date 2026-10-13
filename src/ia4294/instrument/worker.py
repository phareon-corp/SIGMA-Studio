"""A única thread dona da porta.

Tudo que toca a serial vira um *job* numa fila. A GUI nunca bloqueia: ela
enfileira e recebe o resultado por callback (que a ponte Qt transforma em
signal). Sem Qt aqui, para os testes rodarem sem tela.
"""

from __future__ import annotations

import itertools
import queue
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from .capabilities import Capabilities
from .hp4294a import HP4294A, Aborted
from ..model.sweep import SweepTimer
from ..transport.ar488 import AR488Session
from ..transport.traffic import NOTE, TrafficLog


class WorkerListener(Protocol):
    def job_started(self, job_id: int, name: str) -> None: ...
    def job_progress(self, job_id: int, frac: float, message: str) -> None: ...
    def job_done(self, job_id: int, name: str, result: Any) -> None: ...
    def job_failed(self, job_id: int, name: str, error: str, aborted: bool) -> None: ...
    def connection_changed(self, connected: bool, description: str) -> None: ...


class NotConnected(RuntimeError):
    pass


@dataclass
class JobContext:
    worker: "PortWorker"
    job_id: int
    abort: threading.Event

    @property
    def session(self) -> AR488Session:
        if self.worker.session is None:
            raise NotConnected("sem conexão")
        return self.worker.session

    @property
    def driver(self) -> HP4294A:
        if self.worker.driver is None:
            raise NotConnected("sem conexão")
        return self.worker.driver

    def progress(self, frac: float, message: str = "") -> None:
        self.worker.listener.job_progress(self.job_id, frac, message)

    def check_abort(self) -> None:
        if self.abort.is_set():
            raise Aborted("abortado")


Job = Callable[[JobContext], Any]
_STOP = object()


class PortWorker:
    def __init__(self, listener: WorkerListener, traffic: TrafficLog,
                 caps: Capabilities | None = None, timer_path: Path | None = None) -> None:
        self.listener = listener
        self.traffic = traffic
        self.caps = caps or Capabilities()
        self.timer = SweepTimer(timer_path)
        self.session: AR488Session | None = None
        self.driver: HP4294A | None = None
        self._q: queue.Queue = queue.Queue()
        self._ids = itertools.count(1)
        self._abort = threading.Event()
        self._busy = threading.Event()
        self._thread = threading.Thread(target=self._run, name="porta-gpib", daemon=True)

    # ── chamado de qualquer thread ──────────────────────────────────────
    def start(self) -> None:
        self._thread.start()

    def submit(self, name: str, fn: Job) -> int:
        job_id = next(self._ids)
        self._q.put((job_id, name, fn))
        return job_id

    def abort(self) -> None:
        """Aborta o job em curso e descarta os enfileirados."""
        self._abort.set()
        try:
            while True:
                item = self._q.get_nowait()
                if item is _STOP:
                    self._q.put(_STOP)
                    break
                self.listener.job_failed(item[0], item[1], "cancelado", True)
        except queue.Empty:
            pass

    @property
    def busy(self) -> bool:
        return self._busy.is_set()

    def stop(self, timeout: float = 5.0) -> None:
        self._abort.set()
        self._q.put(_STOP)
        if self._thread.is_alive():
            self._thread.join(timeout)

    # ── jobs prontos ────────────────────────────────────────────────────
    def connect(self, session: AR488Session) -> int:
        def job(ctx: JobContext) -> str:
            self._close()
            session.traffic = self.traffic
            session.open()
            self.session = session
            self.driver = HP4294A(session, self.caps, self.timer)
            self.listener.connection_changed(True, session.link.description)
            return session.version

        return self.submit("conectar", job)

    def disconnect(self) -> int:
        def job(ctx: JobContext) -> None:
            self._close()

        return self.submit("desconectar", job)

    def set_capabilities(self, caps: Capabilities) -> None:
        def job(ctx: JobContext) -> None:
            self.caps = caps
            if self.driver is not None:
                self.driver.caps = caps

        self.submit("capacidades", job)

    # ── thread da porta ─────────────────────────────────────────────────
    def _close(self) -> None:
        if self.session is not None:
            try:
                self.session.close()
            finally:
                self.session = None
                self.driver = None
                self.listener.connection_changed(False, "")

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is _STOP:
                self._close()
                return
            job_id, name, fn = item
            self._abort.clear()
            self._busy.set()
            self.listener.job_started(job_id, name)
            try:
                result = fn(JobContext(self, job_id, self._abort))
            except Aborted:
                self.listener.job_failed(job_id, name, "abortado", True)
            except Exception as exc:  # noqa: BLE001 — tudo vira mensagem na UI
                self.traffic.record(NOTE, f"falha em {name}: {exc!r}")
                self.traffic.record(NOTE, traceback.format_exc().strip().splitlines()[-1])
                self.listener.job_failed(job_id, name, str(exc) or type(exc).__name__, False)
            else:
                self.listener.job_done(job_id, name, result)
            finally:
                self._busy.clear()
