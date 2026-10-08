# Handoff: Lei do Bem - apoio à análise preliminar de elegibilidade

Documento para quem entra no desenvolvimento. Resume o que foi decidido, o que existe, o que falta e o que não deve ser feito.

Data do handoff: 2026-10-08
Contexto: Hackathon STS 2026, desafio do Banco do Nordeste (BNB).

## 1. Ideia em uma frase

Ferramenta que organiza a análise de elegibilidade à Lei do Bem em cinco pontos de decisão (D1 a D5). A IA propõe uma conclusão com o porquê e as referências. O analista confirma, altera ou rejeita. Nada avança sem a confirmação dele.

## 2. Regras que não podem ser quebradas

1. A IA propõe; o analista decide. Nenhum ponto avança sem decisão explícita.
2. A IA não inventa. Toda afirmação cita um `trecho_id` recuperado de uma fonte. Sem trecho, a saída é "não consta na documentação".
3. Ausência de evidência não é não elegibilidade. O status padrão é "Evidência insuficiente".
4. Classificações possíveis (usar exatamente estes quatro): Elegível, Com ressalvas, Não elegível, Evidência insuficiente.
5. Alterar ou rejeitar exige motivo com pelo menos 20 caracteres.
6. Precedentes internos (discordâncias entre analistas) são não normativos. Nunca alteram proposta, status ou classificação, e nunca são citados como fundamento legal.
7. A revisão cega exige um segundo analista diferente do originador.
8. Nenhuma regra ou prompt muda automaticamente. Padrões recorrentes vão para o curador normativo.
9. Apenas dados fictícios no hackathon. Dados reais e sigilosos não vão para serviços de IA públicos.
10. Todo evento (proposta, decisão, reabertura, discordância) fica em log somente de anexação.

## 3. Onde estão os arquivos

Projeto: `/home/claude/lei-do-bem-analise` (ambiente da sessão de cloud). Ainda não há repositório git. Antes de qualquer entrega, decidir o repositório e fazer o primeiro commit.

```
lei-do-bem-analise/
├── README.md
├── pyproject.toml
├── .gitignore
├── docs/
│   ├── base_projeto_v0.2.txt        # base de negócio (versão atual)
│   ├── adr/0001-stack.md            # decisão: Python + React (JavaScript)
│   └── HANDOFF.md                   # este arquivo
├── src/
│   ├── decisoes/maquina_estados.py  # D1..D5, estados, transições, reabertura, log
│   └── schemas/discordancia.py      # discordância, revisão cega, precedente, padrão candidato
├── tests/unit/
│   ├── test_maquina_estados.py      # 14 testes
│   └── test_discordancia.py         # 11 testes
├── prompts/                         # vazio (prompts versionados, ainda não escritos)
└── dados/                           # vazio (normas, projetos fictícios, calibração)
```

Cópias de trabalho (também na sessão): `scratchpad/base_projeto_lei_do_bem_v0.1.txt`, `v0.2`, `scratchpad/fase1/discordancia.py`, `scratchpad/0001-stack.md`.

### Como rodar os testes

```bash
cd lei-do-bem-analise
python3 -m venv .venv
.venv/bin/pip install pydantic pytest
.venv/bin/pytest
```

Estado no momento do handoff: 25 testes passando.

## 4. O que já foi feito

**Documentação**
- Base do projeto v0.1 e v0.2 (v0.2 inclui o módulo de discordâncias e precedentes).
- ADR 0001: stack escolhida. Back-end em Python 3.11+ (FastAPI, Pydantic v2, SDK MCP em Python, pypdf/pdfplumber, pandas, sentence-transformers local, FAISS, rank-bm25). Front-end em React com JavaScript, Vite.
- Lista de perguntas para os analistas (40 perguntas em 8 temas), para validar requisitos.
- Estrutura de pastas e prompt de briefing para o desenvolvimento.
- Fluxo de usuário e layout do cartão de decisão.

**Código**
- `maquina_estados.py`: classe `PontoDecisao` com ações `propor`, `aceitar`, `alterar`, `rejeitar`, `reabrir`. Funções `pode_apresentar`, `proximo_ponto_pendente`, `decisao_final_pronta` e `reabrir_dependentes`. Dependências: D3 reabre D2; D2 reabre D4; D4 reabre D5.
- `discordancia.py`: enums de tipo e status, `RegistroDiscordancia`, `RevisaoCega` (com validação de analista diferente), `PrecedenteInterno` (natureza fixa "interno_nao_normativo") e `e_padrao_candidato` (limiar de 3 projetos distintos com convergência contra a IA).

## 5. O que não existe ainda

- Ingestão de documentos (PDF, CSV/XLSX, TXT, MD, JSON).
- Chunking por unidade lógica e índice híbrido (embeddings + BM25).
- Recuperação com citações e verificador de citações.
- Motor de avaliação D1 a D5 e os prompts dos critérios.
- Servidor MCP e API FastAPI.
- Interface React.
- Dossiê em Markdown.
- Calibração contra PRJ01 a PRJ20.
- Massa de dados fictícios (PRJ01 a PRJ40): não recebida.
- Textos normativos (Lei 11.196/2005, Decreto 5.798/2006, instruções normativas, guia): não recebidos em texto.

## 6. Bloqueios e decisões pendentes

| Item | Quem decide | Impacto |
|---|---|---|
| Textos normativos oficiais e versão de referência | BNB | Sem eles não há citações nem prompts de critério |
| Massa de dados (PRJ01 a PRJ40) | BNB / organização | Sem ela não há teste de ingestão nem calibração |
| Provedor de modelo de linguagem e de embeddings | Equipe + política do banco | Define se os dados podem sair do ambiente |
| Limiar de precedente (sugerido: 3 projetos) | BNB | Define quando um padrão vai ao curador |
| Curador normativo | BNB | Quem recebe os padrões recorrentes |
| Repositório e processo de versionamento | Equipe | Ainda não há git |
| Front-end em JavaScript sem tipos | Equipe | Risco de erro de contrato; mitigar com OpenAPI e testes |

## 7. Cuidados para quem entra agora

- **Não cite artigos de lei de memória.** Os textos normativos precisam vir dos arquivos oficiais. A ferramenta deve ser capaz de apontar a versão e a seção de cada citação.
- **Revise o guia do desafio antes de escrever os prompts dos critérios.** Na leitura desta sessão, o PDF do guia não retornou texto legível. Os detalhes sobre o guia que aparecem nas mensagens anteriores ainda não foram confirmados.
- **Os cinco critérios** usam o nome do material do desafio: novidade, criatividade, incerteza tecnológica, sistematicidade e transferibilidade/reprodutibilidade.
- **"Empresas", não "startups".** A Lei do Bem vale para empresas no Lucro Real em geral. Esse ajuste está pendente na base.
- **"A IA não escolhe" significa:** a IA propõe com justificativa, e o analista confirma. Não é uma IA sem papel na análise.
- **Aprendizado por discordância (Fase 1)** usa precedentes recuperados via RAG, não treinamento de modelo. O ML (Fase 2) fica para depois, com volume de dados suficiente.
- **Três dias de hackathon.** Priorize o caso de ponta a ponta com um projeto fictício (PRJ21, por exemplo), a confirmação em cada ponto e o dossiê.

## 8. Próximos passos sugeridos (ordem)

1. Receber os textos normativos e a massa de dados. Sem eles, parar a parte de análise e seguir só com o que não depende deles.
2. Criar os parsers de ingestão com arquivos fictícios próprios, testados.
3. Implementar o verificador de citações (não depende de modelo e protege contra invenção).
4. Implementar chunking e índice híbrido, com metadados obrigatórios.
5. Implementar o servidor MCP e a API, sem lógica de análise.
6. Escrever os prompts dos critérios em `prompts/`, a partir do texto normativo oficial.
7. Implementar o motor D1 a D5 com o verificador em cada saída.
8. Implementar a interface React seguindo o layout do cartão de decisão.
9. Gerar o dossiê em Markdown e rodar a calibração PRJ01 a PRJ20.

## 9. Glossário

- **D1 a D5:** pontos de decisão. D1 entendimento; D2 avaliação de cada critério; D3 segregação de atividades; D4 evidências contrárias e lacunas; D5 classificação final.
- **Dossiê:** documento final com regra, evidência, versão da norma, autor, data e o que não foi verificado.
- **Trecho_id:** identificador de um trecho recuperado de uma fonte. Toda citação usa um.
- **Precedente interno:** registro de discordância confirmada entre analistas. Não normativo.
- **Revisão cega:** o segundo analista decide sem ver a decisão do primeiro.
- **Padrão candidato:** mesmo critério e tipo de discordância em pelo menos 3 projetos distintos, com convergência contra a IA.
