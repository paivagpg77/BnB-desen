"""
Resolucao de referencias no formato do pacote.

Toda fonte citada em uma proposta precisa apontar para algo que existe no
projeto: um identificador (EV, ATV, S, M, OBS, IN, CR), um arquivo entregue ou
uma ancora "arquivo#identificador", em que o identificador e uma secao do
arquivo ou um ensaio. Referencia que nao resolve bloqueia a proposta.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from src.pacote.modelos import ProjetoCarregado


class TipoReferencia(str, Enum):
    EVIDENCIA = "evidencia"
    ATIVIDADE = "atividade"
    ENSAIO = "ensaio"
    MEDICAO = "medicao"
    OBSERVACAO = "observacao"
    ENTRADA = "entrada"
    CRONOLOGIA = "cronologia"
    ARQUIVO = "arquivo"
    SECAO = "secao"
    DESCONHECIDA = "desconhecida"


@dataclass(frozen=True)
class ReferenciaResolvida:
    referencia: str
    tipo: TipoReferencia
    existe: bool
    detalhe: str = ""


def _indice(projeto: ProjetoCarregado) -> dict[str, TipoReferencia]:
    indice: dict[str, TipoReferencia] = {}
    indice.update({e.id_evidencia: TipoReferencia.EVIDENCIA for e in projeto.evidencias})
    indice.update({a.id_atividade: TipoReferencia.ATIVIDADE for a in projeto.atividades})
    indice.update({e: TipoReferencia.ENSAIO for e in projeto.ensaios()})
    indice.update({m.registro_id: TipoReferencia.MEDICAO for m in projeto.medicoes})
    indice.update({o.observacao_id: TipoReferencia.OBSERVACAO for o in projeto.observacoes})
    indice.update({e.entrada_id: TipoReferencia.ENTRADA for e in projeto.entradas})
    indice.update({c.evento_id: TipoReferencia.CRONOLOGIA for c in projeto.cronologia})
    return indice


def resolver_referencia(projeto: ProjetoCarregado, referencia: str) -> ReferenciaResolvida:
    ref = referencia.strip()
    if not ref:
        return ReferenciaResolvida(referencia, TipoReferencia.DESCONHECIDA, False, "Referencia vazia.")

    indice = _indice(projeto)
    if ref in indice:
        if indice[ref] == TipoReferencia.EVIDENCIA:
            evidencia = next(e for e in projeto.evidencias if e.id_evidencia == ref)
            if not evidencia.presente or evidencia.arquivo in projeto.ausentes:
                return ReferenciaResolvida(
                    ref, TipoReferencia.EVIDENCIA, False,
                    f"{evidencia.arquivo} consta no inventario, mas nao pode ser lido.",
                )
        return ReferenciaResolvida(ref, indice[ref], True)

    arquivo, separador, ancora = ref.partition("#")
    legiveis = projeto.arquivos - set(projeto.ausentes)
    if arquivo not in legiveis:
        return ReferenciaResolvida(
            ref, TipoReferencia.DESCONHECIDA, False,
            "Nao e identificador nem arquivo entregue deste projeto.",
        )
    if not separador:
        return ReferenciaResolvida(ref, TipoReferencia.ARQUIVO, True)

    if projeto.secao(ref) is not None:
        return ReferenciaResolvida(ref, TipoReferencia.SECAO, True)
    # "evidencias/medicoes.csv#PRJ21-S01": a ancora seleciona as linhas do ensaio.
    if ancora in projeto.ensaios():
        return ReferenciaResolvida(ref, TipoReferencia.ENSAIO, True)
    return ReferenciaResolvida(
        ref, TipoReferencia.SECAO, False,
        f"O arquivo existe, mas a ancora '{ancora}' nao foi encontrada nele.",
    )


def resolver_todas(
    projeto: ProjetoCarregado, referencias: Iterable[str]
) -> list[ReferenciaResolvida]:
    return [resolver_referencia(projeto, r) for r in referencias]
