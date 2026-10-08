# Lei do Bem - Apoio à análise preliminar de elegibilidade

Ferramenta de apoio ao analista de P&D do Banco do Nordeste (BNB), desenvolvida no
Hackathon STS 2026. **A IA propõe; o analista decide.**

Base de referência: `docs/base_projeto_v0.2.txt`
Decisão de stack: `docs/adr/0001-stack.md`

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
- [ ] Motor de avaliação D1 a D5 e prompts dos critérios
- [ ] Busca semântica (embeddings): sem prioridade, cada projeto cabe inteiro no contexto do modelo
- [ ] Servidor MCP e API FastAPI
- [ ] Interface React
- [ ] Regressão contra a calibração PRJ01 a PRJ20, aguardando massa de dados

Os dados em `dados/fixtures/` são fictícios e servem só para teste. Não são legislação nem projetos reais.

## Rodar os testes

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

## Massa do hackathon e modelo de linguagem

A configuração local fica no arquivo `.env`, na raiz do projeto, que nunca vai
para o git. Copie o modelo e preencha:

```bash
cp .env.example .env
```

| Variável | Para que serve |
|---|---|
| `OPENROUTER_API_KEY` | Chave do OpenRouter, usada pelo motor de análise |
| `OPENROUTER_MODEL` | Modelo usado; em branco, vale o gratuito padrão |
| `LEI_DO_BEM_PACOTE` | Pasta onde o pacote do hackathon foi extraído (a que contém `01_projetos`) |

A massa é confidencial e **não entra no repositório**: extraia o pacote em uma
pasta fora dele. Sem `LEI_DO_BEM_PACOTE`, os testes de `tests/integracao` são
pulados. Variável já definida no terminal tem prioridade sobre o `.env`.

## Estrutura

```
src/
  decisoes/maquina_estados.py   # estados, transicoes, dependencias, log
  schemas/discordancia.py       # discordancias, revisao cega, precedentes
  pacote/                       # carregador do pacote do desafio e pareceres historicos
  verificacao/recalculo.py      # resultados.csv conferido contra medicoes.csv
  verificacao/referencias.py    # toda fonte citada precisa existir no projeto
  verificacao/citacoes.py       # verificador lexical de citacoes
  llm/cliente.py                # interface do modelo de linguagem e cliente OpenRouter
tests/unit/                     # testes sem rede e sem a massa do hackathon
tests/integracao/               # testes contra a massa (exigem LEI_DO_BEM_PACOTE)
docs/                           # base, ADRs
prompts/                        # prompts versionados (ainda vazio)
dados/                          # normas, projetos ficticios, calibracao (ainda vazio)
```

## Regras que não podem ser quebradas

1. Nenhum ponto avança sem decisão explícita do analista.
2. Alterar ou rejeitar exige motivo com pelo menos 20 caracteres.
3. Precedentes internos são não normativos e nunca alteram a classificação.
4. O segundo analista de uma revisão cega é sempre diferente do originador.
5. Apenas dados fictícios no hackathon.
