# ADR 0002: Interface em Streamlit no lugar de React

- Status: Aceita
- Data: 2026-10-09
- Substitui, em parte: ADR 0001 (seção de front-end)

## Contexto

A ADR 0001 previa front-end em React com JavaScript e uma API FastAPI entre a
interface e o motor. Ela mesma registrava o Streamlit como plano B, caso o
prazo de três dias apertasse.

A interface entregue em 2026-10-08 (`app.py`) foi feita em Streamlit e chama o
motor diretamente, sem API HTTP. O cartão de decisão, o painel de fontes, o
fluxo D1 a D5, o dossiê e a revisão cega já funcionam nela.

## Decisão

- A interface do analista é o `app.py`, em Streamlit.
- Não há API FastAPI nem front-end React nesta fase. O extra `api` do
  `pyproject.toml` fica sem uso até a decisão ser revista.
- As regras ficam fora da tela: `src/motor`, `src/decisoes` e
  `src/apresentacao.py` não dependem do Streamlit e são testados sem ele.
- Outros clientes acessam as evidências pelo servidor MCP (`src/mcp_servidor.py`).

## Consequências

Positivas:
- Um só processo para rodar e um só ambiente para instalar.
- Sem contrato entre front e back para manter; o risco de JavaScript sem tipos,
  apontado na ADR 0001, deixa de existir.
- A tela é testada de ponta a ponta com `streamlit.testing` (`tests/unit/test_app.py`).

Negativas e riscos:
- O estado da sessão vive no processo do Streamlit. Mitigação: as decisões e as
  discordâncias são gravadas em disco a cada evento e retomadas de lá.
- Não há autenticação: o analista digita a própria identificação. Em produção,
  a identidade precisa vir de um login.
- Dois analistas no mesmo projeto ao mesmo tempo gravam no mesmo log sem
  controle de concorrência.
- Layout menos flexível que o de React para o cartão de decisão.

## Quando rever

Se a ferramenta for para produção com vários analistas simultâneos, a API e um
front-end próprio voltam a ser necessários, junto com login e um banco de dados
no lugar dos arquivos JSONL.
