"""
Pareceres de referencia dos projetos historicos (PRJ01 a PRJ20).

Servem para calibrar o nivel de fundamentacao e para a regressao do motor.
Nao sao usados para classificar casos novos por semelhanca.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.pacote.carregador import ler_csv_pacote

ARQUIVO_HISTORICOS = "historicos_classificados.csv"


@dataclass(frozen=True)
class CriterioHistorico:
    criterio: str
    estado: str
    justificativa: str
    fonte: str


@dataclass(frozen=True)
class ParecerHistorico:
    projeto_id: str
    titulo: str
    classificacao: str
    justificativa: str
    limite: str
    fontes_decisivas: tuple[str, ...]
    divergencia_depoimento: str
    criterios: tuple[CriterioHistorico, ...]


def carregar_historicos(raiz: str | Path) -> dict[str, ParecerHistorico]:
    pareceres: dict[str, ParecerHistorico] = {}
    for linha in ler_csv_pacote(Path(raiz) / ARQUIVO_HISTORICOS):
        criterios = tuple(
            CriterioHistorico(
                criterio=linha[f"criterio_{i}"],
                estado=linha[f"estado_{i}"],
                justificativa=linha[f"justificativa_{i}"],
                fonte=linha[f"fonte_{i}"],
            )
            for i in range(1, 6)
        )
        fontes = tuple(
            parte.strip() for parte in linha["fontes_decisivas"].split("|") if parte.strip()
        )
        pareceres[linha["projeto_id"]] = ParecerHistorico(
            projeto_id=linha["projeto_id"],
            titulo=linha["titulo"],
            classificacao=linha["classificacao"],
            justificativa=linha["justificativa"],
            limite=linha["limite"],
            fontes_decisivas=fontes,
            divergencia_depoimento=linha["divergencia_depoimento"],
            criterios=criterios,
        )
    return pareceres
