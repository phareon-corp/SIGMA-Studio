"""Ponte entre a GUI e a thread dona da porta.

O ``PortWorker`` chama o ouvinte na thread da porta; os signals emitidos
daqui atravessam para a thread da GUI como conexões enfileiradas.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from .. import paths
from ..instrument.capabilities import Capabilities
from ..instrument.worker import JobContext, PortWorker
from ..model.config import MeasurementConfig
from ..model.sweep import CompensationState, SweepResult
from ..transport.ar488 import AR488Session, AR488Settings
from ..transport.traffic import NOTE, TrafficEntry, TrafficLog


class _Bridge(QObject):
    started = Signal(int, str)
    progress = Signal(int, float, str)
    done = Signal(int, str, object)
    failed = Signal(int, str, str, bool)
    connection = Signal(bool, str)
    traffic = Signal(object)

    # interface WorkerListener — chamada na thread da porta
    def job_started(self, job_id: int, name: str) -> None:
        self.started.emit(job_id, name)

    def job_progress(self, job_id: int, frac: float, message: str) -> None:
        self.progress.emit(job_id, frac, message)

    def job_done(self, job_id: int, name: str, result: Any) -> None:
        self.done.emit(job_id, name, result)

    def job_failed(self, job_id: int, name: str, error: str, aborted: bool) -> None:
        self.failed.emit(job_id, name, error, aborted)

    def connection_changed(self, connected: bool, description: str) -> None:
        self.connection.emit(connected, description)


Done = Callable[[Any], None]
Fail = Callable[[str, bool], None]


class Controller(QObject):
    connection_changed = Signal(bool, str)
    busy_changed = Signal(bool, str)  # ocupado?, nome do job
    progress = Signal(float, str)
    traffic = Signal(object)  # TrafficEntry
    status = Signal(str, str)  # nível ("info" | "erro"), texto
    compensation_changed = Signal(object)  # CompensationState
    result_ready = Signal(object)  # SweepResult
    config_changed = Signal(object)  # MeasurementConfig
    caps_changed = Signal(object)  # Capabilities

    def __init__(self, simulator_time_scale: float = 0.1) -> None:
        super().__init__()
        self.sim_time_scale = simulator_time_scale
        self.traffic_log = TrafficLog.for_session(paths.log_dir())
        self.caps = Capabilities.load_or_default(paths.capabilities_file())
        self.config = MeasurementConfig()
        self.result: SweepResult | None = None
        self.compensation = CompensationState()
        self.connected = False
        self.port_description = ""
        self.simulated = False
        self.sim_instrument = None
        self.idn = ""

        self._bridge = _Bridge()
        self._callbacks: dict[int, tuple[Done | None, Fail | None]] = {}
        self._running: set[int] = set()
        self._bridge.started.connect(self._on_started)
        self._bridge.progress.connect(lambda _i, f, m: self.progress.emit(f, m))
        self._bridge.done.connect(self._on_done)
        self._bridge.failed.connect(self._on_failed)
        self._bridge.connection.connect(self._on_connection)
        self._bridge.traffic.connect(self.traffic.emit)
        self.traffic_log.add_listener(self._bridge.traffic.emit)

        self.worker = PortWorker(self._bridge, self.traffic_log, self.caps,
                                 timer_path=paths.config_dir() / "tempos.json")
        self.worker.start()

    # ── jobs ────────────────────────────────────────────────────────────
    def run(self, name: str, fn: Callable[[JobContext], Any], on_done: Done | None = None,
            on_fail: Fail | None = None) -> int:
        job_id = self.worker.submit(name, fn)
        self._callbacks[job_id] = (on_done, on_fail)
        return job_id

    def abort(self) -> None:
        self.traffic_log.record(NOTE, "pedido de abortar")
        self.worker.abort()

    @property
    def busy(self) -> bool:
        return bool(self._running)

    def _on_started(self, job_id: int, name: str) -> None:
        self._running.add(job_id)
        self.busy_changed.emit(True, name)

    def _finish(self, job_id: int, name: str) -> tuple[Done | None, Fail | None]:
        self._running.discard(job_id)
        if not self._running:
            self.busy_changed.emit(False, name)
        return self._callbacks.pop(job_id, (None, None))

    def _on_done(self, job_id: int, name: str, result: Any) -> None:
        on_done, _ = self._finish(job_id, name)
        if on_done:
            on_done(result)

    def _on_failed(self, job_id: int, name: str, error: str, aborted: bool) -> None:
        _, on_fail = self._finish(job_id, name)
        self.status.emit("erro", f"{name}: {error}")
        if on_fail:
            on_fail(error, aborted)

    def _on_connection(self, connected: bool, description: str) -> None:
        self.connected = connected
        if not connected:
            self.idn = ""
        self.connection_changed.emit(connected, description or self.port_description)

    # ── conexão ─────────────────────────────────────────────────────────
    def discover(self, on_done: Done | None = None, on_fail: Fail | None = None,
                 deep: bool = False) -> None:
        """Procura a interface e o instrumento; o resultado é um ``Discovery``."""
        job = self.worker.discover(deep)
        self._callbacks[job] = (on_done, on_fail)

    def connect_port(self, port: str, address: int, read_tmo_ms: int, sync: str,
                     on_done: Done | None = None, baudrate: int = 115200) -> None:
        self.simulated = port == "SIMULADOR"
        if self.simulated:
            from ..sim.ar488 import SimLink
            from ..sim.hp4294a import Sim4294A

            self.sim_instrument = Sim4294A(time_scale=self.sim_time_scale)
            link = SimLink(self.sim_instrument, reset_delay=0.4, address=address)
        else:
            from ..transport.links import SerialLink

            self.sim_instrument = None
            link = SerialLink(port, baudrate)
        self.port_description = link.description
        self.set_capabilities(replace(self.caps, sync=sync))
        session = AR488Session(link, AR488Settings(address=address, read_tmo_ms=read_tmo_ms))
        job = self.worker.connect(session)
        self._callbacks[job] = (on_done, None)

    def disconnect_port(self) -> None:
        job = self.worker.disconnect()
        self._callbacks[job] = (None, None)

    def set_capabilities(self, caps: Capabilities) -> None:
        self.caps = caps
        self.worker.set_capabilities(caps)
        self.caps_changed.emit(caps)

    # ── estado compartilhado ────────────────────────────────────────────
    def set_config(self, cfg: MeasurementConfig) -> None:
        self.config = cfg
        self.config_changed.emit(cfg)

    def set_result(self, result: SweepResult) -> None:
        self.result = result
        self.set_compensation(result.compensation)
        self.result_ready.emit(result)

    def set_compensation(self, state: CompensationState) -> None:
        self.compensation = state
        self.compensation_changed.emit(state)

    def refresh_compensation(self) -> None:
        self.run("ler compensação", lambda ctx: ctx.driver.comp_state(), self.set_compensation)

    def shutdown(self) -> None:
        self.worker.stop()
        self.traffic_log.close()


__all__ = ["Controller", "TrafficEntry"]
