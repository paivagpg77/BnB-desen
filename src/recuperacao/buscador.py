"""
Recuperacao de trechos para o motor de analise.

Separa as duas fontes que nunca devem se misturar sem filtro:
- normas (fonte normativa);
- projeto (fatos do caso, filtrados por projeto_id).
"""

from __future__ import annotations

from typing import Iterable, Optional

from src.documentos.modelos import TIPO_NORMA, TIPO_PROJETO, Trecho
from src.indexacao.bm25 import IndiceBM25


class Buscador:
    def __init__(self, trechos: Iterable[Trecho]):
        self._indice = IndiceBM25(trechos)

    def normas(self, consulta: str, k: int = 5) -> list[tuple[float, Trecho]]:
        return self._indice.buscar(consulta, k=k, filtro=lambda t: t.tipo == TIPO_NORMA)

    def projeto(
        self, projeto_id: str, consulta: str, k: int = 5
    ) -> list[tuple[float, Trecho]]:
        return self._indice.buscar(
            consulta,
            k=k,
            filtro=lambda t: t.tipo == TIPO_PROJETO and t.projeto_id == projeto_id,
        )

    def trecho(self, trecho_id: str) -> Optional[Trecho]:
        return self._indice.trecho(trecho_id)
