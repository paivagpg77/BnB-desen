"""
Conferencia de resultados.csv contra medicoes.csv, sem modelo de linguagem.

medicoes.csv e o registro primario; resultados.csv e derivado dele. Refazer a
conta mostra se a consolidacao confere, mas nao e uma confirmacao independente
e nao diz nada sobre elegibilidade.

Regras do LEIA_ME do pacote:
- contagem: soma de numeradores e de denominadores do mesmo ensaio;
- media, mediana, diferenca_maior_menor: sobre os valores do ensaio;
- percentil_95: posto teto(0,95 x soma dos pesos), sem interpolar;
- valor_observado e indicador_precalculado: so a transcricao e conferida;
- taxa_percentual: 100 x valor / base, apenas em contagem de desempenho.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.pacote.modelos import Medicao, ProjetoCarregado, Resultado

TOLERANCIA = 1e-4
TOLERANCIA_TAXA = 1e-3


class Situacao(str, Enum):
    CONFERE = "confere"
    # Valor unico ou indicador ja calculado: confere a copia, nao a conta original.
    TRANSCRICAO_CONFERE = "transcricao_confere"
    DIVERGE = "diverge"
    SEM_MEDICOES = "sem_medicoes"
    NAO_RECALCULAVEL = "nao_recalculavel"


@dataclass(frozen=True)
class ConferenciaResultado:
    ensaio_id: str
    versao: str
    operacao: str
    natureza: str
    situacao: Situacao
    valor_registrado: Optional[float]
    valor_recalculado: Optional[float]
    base_registrada: Optional[float]
    base_recalculada: Optional[float]
    detalhe: str = ""
    metrica: str = ""
    unidade: str = ""

    @property
    def ok(self) -> bool:
        return self.situacao in (Situacao.CONFERE, Situacao.TRANSCRICAO_CONFERE)


def _igual(a: Optional[float], b: Optional[float], tolerancia: float = TOLERANCIA) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tolerancia


def _percentil_95(medicoes: list[Medicao]) -> tuple[Optional[float], float]:
    pares = sorted((m.valor, m.peso or 0.0) for m in medicoes if m.valor is not None)
    total = sum(peso for _, peso in pares)
    if total <= 0:
        return None, total
    posto = math.ceil(0.95 * total)
    acumulado = 0.0
    for valor, peso in pares:
        acumulado += peso
        if acumulado >= posto:
            return valor, total
    return None, total


def _recalcular(
    resultado: Resultado, medicoes: list[Medicao]
) -> tuple[Optional[float], Optional[float]]:
    """Devolve (valor, base) recalculados, ou (None, None) se nao houver regra."""
    operacao = resultado.operacao
    if operacao == "contagem":
        return (
            sum(m.numerador or 0.0 for m in medicoes),
            sum(m.denominador or 0.0 for m in medicoes),
        )
    if operacao == "percentil_95":
        return _percentil_95(medicoes)

    valores = [m.valor for m in medicoes if m.valor is not None]
    if not valores:
        return None, None
    if operacao == "media":
        return sum(valores) / len(valores), float(len(valores))
    if operacao == "mediana":
        return statistics.median(valores), float(len(valores))
    if operacao == "diferenca_maior_menor":
        return max(valores) - min(valores), float(len(valores))
    if operacao in ("valor_observado", "indicador_precalculado"):
        return (valores[0], 1.0) if len(valores) == 1 else (None, float(len(valores)))
    return None, None


def conferir_resultado(
    resultado: Resultado, medicoes: list[Medicao]
) -> ConferenciaResultado:
    do_ensaio = [
        m for m in medicoes
        if m.ensaio_id == resultado.ensaio_id and m.versao == resultado.versao
    ]

    def montar(situacao, valor=None, base=None, detalhe="") -> ConferenciaResultado:
        return ConferenciaResultado(
            ensaio_id=resultado.ensaio_id,
            versao=resultado.versao,
            operacao=resultado.operacao,
            natureza=resultado.natureza,
            situacao=situacao,
            valor_registrado=resultado.valor,
            valor_recalculado=valor,
            base_registrada=resultado.base_de_calculo,
            base_recalculada=base,
            detalhe=detalhe,
            metrica=resultado.metrica,
            unidade=resultado.unidade,
        )

    if not do_ensaio:
        return montar(
            Situacao.SEM_MEDICOES,
            detalhe="Nenhuma linha de medicoes.csv para este ensaio e versao.",
        )

    valor, base = _recalcular(resultado, do_ensaio)
    if valor is None:
        return montar(
            Situacao.NAO_RECALCULAVEL,
            base=base,
            detalhe=f"Operacao '{resultado.operacao}' sem dados suficientes para recalculo.",
        )

    problemas: list[str] = []
    if not _igual(valor, resultado.valor):
        problemas.append(f"valor registrado {resultado.valor}, recalculado {valor}")
    if not _igual(base, resultado.base_de_calculo):
        problemas.append(
            f"base registrada {resultado.base_de_calculo}, recalculada {base}"
        )

    contagem_de_desempenho = (
        resultado.operacao == "contagem" and resultado.natureza == "desempenho"
    )
    if contagem_de_desempenho and base:
        taxa = 100.0 * valor / base
        if not _igual(taxa, resultado.taxa_percentual, TOLERANCIA_TAXA):
            problemas.append(
                f"taxa registrada {resultado.taxa_percentual}, recalculada {round(taxa, 6)}"
            )
    elif resultado.taxa_percentual is not None:
        problemas.append("taxa_percentual preenchida fora de contagem de desempenho")

    if problemas:
        return montar(Situacao.DIVERGE, valor, base, "; ".join(problemas))
    if resultado.operacao in ("valor_observado", "indicador_precalculado"):
        return montar(
            Situacao.TRANSCRICAO_CONFERE,
            valor,
            base,
            "Transcricao conferida; o calculo original nao e refeito.",
        )
    return montar(Situacao.CONFERE, valor, base)


def conferir_projeto(projeto: ProjetoCarregado) -> list[ConferenciaResultado]:
    return [conferir_resultado(r, projeto.medicoes) for r in projeto.resultados]


def so_contagem_de_entrega(projeto: ProjetoCarregado) -> bool:
    """
    Sinal para o analista, nao regra de classificacao: todos os resultados sao
    contagem de material entregue, que nao mede desempenho do mecanismo.
    """
    return bool(projeto.resultados) and all(
        r.natureza == "entrega" for r in projeto.resultados
    )
