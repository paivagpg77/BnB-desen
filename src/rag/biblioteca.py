"""
Biblioteca de referencia do desafio, lida do pacote em tempo de execucao.

Duas fontes, nenhuma delas copiada para o repositorio:

1. Orientacoes: guia do participante, LEIA_ME, guia do desafio e dicionario.
   Sao recuperadas por busca e entram no contexto como material de regra.
2. Pareceres dos projetos historicos (PRJ01 a PRJ20): mostram como fundamentar.
   Entra um exemplo por classificacao, sempre os mesmos, e nunca os mais
   parecidos com o projeto em analise: o guia proibe classificar por
   semelhanca, e escolher exemplos parecidos empurraria o modelo para isso.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from src.documentos.modelos import TIPO_NORMA, Documento, Trecho
from src.indexacao.bm25 import IndiceBM25
from src.ingestao.chunking import dividir
from src.motor.regras import CLASSIFICACOES
from src.pacote.carregador import extrair_texto_pdf
from src.pacote.historicos import ARQUIVO_HISTORICOS, ParecerHistorico, carregar_historicos

# (arquivo relativo a raiz do pacote, identificador do documento, titulo)
DOCUMENTOS = (
    ("GUIA_DO_PARTICIPANTE.md", "guia-participante", "Guia do participante"),
    ("LEIA_ME.md", "leia-me", "LEIA_ME do pacote"),
    ("guia-do-desafio-hackathon-sts-2026.pdf", "guia-desafio", "Guia do desafio"),
    ("00_dados_apoio/dicionario.pdf", "dicionario", "Dicionário de dados e termos"),
)
TAMANHO_MAXIMO_TRECHO = 1200
# Orcamento, em caracteres, do que a busca acrescenta ao nucleo obrigatorio.
ORCAMENTO_ORIENTACOES = 4000

# Secoes do guia do participante que toda analise le: o que classificar, os
# criterios, as quatro classes e como tratar e ler as evidencias.
DOCUMENTO_NUCLEO = "guia-participante"
SECOES_NUCLEO = (
    "Objeto da decisão",
    "Critérios de análise",
    "Elegível",
    "Com ressalvas",
    "Não elegível",
    "Evidência insuficiente",
    "Tratamento das evidências",
    "Como ler os dados",
)

# Vocabulario de P&D e de evidencias, para a busca nos demais documentos.
CONSULTAS_ORIENTACAO = (
    "novidade criatividade incerteza tecnológica sistematicidade transferibilidade reprodutibilidade",
    "estado da técnica referência anterior comparador hipótese tecnológica",
    "fonte primária fonte derivada alegação autodeclaração evidência contrária proveniência",
    "lacuna elo ausente limitação interna exclusão externa",
    "pesquisa rotina desenvolvimento experimental prova de não rotina",
    "contagem de entrega desempenho base de cálculo denominador versão",
)
PREFIXO_HISTORICO = "historico:"


def _fatiar(texto: str, tamanho: int = TAMANHO_MAXIMO_TRECHO) -> list[str]:
    """Divide por linhas, sem cortar uma linha ao meio."""
    partes: list[str] = []
    atual: list[str] = []
    usado = 0
    for linha in texto.splitlines():
        if atual and usado + len(linha) + 1 > tamanho:
            partes.append("\n".join(atual).strip())
            atual, usado = [], 0
        atual.append(linha)
        usado += len(linha) + 1
    if atual:
        partes.append("\n".join(atual).strip())
    return [p for p in partes if p]


def _trechos_do_documento(caminho: Path, doc_id: str, titulo: str) -> list[Trecho]:
    if caminho.suffix.lower() == ".pdf":
        # A extracao de PDF deixa varios espacos entre palavras.
        texto = "\n".join(" ".join(l.split()) for l in extrair_texto_pdf(caminho).splitlines())
        secoes = [(titulo, texto)]
    else:
        documento = Documento(
            doc_id=doc_id,
            tipo=TIPO_NORMA,
            titulo=titulo,
            texto=caminho.read_text(encoding="utf-8-sig"),
            origem=caminho.name,
        )
        secoes = [(t.secao, t.texto) for t in dividir(documento)]

    trechos: list[Trecho] = []
    for secao, texto in secoes:
        for parte in _fatiar(texto):
            trechos.append(
                Trecho(
                    trecho_id=f"{doc_id}#{len(trechos) + 1:03d}",
                    doc_id=doc_id,
                    tipo=TIPO_NORMA,
                    projeto_id=None,
                    secao=f"{titulo} · {secao}" if secao not in (titulo, "inicio") else titulo,
                    texto=parte,
                )
            )
    return trechos


@lru_cache(maxsize=4)
def _orientacoes(raiz: str) -> tuple[Trecho, ...]:
    trechos: list[Trecho] = []
    for arquivo, doc_id, titulo in DOCUMENTOS:
        caminho = Path(raiz) / arquivo
        if caminho.is_file():
            trechos += _trechos_do_documento(caminho, doc_id, titulo)
    return tuple(trechos)


def carregar_orientacoes(raiz: str | Path) -> list[Trecho]:
    """Todos os trechos dos documentos de orientacao presentes no pacote."""
    return list(_orientacoes(str(raiz)))


def _e_nucleo(trecho: Trecho) -> bool:
    return trecho.doc_id == DOCUMENTO_NUCLEO and any(
        trecho.secao.endswith(f"· {secao}") for secao in SECOES_NUCLEO
    )


def buscar_orientacoes(
    raiz: str | Path,
    consultas: Iterable[str] = CONSULTAS_ORIENTACAO,
    orcamento: int = ORCAMENTO_ORIENTACOES,
    k: int = 3,
    com_nucleo: bool = True,
) -> list[Trecho]:
    """
    Nucleo do guia do participante e, em seguida, os trechos dos demais
    documentos mais relevantes para as consultas, dentro do orcamento.

    O motor pede sem o nucleo: a base de regras da ferramenta ja traz esse
    conteudo, e manda-lo duas vezes so gasta tokens.
    """
    trechos = carregar_orientacoes(raiz)
    if not trechos:
        return []
    nucleo = [t for t in trechos if _e_nucleo(t)]
    escolhidos = list(nucleo) if com_nucleo else []
    ja = {t.trecho_id for t in nucleo}

    indice = IndiceBM25(trechos)
    pontuacoes: dict[str, float] = {}
    for consulta in consultas:
        for pontuacao, trecho in indice.buscar(consulta, k=k):
            if trecho.trecho_id not in ja:
                pontuacoes[trecho.trecho_id] = max(
                    pontuacao, pontuacoes.get(trecho.trecho_id, 0.0)
                )
    usado = 0
    for trecho_id, _ in sorted(pontuacoes.items(), key=lambda par: (-par[1], par[0])):
        trecho = indice.trecho(trecho_id)
        if usado + len(trecho.texto) > orcamento:
            continue
        escolhidos.append(trecho)
        usado += len(trecho.texto)
    return escolhidos


def texto_do_parecer(parecer: ParecerHistorico) -> str:
    linhas = [
        f"Projeto histórico {parecer.projeto_id} — {parecer.titulo}",
        f"Classificação de referência: {parecer.classificacao}",
        f"Justificativa: {parecer.justificativa}",
        f"Limite da conclusão: {parecer.limite}",
    ]
    if parecer.divergencia_depoimento:
        linhas.append(f"Divergência entre depoimento e registro: {parecer.divergencia_depoimento}")
    for criterio in parecer.criterios:
        linhas.append(
            f"- {criterio.criterio}: {criterio.estado}. {criterio.justificativa} "
            f"(fonte no projeto {parecer.projeto_id}: {criterio.fonte})"
        )
    return "\n".join(linhas)


@lru_cache(maxsize=4)
def _pareceres(raiz: str) -> tuple[ParecerHistorico, ...]:
    if not (Path(raiz) / ARQUIVO_HISTORICOS).is_file():
        return ()
    return tuple(carregar_historicos(raiz).values())


def trechos_dos_historicos(raiz: str | Path) -> list[Trecho]:
    """Um trecho por parecer historico, com identificador 'historico:PRJxx'."""
    return [
        Trecho(
            trecho_id=f"{PREFIXO_HISTORICO}{p.projeto_id}",
            doc_id="historicos",
            tipo=TIPO_NORMA,
            projeto_id=None,
            secao=f"{p.projeto_id} · {p.classificacao}",
            texto=texto_do_parecer(p),
        )
        for p in _pareceres(str(raiz))
    ]


def exemplos_de_referencia(
    raiz: str | Path, excluir: Optional[str] = None
) -> list[Trecho]:
    """
    Um parecer historico por classificacao, na ordem dos identificadores.
    'excluir' tira o proprio projeto dos exemplos, para a calibracao contra os
    historicos nao receber a resposta dentro do prompt.
    """
    por_id = {t.trecho_id: t for t in trechos_dos_historicos(raiz)}
    exemplos: list[Trecho] = []
    for classificacao in CLASSIFICACOES:
        for parecer in sorted(_pareceres(str(raiz)), key=lambda p: p.projeto_id):
            if parecer.classificacao == classificacao and parecer.projeto_id != excluir:
                exemplos.append(por_id[f"{PREFIXO_HISTORICO}{parecer.projeto_id}"])
                break
    return exemplos


def buscar_pareceres(raiz: str | Path, consulta: str, k: int = 3) -> list[tuple[float, Trecho]]:
    """Busca lexical nos pareceres historicos (consulta de referencia, via MCP)."""
    trechos = trechos_dos_historicos(raiz)
    return IndiceBM25(trechos).buscar(consulta, k=k) if trechos else []
