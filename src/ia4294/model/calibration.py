"""Os três procedimentos de calibração do 4294A, como dados.

Tudo aqui vem do Operation Manual (cap. 4 "Adapter Setting", cap. 6
"Calibration", Tabelas 6-1, B-35, B-36, B-37):

* **Setup do adaptador** (``[Cal] → ADAPTER → SETUP``): mede a fase do
  caminho até o fixture e grava na memória não volátil. Com o 16451B ligado
  direto no painel, o procedimento do cap. 4 pede só PHASE COMP (``ECALP``) e
  depois ``ECALDON``. Uma vez só, ou quando a temperatura muda mais de ±5 °C.
* **Compensação do fixture** (``FIXTURE COMPEN``): OPEN/SHORT/LOAD nos
  eletrodos. É a "calibração" do 16451B no dia a dia. Com LOAD, as teclas do
  16451B são invertidas (p. 136).
* **Calibração de usuário** (``USER CAL``): OPEN/SHORT/LOAD com kit padrão
  na porta. Só existe com 42942A ou 42941A (p. 147). Com 4TP 1M — o caso do
  16451B — o manual diz que ela "cannot be performed" (p. 135).
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: o que cada código de erro de calibração quer dizer, para a tela
CAL_ERRORS = {
    10: "ADDITIONAL STANDARDS NEEDED — falta medir algum padrão antes do done",
    11: "CALIBRATION REQUIRED — o padrão ainda não foi medido",
    -213: "Init ignored — havia outra medida em curso",
}

#: acima disto o SHORT pode dar "REDUCE OSC LEVEL" / "BRIDGE UNBALANCED" (p. 151)
COMP_MAX_OSC_V = 0.5

USER_CAL_ADAPTERS = ("APC7", "PROBE")


@dataclass(frozen=True)
class CalStep:
    key: str  # rótulo curto: "PHASE COMP", "OPEN"…
    command: str  # mensagem GPIB do passo
    instruction: str  # o que a pessoa faz no fixture antes
    measures: bool = True  # True = varredura longa com espera; False = comando instantâneo
    optional: bool = False
    estimate_s: float = 20.0  # só para a barra; o fim vem do instrumento


@dataclass(frozen=True)
class Procedure:
    key: str  # "adapter" | "fixture" | "user"
    title: str
    summary: str
    steps: tuple[CalStep, ...]
    pre: str = ""  # mensagem enviada antes do primeiro passo
    notes: tuple[str, ...] = field(default_factory=tuple)
    available: bool = True
    unavailable_reason: str = ""


def adapter_setup(adapter: str = "M1") -> Procedure:
    return Procedure(
        "adapter", "Setup do adaptador",
        "Mede a fase do caminho até o 16451B e grava na memória não volátil do 4294A. "
        "Faz-se uma vez; refaça se a temperatura da sala mudar mais de 5 °C.",
        (
            CalStep("ADAPTADOR", f"E4TP {adapter}",
                    "Seleciona o adaptador. Para o 16451B o manual manda 4TP 1M (Adapter Selection, cap. 4).",
                    measures=False),
            CalStep("PHASE COMP", "ECALP",
                    "16451B ligado direto nos quatro conectores do painel, sem cabo nem adaptador. "
                    "4294A ligado há mais de 30 min. Contatos do 16451B em OPEN. "
                    "Leva alguns minutos; a tela do 4294A mostra WAIT--MEASURING ADJUSTMENT KIT.",
                    estimate_s=180.0),
            CalStep("DONE", "ECALDON",
                    "Calcula e grava o setup. Se voltar o erro 10, o instrumento quer mais algum "
                    "padrão — pare e confira o menu SETUP na tela.",
                    measures=False),
        ),
        notes=(
            "O slot 4TP 1M é o mesmo do cabo 16048G. Se o setup foi feito com o cabo, ele descreve "
            "o cabo — refazer com o 16451B montado sobrescreve.",
            "A Tabela B-36 pede LOAD do adaptador para 4TP 1M em geral (cabo + resistor); o "
            "procedimento do 16451B (p. 73) pede só PHASE COMP. Este assistente segue o do 16451B.",
        ),
    )


def fixture_compensation(include_load: bool, short_r: float = 0.0, short_l: float = 0.0,
                         load_c: float = 0.0, load_g: float = 0.0) -> Procedure:
    std = f"DCALSHORR {short_r:g};DCALSHORL {short_l:g}"
    if include_load:
        # p. 136: o 4294A modela padrões como R-L série; o 16451B precisa de C-G paralelo
        std = f"DCALLOADR 100E9;DCALLOADL 0;DCALOPENC {load_c:g};DCALOPENG {load_g:g};" + std
        steps = (
            CalStep("OPEN", "COMC",
                    "Eletrodos em OPEN, na mesma distância de quando a amostra está entre eles. "
                    "Com LOAD, o OPEN do 16451B é medido pela tecla LOAD — por isso COMC."),
            CalStep("SHORT", "COMB",
                    "Eletrodos em curto: superior encostado no inferior, sem amostra."),
            CalStep("LOAD", "COMA",
                    "Padrão de carga entre os eletrodos (Cp e G conhecidos). "
                    "A carga do 16451B é medida pela tecla OPEN — por isso COMA."),
        )
    else:
        steps = (
            CalStep("OPEN", "COMA",
                    "Eletrodos em OPEN, na mesma distância de quando a amostra está entre eles."),
            CalStep("SHORT", "COMB",
                    "Eletrodos em curto: superior encostado no inferior, sem amostra."),
        )
    return Procedure(
        "fixture", "Compensação do fixture",
        "Remove os parasitas do 16451B. Cada padrão é uma varredura; o 4294A liga a "
        "compensação correspondente sozinho ao terminar.",
        steps, pre=std,
        notes=(
            "Antes do OPEN o app aplica o perfil da aba Medida. Com CALP USER a compensação vale "
            "só para esses pontos; trocar CALP depois invalida os dados (p. 155).",
            "Oscilador acima de 500 mV pode dar REDUCE OSC LEVEL no SHORT (p. 151): durante a "
            "compensação o app limita POWE a 500 mV.",
            "Com 1 m de extensão aparece um degrau no traço em 5 MHz; só o LOAD o remove (p. 151).",
        ),
    )


def user_calibration(adapter: str) -> Procedure:
    ok = adapter in USER_CAL_ADAPTERS
    return Procedure(
        "user", "Calibração de usuário",
        "OPEN, SHORT e LOAD com kit padrão no plano da porta. Os três são obrigatórios e "
        "ligam juntos (CALST).",
        (
            CalStep("OPEN", "CALA", "Padrão OPEN no plano de calibração."),
            CalStep("SHORT", "CALB", "Padrão SHORT no plano de calibração."),
            CalStep("LOAD", "CALC", "Padrão LOAD (50 Ω, ou o valor definido) no plano de calibração."),
            CalStep("DONE", "CALDON", "Calcula os coeficientes e liga a calibração.", measures=False),
        ),
        available=ok,
        unavailable_reason=(
            "" if ok else
            "Com o adaptador atual (E4TP " + adapter + ") o 4294A não aceita calibração de usuário: "
            "\"User calibration can be performed only when 42942A or 42941A is selected\" (p. 147). "
            "Para o 16451B a calibração é o setup do adaptador seguido da compensação do fixture."
        ),
    )


def explain_error(code: int, msg: str) -> str:
    return f"{code} {CAL_ERRORS.get(code, msg)}"
