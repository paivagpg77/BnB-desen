"""
Busca semantica por embeddings e fusao com a busca lexical.

O BM25 so encontra o trecho que usa as mesmas palavras da consulta. O indice
vetorial encontra tambem o que diz a mesma coisa com outras palavras. Os dois
resultados sao fundidos pela posicao (reciprocal rank fusion), de modo que a
escala das pontuacoes de cada busca nao importa.

O modelo de embeddings roda localmente (sentence-transformers): o conteudo dos
projetos nao sai do ambiente. Sem EMBEDDINGS_MODELO no .env a busca semantica
fica desligada e vale so a lexical.
"""

from __future__ import annotations

import math
import os
from typing import Callable, Iterable, Optional, Protocol

from src.config import carregar_env
from src.documentos.modelos import Trecho

VARIAVEL_MODELO = "EMBEDDINGS_MODELO"
# Multilingue (inclui portugues) e pequeno o bastante para rodar em CPU.
MODELO_SUGERIDO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CONSTANTE_RRF = 60

Resultado = tuple[float, Trecho]


class ErroDeEmbeddings(RuntimeError):
    pass


class Embeddings(Protocol):
    nome: str

    def codificar(self, textos: list[str]) -> list[list[float]]: ...


class EmbeddingsLocais:
    """Modelo do sentence-transformers, carregado na primeira codificacao."""

    def __init__(self, nome: str):
        self.nome = nome
        self._modelo = None

    def codificar(self, textos: list[str]) -> list[list[float]]:
        if self._modelo is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as erro:
                raise ErroDeEmbeddings(
                    f"{VARIAVEL_MODELO} está definido, mas o sentence-transformers não "
                    'está instalado. Instale com: pip install -e ".[semantica]"'
                ) from erro
            self._modelo = SentenceTransformer(self.nome)
        return [list(map(float, vetor)) for vetor in self._modelo.encode(textos)]


def embeddings_padrao() -> Optional[Embeddings]:
    """Modelo configurado no .env, ou None quando a busca semantica esta desligada."""
    carregar_env()
    nome = os.environ.get(VARIAVEL_MODELO, "").strip()
    return EmbeddingsLocais(nome) if nome else None


def _normalizar(vetor: list[float]) -> list[float]:
    norma = math.sqrt(sum(v * v for v in vetor))
    return [v / norma for v in vetor] if norma else vetor


class IndiceVetorial:
    """Similaridade de cosseno sobre os trechos, com a mesma busca do IndiceBM25."""

    def __init__(self, trechos: Iterable[Trecho], embeddings: Embeddings):
        self._trechos: dict[str, Trecho] = {t.trecho_id: t for t in trechos}
        self._embeddings = embeddings
        vetores = embeddings.codificar([t.texto for t in self._trechos.values()])
        self._vetores = dict(zip(self._trechos, map(_normalizar, vetores)))

    def __len__(self) -> int:
        return len(self._trechos)

    def buscar(
        self,
        consulta: str,
        k: int = 5,
        filtro: Optional[Callable[[Trecho], bool]] = None,
    ) -> list[Resultado]:
        if not consulta.strip() or not self._trechos:
            return []
        alvo = _normalizar(self._embeddings.codificar([consulta])[0])
        resultados: list[Resultado] = []
        for trecho_id, trecho in self._trechos.items():
            if filtro is not None and not filtro(trecho):
                continue
            semelhanca = sum(a * b for a, b in zip(alvo, self._vetores[trecho_id]))
            if semelhanca > 0:
                resultados.append((semelhanca, trecho))
        resultados.sort(key=lambda par: (-par[0], par[1].trecho_id))
        return resultados[:k]


def fundir(listas: Iterable[list[Resultado]], k: int = 5) -> list[Resultado]:
    """
    Reciprocal rank fusion: cada lista contribui com 1 / (60 + posicao). Trecho
    bem colocado nas duas buscas fica a frente do que aparece em uma so.
    """
    pontuacao: dict[str, float] = {}
    trechos: dict[str, Trecho] = {}
    for lista in listas:
        for posicao, (_, trecho) in enumerate(lista, start=1):
            trechos[trecho.trecho_id] = trecho
            pontuacao[trecho.trecho_id] = (
                pontuacao.get(trecho.trecho_id, 0.0) + 1.0 / (CONSTANTE_RRF + posicao)
            )
    ordenados = sorted(pontuacao.items(), key=lambda par: (-par[1], par[0]))
    return [(pontos, trechos[trecho_id]) for trecho_id, pontos in ordenados[:k]]
