"""O ciclo inteiro, sem hardware: configura, dispara, lê, exporta."""

import threading

import numpy as np
import pandas as pd

from ia4294 import paths
from ia4294.instrument.hp4294a import HP4294A
from ia4294.model import dielectric, export
from ia4294.model.config import MeasurementConfig
from ia4294.model.params import to_cp_d


def test_configure_trigger_read_export(session, sim):
    cfg = MeasurementConfig(meas="CPD", sweep_type="LOG", start=1e3, stop=1e7, points=101,
                            bw=2, averaging_on=True, averaging_factor=3)
    drv = HP4294A(session)

    result, reports = drv.acquire(cfg, threading.Event())

    # configurou: cada bloco conferido com OUTPERRO?
    assert [r.name for r in reports] == ["estado", "medida", "fonte", "varredura", "exatidão", "disparo"]
    assert all(r.ok for r in reports)
    assert sim.state["MEAS"] == "CPD" and sim.state["POIN"] == 101 and sim.state["AVER"] is True
    # disparou: NUMG = fator de média
    assert sim.sweep_count >= 3
    # leu: eixo calculado de STAR/STOP/POIN, traços com o tamanho certo
    assert np.allclose(result.x, np.geomspace(1e3, 1e7, 101))
    assert result.trace_a.shape == result.trace_b.shape == (101,)
    assert np.allclose(result.trace_a, sim.trace_a) and np.allclose(result.trace_b, sim.trace_b)
    assert result.idn.startswith("HEWLETT-PACKARD,4294A")
    assert 5e-12 < result.trace_a.mean() < 5e-11  # ~10 pF do capacitor de 38 mm × 1 mm

    # exportou: um arquivo por formato, cabeçalho espelhando o 4294A
    out = export.export_run(result, paths.data_dir(), ("csv", "parquet"))
    assert [p.suffix for p in out] == [".csv", ".parquet"]
    assert all(p.stem.startswith("4294A_") and p.stem.endswith("_CPD") for p in out)

    df, meta = export.read_csv(out[0])
    assert list(df.columns) == ["frequency_Hz", "Cp_F", "D"]
    assert len(df) == 101
    assert np.allclose(df["Cp_F"], result.trace_a, rtol=1e-11)
    for key in ("DATE", "MEASURE PARAMETER", "ADAPTER", "SWEEP TYPE", "NUMBER of POINTS",
                "OSC LEVEL", "DC BIAS", "BW", "SWEEP AVERAGING", "COMPENSATION"):
        assert key in meta
    assert meta["SWEEP TYPE"] == "LOG FREQ"
    assert meta["NUMBER of POINTS"] == "101"
    assert meta["SWEEP AVERAGING"] == "ON 3"
    assert meta["COMPENSATION"] == "OPEN OFF · SHORT OFF · LOAD OFF"

    pq_df, pq_meta = export.read_parquet(out[1])
    pd.testing.assert_frame_equal(pq_df, df, check_exact=False, rtol=1e-12)
    assert pq_meta == meta


def test_dielectric_from_simulated_sample(session, sim):
    """Com OPEN/SHORT/LOAD ligadas, eps' volta ao modelo da amostra."""
    cfg = MeasurementConfig(meas="CPD", sweep_type="LOG", start=1e3, stop=1e6, points=31, bw=5)
    drv = HP4294A(session)
    drv.apply(cfg)
    for key in ("COMA", "COMB", "COMC"):
        assert drv.comp_measure(key, cfg, threading.Event()) == []
    assert drv.set_comp(True, True, True).ok
    result, _ = drv.acquire(cfg, threading.Event(), apply=False)

    geom = dielectric.Geometry(sim.sample.thickness_m, sim.sample.electrode_diameter_m)
    d = dielectric.compute(result, geom)
    eps_hi = sim.sample.eps_inf
    eps_lo = sim.sample.eps_inf + sim.sample.delta_eps
    assert eps_hi < d.eps_real[-1] < d.eps_real[0] < eps_lo + 0.1
    assert np.all(d.tan_delta > 0)

    out = export.export_run(result, paths.data_dir(), ("csv",), dielectric=d)
    df, meta = export.read_csv(out[0])
    assert {"eps_r_real", "tan_delta"} <= set(df.columns)
    assert meta["THICKNESS"] == "1 mm" and meta["ELECTRODE DIAMETER"] == "38 mm"


def test_to_cp_d_equivalences():
    f = np.array([1e3, 1e5])
    cp = np.array([10e-12, 9e-12])
    dd = np.array([0.01, 0.05])
    w = 2 * np.pi * f
    g = dd * w * cp
    assert np.allclose(to_cp_d("CPG", f, cp, g)[1], dd)
    assert np.allclose(to_cp_d("CPQ", f, cp, 1 / dd)[1], dd)
    assert np.allclose(to_cp_d("CPR", f, cp, 1 / g)[1], dd)
