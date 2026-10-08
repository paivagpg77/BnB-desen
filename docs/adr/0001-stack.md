# ADR 0001: Stack de back-end e front-end

- Status: Aceita (sujeita à validação da equipe)
- Data: 2026-10-07
- Projeto: Ferramenta de apoio à análise preliminar de elegibilidade à Lei do Bem (Hackathon STS 2026, desafio BNB)

## Contexto

A ferramenta precisa:

- extrair e indexar documentos em PDF, CSV/XLSX, TXT, MD e JSON;
- executar RAG híbrido (embeddings e BM25) com citações rastreáveis;
- expor ferramentas por meio de um servidor MCP;
- apresentar um fluxo de confirmação em cinco pontos de decisão (D1 a D5), com cartões, painel de referência e histórico;
- gerar um dossiê a partir das decisões confirmadas;
- manter dados sigilosos em ambiente controlado.

O prazo do hackathon é de três dias.

## Decisão

**Back-end**

- Python 3.11+
- FastAPI para a API HTTP
- Pydantic v2 para schemas e validação de dados
- SDK oficial `mcp` (Python) para o servidor MCP
- pypdf e pdfplumber para PDF; pandas e openpyxl para CSV e XLSX
- sentence-transformers para embeddings, executado localmente
- FAISS para busca vetorial
- rank-bm25 para busca lexical
- Dossiê em Markdown na Fase 1 (Jinja2 para os templates); PDF em fase posterior

**Front-end**

- React com JavaScript (sem TypeScript)
- Vite como ferramenta de build
- Biblioteca de componentes a definir pela equipe (sugestão: uma biblioteca com tabelas, formulários e acessibilidade prontos)
- Comunicação com o back-end pela API REST documentada via OpenAPI, gerada automaticamente pelo FastAPI

**Testes**

- pytest no back-end
- Vitest e React Testing Library no front-end

## Alternativas consideradas

| Alternativa | Motivo para não adotar |
|---|---|
| Python + Streamlit | Entrega mais rápida, mas layout limitado para o cartão de decisão e o painel de referência. Pode servir de plano B se o prazo apertar. |
| TypeScript no front-end | Melhor segurança de tipos, mas a equipe optou por JavaScript. Reavaliar na versão de produção. |
| Node.js no back-end | Ecossistema de extração de documentos e RAG menos maduro que o de Python. |

## Consequências

Positivas:
- O ecossistema Python cobre extração de documentos, RAG e MCP sem gambiarras.
- O front-end em React permite controlar o fluxo de decisão e o painel de referência com precisão.
- Os embeddings locais mantêm o conteúdo dos projetos dentro do ambiente.

Negativas e riscos:
- **Prazo:** React exige mais trabalho inicial que o Streamlit. Mitigação: usar Vite e uma biblioteca de componentes, manter a interface mínima e priorizar o fluxo D1 a D5 antes de qualquer refinamento visual.
- **JavaScript sem tipos:** erros de contrato entre front e back são mais difíceis de detectar. Mitigação: validar as respostas com o schema OpenAPI, cobrir os contratos com testes e usar JSDoc nos modelos principais.
- **Dependência de dois ambientes:** é preciso rodar back-end e front-end ao mesmo tempo. Mitigação: um script único de inicialização e um arquivo docker-compose, se houver tempo.

## Itens a validar

1. Escolha da biblioteca de componentes de interface.
2. Modelo de embeddings: confirmar que o modelo escolhido pode rodar no ambiente do banco.
3. Modelo de linguagem: confirmar o provedor e a política de dados antes de qualquer uso com dados reais.
