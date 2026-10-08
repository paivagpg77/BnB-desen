"""
Indice lexical BM25, sem dependencias externas.

Busca por palavras (com normalizacao de acentos). Nao entende sinonimos:
para isso entra a busca vetorial, quando houver modelo de embeddings aprovado.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Callable, Iterable, Optional

from src.documentos.modelos import Trecho
from src.texto.tokens import tokenizar


class IndiceBM25:
    def __init__(self, trechos: Iterable[Trecho], k1: float = 1.5, b: float = 0.75):
        self._trechos: dict[str, Trecho] = {t.trecho_id: t for t in trechos}
        self._tf: dict[str, Counter] = {}
        self._tamanho: dict[str, int] = {}
        for trecho_id, trecho in self._trechos.items():
            tokens = tokenizar(trecho.texto)
            self._tf[trecho_id] = Counter(tokens)
            self._tamanho[trecho_id] = len(tokens)

        total = len(self._trechos)
        self._media = (sum(self._tamanho.values()) / total) if total else 1.0
        frequencia_documento: Counter = Counter()
        for contagem in self._tf.values():
            frequencia_documento.update(contagem.keys())
        self._idf = {
            palavra: math.log(1 + (total - f + 0.5) / (f + 0.5))
            for palavra, f in frequencia_documento.items()
        }
        self._k1 = k1
        self._b = b

    def __len__(self) -> int:
        return len(self._trechos)

    def trecho(self, trecho_id: str) -> Optional[Trecho]:
        return self._trechos.get(trecho_id)

    def _pontuar(self, consulta_tokens: set[str], trecho_id: str) -> float:
        tf = self._tf[trecho_id]
        tamanho = self._tamanho[trecho_id]
        pontuacao = 0.0
        for palavra in consulta_tokens:
            f = tf.get(palavra, 0)
            if f == 0:
                continue
            normalizacao = self._k1 * (1 - self._b + self._b * tamanho / self._media)
            pontuacao += self._idf[palavra] * f * (self._k1 + 1) / (f + normalizacao)
        return pontuacao

    def buscar(
        self,
        consulta: str,
        k: int = 5,
        filtro: Optional[Callable[[Trecho], bool]] = None,
    ) -> list[tuple[float, Trecho]]:
        consulta_tokens = set(tokenizar(consulta))
        if not consulta_tokens:
            return []
        resultados: list[tuple[float, Trecho]] = []
        for trecho_id, trecho in self._trechos.items():
            if filtro is not None and not filtro(trecho):
                continue
            pontuacao = self._pontuar(consulta_tokens, trecho_id)
            if pontuacao > 0:
                resultados.append((pontuacao, trecho))
        resultados.sort(key=lambda par: (-par[0], par[1].trecho_id))
        return resultados[:k]
