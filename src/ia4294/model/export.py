"""Exportação CSV/Parquet com cabeçalho espelhando o do 4294A (SAVDASC).

Uma corrida = um arquivo por formato, nome com timestamp.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path

import pandas as pd

from .. import __version__
from .config import ADAPTERS
from .dielectric import DielectricResult
from .sweep import SweepResult


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def header(result: SweepResult, dielectric: DielectricResult | None = None) -> "OrderedDict[str, str]":
    """Mesmos campos, na mesma ordem, do cabeçalho ASCII do 4294A (Tabela 8-5)."""
    c = result.config
    p = result.param
    h: OrderedDict[str, str] = OrderedDict()
    h["INSTRUMENT"] = result.idn or "4294A"
    t = result.timestamp  # mês em inglês, como o 4294A escreve — %b segue o locale
    h["DATE"] = f"{_MONTHS[t.month - 1]} {t:%d %Y %H:%M:%S}"
    h["MEASURE PARAMETER"] = f"{p.long_name} ({c.meas})"
    h["ADAPTER"] = ADAPTERS.get(c.adapter, c.adapter)
    ax = result.axis
    h["SWEEP TYPE"] = f"{c.sweep_type} {ax.header}"
    if not ax.is_frequency:
        # a curva C-V (ou C-Vosc) inteira foi levantada nesta frequência
        h["FIXED FREQUENCY (CWFREQ)"] = f"{c.cw_freq_hz:g} Hz"
    h["NUMBER of POINTS"] = str(result.points)
    h["OSC LEVEL"] = c.osc_text()
    h["DC BIAS"] = c.bias_text()
    h["BW"] = str(c.bw)
    h["SWEEP AVERAGING"] = f"ON {c.averaging_factor}" if c.averaging_on else "OFF"
    h["POINT AVERAGING"] = f"ON {c.point_avg_factor}" if c.point_avg_on else "OFF"
    h["Cal Point"] = c.cal_point
    h["COMPENSATION"] = result.compensation.text()
    h["TRACE A"] = f"{p.a.symbol} [{p.a.unit or '-'}] FORMAT {c.fmt_a}"
    h["TRACE B"] = f"{p.b.symbol} [{p.b.unit or '-'}] FORMAT {c.fmt_b}"
    h["SOURCE"] = result.source
    if dielectric is not None:
        g = dielectric.geometry
        h["THICKNESS"] = f"{g.thickness_m * 1e3:g} mm"
        h["ELECTRODE DIAMETER"] = f"{g.electrode_diameter_m * 1e3:g} mm"
    for k, v in result.notes.items():
        h[k.upper()] = v
    h["SOFTWARE"] = f"ia4294 {__version__}"
    return h


def dataframe(result: SweepResult, dielectric: DielectricResult | None = None) -> pd.DataFrame:
    p = result.param
    df = pd.DataFrame({
        result.axis.column: result.x,
        p.a.column: result.trace_a,
        p.b.column: result.trace_b,
    })
    if dielectric is not None:
        df["eps_r_real"] = dielectric.eps_real
        df["tan_delta"] = dielectric.tan_delta
    return df


def file_stem(result: SweepResult) -> str:
    return f"4294A_{result.timestamp:%Y%m%d-%H%M%S}_{result.config.meas}"


def write_csv(result: SweepResult, path: Path, dielectric: DielectricResult | None = None) -> Path:
    lines = [f'# "{k}: {v}"' for k, v in header(result, dielectric).items()]
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(lines) + "\n")
        dataframe(result, dielectric).to_csv(fh, index=False, float_format="%.12e")
    return path


def write_parquet(result: SweepResult, path: Path, dielectric: DielectricResult | None = None) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pandas(dataframe(result, dielectric), preserve_index=False)
    meta = dict(table.schema.metadata or {})
    meta[b"ia4294.header"] = json.dumps(header(result, dielectric), ensure_ascii=False).encode()
    meta[b"ia4294.config"] = json.dumps(result.config.to_dict()).encode()
    pq.write_table(table.replace_schema_metadata(meta), path)
    return path


def export_run(result: SweepResult, directory: Path, formats: tuple[str, ...] = ("csv",),
               dielectric: DielectricResult | None = None) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stem = file_stem(result) + ("_dieletrico" if dielectric is not None else "")
    out: list[Path] = []
    for fmt in formats:
        if fmt == "csv":
            out.append(write_csv(result, directory / f"{stem}.csv", dielectric))
        elif fmt == "parquet":
            out.append(write_parquet(result, directory / f"{stem}.parquet", dielectric))
        else:
            raise ValueError(f"formato {fmt} desconhecido")
    return out


def read_csv(path: Path) -> tuple[pd.DataFrame, dict[str, str]]:
    meta: dict[str, str] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("#"):
                break
            body = line[1:].strip().strip('"')
            k, _, v = body.partition(": ")
            meta[k] = v
    return pd.read_csv(path, comment="#"), meta


def read_parquet(path: Path) -> tuple[pd.DataFrame, dict[str, str]]:
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    meta = json.loads(table.schema.metadata[b"ia4294.header"])
    return table.to_pandas(), meta
