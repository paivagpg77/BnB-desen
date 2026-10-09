# Lei do Bem - Apoio à análise preliminar de elegibilidade

Ferramenta de apoio ao analista de P&D do Banco do Nordeste (BNB), desenvolvida no
Hackathon STS 2026. **A IA propõe; o analista decide.**

Base de referência: `docs/base_projeto_v0.2.txt`
Decisões de stack: `docs/adr/0001-stack.md` e `docs/adr/0002-interface-streamlit.md`

## Estado atual (Fase 1, em andamento)

- [x] Máquina de estados dos pontos D1 a D5, com analista identificado, motivo obrigatório e reabertura por dependência
- [x] Schemas do módulo de discordâncias e precedentes internos
- [x] Regra de convergência (revisão cega) e de padrão candidato
- [x] Ingestão de TXT, MD, CSV e JSON (PDF ainda não suportado)
- [x] Divisão em trechos por unidade lógica (cabeçalho ou artigo), com trecho_id estável
- [x] Busca lexical BM25 sem dependências, com filtro por norma ou por projeto
- [x] Verificador de citações: trecho existe, foi recuperado, literal confere e cobertura lexical
- [x] Bloqueio de proposta sem citação ou com citação falha
- [x] Dossiê em Markdown a partir de decisões confirmadas, com referências conferidas
- [x] Carregador do pacote do desafio (CSV com BOM e ponto e vírgula, JSON, MD, PDF), com os identificadores e âncoras do próprio pacote
- [x] Conferência de `resultados.csv` contra `medicoes.csv`, sem modelo de linguagem
- [x] Resolução de referências (`PRJ21-EV08`, `PRJ21-S01`, `evidencias/metodo.md#2`): fonte que não existe bloqueia a proposta
- [x] Cliente do OpenRouter atrás de uma interface, com o modelo como configuração
- [x] Base de regras citável (`dados/normas/criterios_analise.md`) e regra explícita de classificação a partir dos estados dos critérios
- [x] RAG: corpus do projeto com identificadores do pacote, núcleo obrigatório mais busca lexical dentro de um orçamento de contexto
- [x] Motor de análise com LLM: proposta conferida fonte a fonte; critério sem fonte válida é rebaixado
- [x] Fluxo D1 a D5 ligado ao motor; a classificação é derivada do que o analista confirmou
- [x] Servidor MCP com as ferramentas de leitura das evidências
- [x] Interface Streamlit básica, do projeto ao dossiê
- [x] Log das decisões em disco, somente de anexação: a análise salva volta com as decisões já registradas
- [x] Rever um ponto já decidido: ele e os pontos que dependem dele voltam a aguardar decisão
- [x] Fila de reserva por papel: provedor sem cota ou fora do ar é substituído pelo seguinte
- [x] Discordâncias, revisão cega por um segundo analista e precedentes internos na interface
- [ ] Calibração contra PRJ01 a PRJ20 (`scripts/calibrar.py`), aguardando chave do modelo
- [ ] Busca semântica (embeddings): sem prioridade, o contexto por projeto é pequeno

Os dados em `dados/fixtures/` são fictícios e servem só para teste. Não são legislação nem projetos reais.

## Rodar os testes

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

No Windows, troque `.venv/bin/` por `.venv\Scripts\` em todos os comandos.

## Massa do hackathon e modelo de linguagem

A configuração local fica no arquivo `.env`, na raiz do projeto, que nunca vai
para o git. Copie o modelo e preencha:

```bash
cp .env.example .env
```

| Variável | Para que serve |
|---|---|
| `OPENROUTER_API_KEY` | Chave do OpenRouter |
| `GEMINI_API_KEY` | Chave do Gemini (aistudio.google.com/apikey) |
| `GROQ_API_KEY` | Chave do Groq (console.groq.com/keys) |
| `OPENROUTER_MODEL` | Modelo usado; em branco, vale o gratuito padrão |
| `LEI_DO_BEM_PACOTE` | Pasta onde o pacote do hackathon foi extraído (a que contém `01_projetos`) |
| `LEI_DO_BEM_SAIDA` | Pasta das análises, dos logs e dos dossiês; em branco, vale `saida/` |

A massa é confidencial e **não entra no repositório**: extraia o pacote em uma
pasta fora dele. Sem `LEI_DO_BEM_PACOTE`, os testes de `tests/integracao` são
pulados. Variável já definida no terminal tem prioridade sobre o `.env`.

## Como usar

```bash
.venv/bin/pip install -e ".[dev]"          # inclui streamlit e mcp
.venv/bin/streamlit run app.py              # interface do analista
.venv/bin/python -m src.mcp_servidor        # servidor MCP (stdio)
.venv/bin/python scripts/calibrar.py --limite 5   # regressão contra os históricos
```

Na interface: informe sua identificação, escolha o projeto e peça a análise.
Cada ponto (D1, os cinco critérios, D3, D4 e D5) mostra a proposta, as fontes e
espera a sua decisão. O dossiê sai em `saida/` quando todos estão decididos.

Cada proposta, decisão e reabertura é gravada em `saida/decisoes/<projeto>.jsonl`,
um evento por linha, sem reescrita. "Abrir análise salva" retoma do ponto em que
o analista parou. Em um ponto já decidido, "Rever este ponto" reabre esse ponto
e os que dependem dele.

### Discordâncias e revisão cega

Alterar ou rejeitar uma proposta abre uma discordância, com o tipo e o motivo
informados pelo analista. Na tela "Discordâncias e revisão cega" (seletor na
barra lateral), um segundo analista vê a proposta da IA e as fontes, sem a
decisão do primeiro, e diz se concorda com a IA. Quem abriu a discordância não
a revisa.

Discordância confirmada pelos dois vira precedente interno e aparece no cartão
do mesmo ponto em outros projetos, como contexto. O precedente não altera
proposta, estado nem classificação e não é fundamento legal. Com o mesmo ponto
e o mesmo tipo confirmados em três projetos, a tela avisa que o padrão deve ir
ao curador normativo; nenhuma regra ou prompt muda sozinho. Os analistas
aparecem por pseudônimo em `saida/discordancias.jsonl`.

### Três modelos, um papel cada

A análise é dividida entre provedores com camada gratuita, para nenhum repetir
o trabalho do outro e cada um receber só o recorte de que precisa:

| Papel | Provedor padrão | O que faz | O que recebe |
|---|---|---|---|
| Analista | Gemini | Avalia os cinco critérios e propõe a classificação | Regras, exemplos e evidências do projeto |
| Confronto | Groq | Confronta a entrevista com os registros e classifica as atividades | Entrevista, ensaios, método, observações e atividades |
| Auditor | OpenRouter | Diz se as fontes citadas sustentam cada justificativa | Justificativas do analista e o texto das fontes citadas |

Cada papel tem uma fila de reserva com os outros provedores. Quando o titular
fica sem cota (HTTP 429) ou recusa a chamada, a mesma pergunta vai para o
seguinte, e a tela avisa o analista de quem respondeu no lugar. O modelo sem
cota sai da fila por um minuto; o recusado, por dez. Para ter reservas dentro
do mesmo provedor, liste os modelos separados por vírgula
(`GEMINI_MODEL=gemini-3.8-flash,gemini-3.6-flash`).

Analista e confronto rodam ao mesmo tempo; o auditor roda depois. Com menos de
três chaves no `.env`, os papéis são redistribuídos; com uma só, o analista faz
também o confronto e não há auditoria. Falha do confronto ou do auditor vira
aviso na tela e não interrompe a análise. O resultado da auditoria é um alerta
para o analista: não altera o estado de nenhum critério.

O que o modelo pode e não pode fazer:

1. Só recebe trechos recuperados do projeto e a base de regras.
2. Cada fonte que ele cita é conferida contra o que recebeu; fonte inexistente é descartada e mostrada ao analista.
3. Critério sem nenhuma fonte válida é rebaixado para o estado indeterminado.
4. A classificação exibida vem da regra sobre os estados confirmados pelo analista, não da sugestão do modelo.

Ferramentas do servidor MCP, todas somente de leitura: `listar_projetos`,
`resumo_do_projeto`, `buscar_evidencias`, `ler_referencia`,
`conferir_resultados`, `buscar_regras` e `parecer_historico`.

## Estrutura

```
src/
  decisoes/maquina_estados.py   # estados, transicoes, dependencias, log
  decisoes/registro.py          # log das decisoes em disco e retomada da analise
  decisoes/discordancias.py     # discordancias, revisao cega, precedentes e padroes candidatos
  schemas/discordancia.py       # discordancias, revisao cega, precedentes
  pacote/                       # carregador do pacote do desafio e pareceres historicos
  verificacao/recalculo.py      # resultados.csv conferido contra medicoes.csv
  verificacao/referencias.py    # toda fonte citada precisa existir no projeto
  verificacao/citacoes.py       # verificador lexical de citacoes
  llm/cliente.py                # interface do modelo de linguagem e cliente OpenRouter
  rag/corpus.py                 # corpus do projeto, recuperacao de contexto e base de regras
  motor/                        # regras de classificacao, analisador com LLM e fluxo D1 a D5
  ferramentas.py                # consultas de leitura usadas pelo motor, pela interface e pelo MCP
  mcp_servidor.py               # servidor MCP
app.py                          # interface Streamlit
prompts/analise_projeto.md      # prompt versionado do motor
scripts/calibrar.py             # regressao contra os projetos historicos
tests/unit/                     # testes sem rede e sem a massa do hackathon
tests/integracao/               # testes contra a massa (exigem LEI_DO_BEM_PACOTE)
docs/                           # base, ADRs
dados/normas/                   # base de regras da ferramenta
dados/fixtures/                 # projeto ficticio para os testes
```

## Regras que não podem ser quebradas

1. Nenhum ponto avança sem decisão explícita do analista.
2. Alterar ou rejeitar exige motivo com pelo menos 20 caracteres.
3. Precedentes internos são não normativos e nunca alteram a classificação.
4. O segundo analista de uma revisão cega é sempre diferente do originador.
5. Apenas dados fictícios no hackathon.
