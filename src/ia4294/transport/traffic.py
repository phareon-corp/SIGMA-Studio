"""Registro de todo o tráfego da porta, com timestamp, em arquivo por sessão."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, TextIO

# Direções: ">" host → interface, "<" interface → host, "!" evento do app.
SEND = ">"
RECV = "<"
NOTE = "!"


@dataclass(frozen=True, slots=True)
class TrafficEntry:
    timestamp: datetime
    direction: str
    text: str

    def format(self) -> str:
        ts = self.timestamp.isoformat(timespec="milliseconds")
        return f"{ts} {self.direction} {self.text}"


Listener = Callable[[TrafficEntry], None]


class TrafficLog:
    """Grava cada linha trafegada num arquivo e avisa os ouvintes.

    Só a thread dona da porta escreve aqui; o lock existe porque eventos do
    app ("!") também podem vir da thread da GUI.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._listeners: list[Listener] = []
        self._fh: TextIO | None = None
        self.path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = path.open("a", encoding="utf-8")

    @classmethod
    def for_session(cls, directory: Path) -> "TrafficLog":
        name = datetime.now().strftime("sessao_%Y%m%d-%H%M%S.log")
        return cls(directory / name)

    def add_listener(self, fn: Listener) -> None:
        self._listeners.append(fn)

    def record(self, direction: str, text: str) -> TrafficEntry:
        entry = TrafficEntry(datetime.now(), direction, text)
        with self._lock:
            if self._fh is not None:
                self._fh.write(entry.format() + "\n")
                self._fh.flush()
        for fn in list(self._listeners):
            fn(entry)
        return entry

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                self._fh.close()
                self._fh = None
