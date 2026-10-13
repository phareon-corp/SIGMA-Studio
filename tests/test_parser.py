import numpy as np
import pytest

from ia4294.instrument.parser import (
    ParseError, parse_block, parse_bool, parse_error, parse_idn, parse_number, parse_numbers,
    parse_savdasc, per_point, split_block_header,
)


def test_numbers_form4():
    v = parse_numbers("+1.00000000000E+003,-2.5E-012,+0.00000000000E+000\n")
    assert v.tolist() == [1e3, -2.5e-12, 0.0]


def test_numbers_rejects_garbage():
    with pytest.raises(ParseError):
        parse_numbers("abc,1")
    with pytest.raises(ParseError):
        parse_numbers("   ")


def test_single_number_and_int_like():
    assert parse_number("+201") == 201
    with pytest.raises(ParseError):
        parse_number("1,2")


@pytest.mark.parametrize("text,code,msg", [
    ('0,"No error"', 0, "No error"),
    ("0", 0, "No error"),
    ('-113,"Undefined header"', -113, "Undefined header"),
    ('+11,"CALIBRATION REQUIRED"', 11, "CALIBRATION REQUIRED"),
])
def test_error(text, code, msg):
    assert parse_error(text) == (code, msg)


@pytest.mark.parametrize("text,val", [("1", True), ("0", False), ("ON", True), ("off", False), ("+1", True)])
def test_bool(text, val):
    assert parse_bool(text) is val


def test_idn():
    i = parse_idn("HEWLETT-PACKARD,4294A,MY43201776,REV1.11\n")
    assert i.is_4294a and i.serial == "MY43201776" and i.firmware == "REV1.11"
    with pytest.raises(ParseError):
        parse_idn("AR488 GPIB controller")


@pytest.mark.parametrize("form,dt", [("FORM2", ">f4"), ("FORM3", ">f8"), ("FORM5", "<f4")])
def test_binary_block(form, dt):
    vals = np.array([1.5, -2.25, 1e6])
    raw = b"#6" + f"{len(vals) * np.dtype(dt).itemsize:06d}".encode() + vals.astype(dt).tobytes()
    assert np.allclose(parse_block(split_block_header(raw), form), vals)


def test_per_point():
    pairs = np.array([1, 0, 2, 0, 3, 0], float)
    v, k = per_point(pairs, 3)
    assert v.tolist() == [1, 2, 3] and k == 2
    v, k = per_point(np.array([1.0, 2.0]), 2)
    assert k == 1
    with pytest.raises(ParseError):
        per_point(np.arange(5.0), 3)


MANUAL_EXAMPLE = '''4294A REV1.01
"DATE: Nov 1 1999"
"MEASURE PARAMETER: IMPEDANCE MAG PHASE (DEG)"
"ADAPTER: NONE"
"SWEEP TYPE: LIN FREQ"
"NUMBER of POINTS: 2"
"OSC LEVEL: 500 mVolt"
"DC BIAS: OFF"
"BW: 1"
"Cal Point: FIXED"
"Frequency""Comp[open] Real""Comp[open] Imag"
4.00000000000e+01 2.947073e-09 -1.565653e-09
"TRACE: A"
"FORMAT: LOG"
"Frequency" "Data Real" "Data Imag" "Data Trace Real" "Data Trace Imag"
4.00000000000e+01 1.976390e-02 5.641327e-03 2.055326e-02 0.000000e+00
8.00000000000e+01 1.976390e-02 5.641327e-03 2.155326e-02 0.000000e+00
"TRACE: B"
"FORMAT: LINEAR"
"Frequency" "Data Real" "Data Imag" "Data Trace Real" "Data Trace Imag"
4.00000000000e+01 1.976390e-02 5.641327e-03 1.593065e+01 0.000000e+00
8.00000000000e+01 1.976390e-02 5.641327e-03 1.693065e+01 0.000000e+00
'''


def test_savdasc_manual_example():
    f = parse_savdasc(MANUAL_EXAMPLE)
    assert f.revision == "4294A REV1.01"
    assert f.header["NUMBER of POINTS"] == "2"
    assert f.header["SWEEP TYPE"] == "LIN FREQ"
    assert set(f.traces) == {"A", "B"}
    assert f.traces["A"].fmt == "LOG" and f.traces["B"].fmt == "LINEAR"
    assert f.traces["A"].frequency.tolist() == [40.0, 80.0]
    assert f.traces["B"].data_trace.tolist() == [15.93065, 16.93065]
