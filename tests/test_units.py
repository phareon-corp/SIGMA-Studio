import pytest

from ia4294.model.units import format_eng, parse_eng


@pytest.mark.parametrize("text,v", [("10M", 10e6), ("500m", 0.5), ("100E9", 100e9), ("2.2p", 2.2e-12),
                                    ("1 kHz", 1e3), ("40", 40.0), ("-1.5u", -1.5e-6), ("10 pF", 10e-12),
                                    ("0,5", 0.5)])
def test_parse(text, v):
    assert parse_eng(text) == pytest.approx(v)


def test_parse_rejects():
    with pytest.raises(ValueError):
        parse_eng("dez")


@pytest.mark.parametrize("v,unit,out", [(1.2e-11, "F", "12 pF"), (1e6, "Hz", "1 MHz"), (0.5, "V", "500 mV"),
                                        (0, "Ω", "0 Ω"), (0.0123, "", "0.0123"), (999.99e3, "Hz", "1 MHz")])
def test_format(v, unit, out):
    assert format_eng(v, unit, 4) == out
