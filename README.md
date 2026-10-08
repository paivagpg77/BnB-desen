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
- [ ] Busca semântica (embeddings), aguardando escolha de modelo aprovado
- [ ] Extração de PDF, aguardando biblioteca e PDFs reais
- [ ] Motor de avaliação D1 a D5 e prompts dos critérios, aguardando textos normativos
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

## Estrutura

```
src/
  decisoes/maquina_estados.py   # estados, transicoes, dependencias, log
  schemas/discordancia.py       # discordancias, revisao cega, precedentes
tests/unit/                     # testes da maquina de estados e das discordancias
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
