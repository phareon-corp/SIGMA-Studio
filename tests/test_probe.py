from ia4294 import paths
from ia4294.instrument.capabilities import Capabilities
from ia4294.instrument.probe import main, probe


def test_probe_on_simulator(session):
    log = []
    caps = probe(session, log.append)
    assert caps.probed and caps.idn.startswith("HEWLETT-PACKARD")
    assert caps.trace_query == "OUTPDTRC?"
    assert caps.queries["OUTPDTRC?"]["depends_on_trace"] is True
    # OUTPDATA? responde, mas é o mesmo array nos dois traços
    assert caps.queries["OUTPDATA?"]["ok"] and not caps.queries["OUTPDATA?"]["depends_on_trace"]
    assert caps.sweep_query == "OUTPSWPRM?"
    assert caps.queries["OUTPSWPRMP?"]["ok"] is False
    assert caps.formats == {"FORM4": True, "FORM3": True, "FORM2": True, "FORM5": True}
    assert caps.sync_tests == {"spoll": True, "opc_query": True} and caps.sync == "spoll"
    assert caps.binary_format is None  # binário só registrado
    assert caps.queries["FORM3 OUTPDTRC?"]["ok"]


def test_capabilities_roundtrip(tmp_path):
    c = Capabilities(probed=True, trace_query="OUTPDATA?", sweep_query=None, sync="opc_query")
    p = tmp_path / "c.json"
    c.save(p)
    assert Capabilities.load(p) == c
    assert Capabilities.load_or_default(tmp_path / "nao.json") == Capabilities()


def test_probe_cli_sim(capsys):
    assert main(["--sim"]) == 0
    caps = Capabilities.load(paths.capabilities_file())
    assert caps.probed and caps.trace_query == "OUTPDTRC?"
