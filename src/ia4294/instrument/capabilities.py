"""O que o 4294A conectado aceita, descoberto pelo probe e lido pelo app."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class Capabilities:
    probed: bool = False
    idn: str = ""
    probed_at: str = ""
    #: formato ASCII de transferência (o único que dispensa leitura binária)
    ascii_format: str = "FORM4"
    #: formato binário que funcionou, se algum
    binary_format: str | None = None
    #: consulta que devolve o traço ativo (TRAC A/B), formatado
    trace_query: str = "OUTPDTRC?"
    #: consulta do eixo de varredura — só é necessária em SWPT LIST
    sweep_query: str | None = "OUTPSWPRM?"
    #: estratégia de espera: "spoll" (status byte) ou "opc_query" (*OPC?)
    sync: str = "spoll"
    formats: dict[str, bool] = field(default_factory=dict)
    queries: dict[str, dict] = field(default_factory=dict)
    sync_tests: dict[str, bool] = field(default_factory=dict)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Capabilities":
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def load_or_default(cls, path: Path) -> "Capabilities":
        try:
            return cls.load(path)
        except (OSError, ValueError, TypeError):
            return cls()

    def summary(self) -> str:
        if not self.probed:
            return "sem probe — usando OUTPDTRC? e FORM4 por convenção HP"
        sweep = self.sweep_query or "calculado"
        return (f"traço {self.trace_query} · eixo {sweep} · {self.ascii_format}"
                f"{' · ' + self.binary_format if self.binary_format else ''} · espera {self.sync}")
