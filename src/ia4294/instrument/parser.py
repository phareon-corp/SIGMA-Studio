"""Interpretação das respostas do 4294A. Sem I/O, sem estado."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

_SPLIT = re.compile(r"[,;\s]+")


class ParseError(ValueError):
    pass


def parse_numbers(text: str) -> np.ndarray:
    """Array ASCII (FORM4): números separados por vírgula."""
    parts = [p for p in _SPLIT.split(text.strip()) if p]
    if not parts:
        raise ParseError("resposta vazia")
    try:
        return np.array([float(p) for p in parts], dtype=float)
    except ValueError as exc:
        raise ParseError(f"não numérico: {text[:60]!r}") from exc


def parse_number(text: str) -> float:
    arr = parse_numbers(text)
    if arr.size != 1:
        raise ParseError(f"esperava 1 número, veio {arr.size}")
    return float(arr[0])


def parse_bool(text: str) -> bool:
    t = text.strip().upper()
    if t in ("1", "ON", "+1"):
        return True
    if t in ("0", "OFF", "+0"):
        return False
    raise ParseError(f"não é booleano: {text!r}")


def parse_error(text: str) -> tuple[int, str]:
    """OUTPERRO? → ``(código, mensagem)``. Aceita ``0`` ou ``0,"No error"``."""
    t = text.strip()
    num, _, msg = t.partition(",")
    try:
        code = int(float(num))
    except ValueError as exc:
        raise ParseError(f"OUTPERRO? ilegível: {text!r}") from exc
    return code, msg.strip().strip('"') or ("No error" if code == 0 else "")


@dataclass(frozen=True, slots=True)
class Identity:
    manufacturer: str
    model: str
    serial: str
    firmware: str

    @property
    def is_4294a(self) -> bool:
        return self.model.upper() == "4294A"


def parse_idn(text: str) -> Identity:
    parts = [p.strip() for p in text.strip().split(",")]
    if len(parts) != 4:
        raise ParseError(f"*IDN? fora do padrão: {text!r}")
    return Identity(*parts)


# FORM2 = IEEE 32 bits big-endian, FORM3 = IEEE 64 bits big-endian,
# FORM5 = IEEE 32 bits little-endian (ordem de PC).
BINARY_DTYPES = {"FORM2": ">f4", "FORM3": ">f8", "FORM5": "<f4"}


def parse_block(data: bytes, form: str) -> np.ndarray:
    dt = np.dtype(BINARY_DTYPES[form])
    if len(data) % dt.itemsize:
        raise ParseError(f"bloco de {len(data)} bytes não divide em {form}")
    return np.frombuffer(data, dtype=dt).astype(float)


def split_block_header(raw: bytes) -> bytes:
    """Remove ``#<n><len>`` de um bloco definido IEEE 488.2."""
    if raw[:1] != b"#" or not raw[1:2].isdigit():
        raise ParseError("não começa com #<n>")
    n = int(raw[1:2])
    length = int(raw[2 : 2 + n])
    body = raw[2 + n : 2 + n + length]
    if len(body) != length:
        raise ParseError("bloco truncado")
    return body


def per_point(values: np.ndarray, points: int) -> tuple[np.ndarray, int]:
    """Reduz um array de traço ao valor principal de cada ponto.

    Os arrays do 4294A vêm com 1 ou 2 valores por ponto (real, imag); num
    traço formatado escalar o primeiro é o valor e o segundo é 0.
    """
    if values.size == points:
        return values, 1
    if values.size == 2 * points:
        return values[0::2].copy(), 2
    raise ParseError(f"{values.size} valores para {points} pontos")


# ── SAVDASC ─────────────────────────────────────────────────────────────
@dataclass(slots=True)
class AsciiTrace:
    name: str
    fmt: str
    columns: list[str]
    data: np.ndarray  # (pontos, colunas)

    @property
    def frequency(self) -> np.ndarray:
        return self.data[:, 0]

    @property
    def data_trace(self) -> np.ndarray:
        """Coluna "Data Trace Real" — o valor exibido na tela."""
        i = self.columns.index("Data Trace Real") if "Data Trace Real" in self.columns else 3
        return self.data[:, i]


@dataclass(slots=True)
class AsciiFile:
    revision: str
    header: dict[str, str] = field(default_factory=dict)
    traces: dict[str, AsciiTrace] = field(default_factory=dict)


_QUOTED = re.compile(r'"([^"]*)"')


def parse_savdasc(text: str) -> AsciiFile:
    """Arquivo .TXT gravado pelo próprio 4294A (SAVDASC), Tabela 8-5 do manual."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ParseError("arquivo vazio")
    out = AsciiFile(revision=lines[0].strip())
    cur: AsciiTrace | None = None
    rows: list[list[float]] = []

    def close() -> None:
        nonlocal cur, rows
        if cur is not None and cur.name != "_cal":
            cur.data = np.array(rows, dtype=float).reshape(len(rows), len(cur.columns))
            out.traces[cur.name] = cur
        cur, rows = None, []

    i = 1
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith('"'):
            quoted = _QUOTED.findall(ln)
            if len(quoted) > 1 or (quoted and ":" not in quoted[0]):
                # linha de nomes de coluna
                if cur is None:  # bloco de dados de compensação, ignorado
                    cur = AsciiTrace("_cal", "", quoted, np.empty((0, 0)))
                else:
                    cur.columns = quoted
                i += 1
                continue
            key, _, val = quoted[0].partition(":")
            key, val = key.strip(), val.strip()
            if key == "TRACE":
                close()
                cur = AsciiTrace(val, "", [], np.empty((0, 0)))
            elif key == "FORMAT" and cur is not None:
                cur.fmt = val
            elif cur is None:
                out.header[key] = val
        elif cur is not None and cur.columns and cur.name != "_cal":
            rows.append([float(x) for x in ln.split()])
        i += 1
    close()
    out.traces.pop("_cal", None)
    return out
