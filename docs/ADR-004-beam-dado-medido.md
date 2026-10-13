# ADR-004 — `--beam` #4FE0FF como cor do traço medido (ia4294)

- **Data:** 2026-10-09
- **Status:** **proposto**, aguardando aceite em `~/Documentos/Phareon/Design/decisoes/`
- **Afeta:** ia4294 (app de bancada); não muda o site
- **Responde a:** ADR-002, que reserva o ciano e exige um ADR antes do primeiro uso

## Contexto

O ia4294 é uma interface de instrumento. Mostra dois traços medidos pelo HP 4294A
(Cp e D, |Z| e θ…) e a permissividade calculada a partir deles. O ADR-002
reservou o ciano com um significado já atribuído: **laranja = a fonte, ciano =
o dado medido**. Este é o primeiro artefato que precisa exatamente disso.

## As três perguntas do ADR-002

**1. Que informação só o ciano comunica?**
"Isto foi lido do instrumento." Os traços A e B e as curvas ε′ e tan δ são
desenhados em `--beam`. Nada mais na interface usa ciano: nem rótulos, nem
botões, nem estados. Se aparece ciano, é medida.

**2. Como fica o orçamento combinado das duas cores de sinal?**
- Laranja: botão primário (um por bloco), numeral `0N /` da seção, dot do
  eyebrow, barra do passo ativo na compensação, barra de progresso *enquanto há
  progresso real* (volta a zero ao terminar), cursor de leitura, anel de foco.
  Caixas de seleção marcadas usam `--ink`, não acento, para não estourar os 8%.
- Ciano: só traços de 1,6 px sobre `--bg`. Por ser linha fina, a área ocupada
  fica abaixo de 2% mesmo com os dois gráficos cheios.
- Somado: tem de ficar abaixo dos 14% que o ADR-003 permite para duas tintas.
  Ainda não foi medido nas capturas de tela; é a primeira coisa a conferir no
  aceite.

**3. O que acontece no terreno claro?**
Nada: o app usa só o terreno escuro. Não existe tela clara no ia4294. Se um
dia houver exportação de gráfico para papel/claro, o traço vira `--ink-dark` e
este ADR precisa de revisão (ciano sobre `--bg-light` dá ~1,6:1).

## Decisão proposta

Liberar `--beam` **apenas** para traço de dado medido em gráfico, no terreno
escuro, em linha fina. Continua proibido como texto, fundo, borda ou estado.

## Implementação

- `src/ia4294/ui/widgets.py` → `data_pen()` é o único ponto que lê `beam`.
- Os tokens vêm de `src/ia4294/ui/assets/phareon-tokens.css`, cópia literal de
  `tokens/tokens.css`. Se o token mudar lá, copie o arquivo de novo.

## Se for recusado

Troque `data_pen()` para `--ink`. Nenhum outro arquivo muda.
