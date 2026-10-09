"""
Geracao do dossie em Markdown a partir das decisoes confirmadas.

O dossie so e gerado quando todos os pontos estao decididos. Cada referencia
da justificativa e conferida contra a base: se o trecho nao existir, o dossie
mostra o problema em vez de esconde-lo.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from src.decisoes.maquina_estados import (
    ORDEM_PONTOS,
    PontoDecisao,
    decisao_final_pronta,
)
from src.documentos.modelos import Trecho
from src.motor.linguagem import frase_da_decisao


class DossieIncompleto(ValueError):
    pass


def _ultimo_evento_decisao(ponto: PontoDecisao) -> Optional[dict]:
    decisoes = [e for e in ponto.eventos if e["evento"] == "decisao_analista"]
    return decisoes[-1] if decisoes else None


def _data(ts: Optional[str]) -> str:
    try:
        return datetime.fromisoformat(ts).strftime("%d/%m/%Y %H:%M UTC")
    except (TypeError, ValueError):
        return ts or ""


def _ordenar(pontos: Iterable[PontoDecisao]) -> list[PontoDecisao]:
    return sorted(pontos, key=lambda p: (ORDEM_PONTOS.index(p.ponto), p.criterio or ""))


def _secao_referencias(
    porque: list[dict], trechos: dict[str, Trecho]
) -> list[str]:
    linhas = []
    for item in porque:
        trecho_id = item.get("trecho_id", "")
        afirmacao = item.get("afirmacao", "")
        trecho = trechos.get(trecho_id)
        linhas.append(f"- {afirmacao}")
        if trecho is None:
            linhas.append(f"  - Referência **não encontrada na base**: `{trecho_id}`")
        else:
            resumo = " ".join(trecho.texto.split())[:200]
            linhas.append(f"  - Fonte: `{trecho_id}` ({trecho.secao})")
            linhas.append(f"  - Trecho: \"{resumo}\"")
    return linhas


def gerar_dossie(
    projeto_id: str,
    pontos: list[PontoDecisao],
    trechos: dict[str, Trecho],
    versao_norma: str,
    nao_verificado: list[str],
    emitido_em: Optional[datetime] = None,
) -> str:
    if not decisao_final_pronta(pontos):
        pendentes = [p.decision_id for p in pontos if not p.decidido]
        raise DossieIncompleto(f"Há pontos sem decisão: {', '.join(pendentes)}.")

    emitido = (emitido_em or datetime.now()).strftime("%d/%m/%Y %H:%M")
    linhas: list[str] = [
        f"# Dossiê de análise preliminar: {projeto_id}",
        "",
        f"- Versão da norma utilizada: {versao_norma}",
        f"- Emitido em: {emitido}",
        "- Natureza: classificação preliminar. A decisão final é do analista.",
        "",
        "## Decisões",
        "",
    ]

    analistas: set[str] = set()
    for ponto in _ordenar(pontos):
        decisao = _ultimo_evento_decisao(ponto)
        justificativa = ponto.justificativa or {}
        linhas += [f"### {justificativa.get('titulo') or ponto.decision_id}", ""]
        linhas.append(f"- Identificador: `{ponto.decision_id}`")
        linhas.append(f"- Proposta da IA: **{ponto.valor_proposto}**")
        if justificativa.get("parecer"):
            linhas.append(f"- Parecer da IA: {justificativa['parecer']}")
        if justificativa.get("auditoria"):
            linhas.append(f"- {justificativa['auditoria']['texto']}")

        if decisao:
            analista = decisao.get("analista", "")
            analistas.add(analista)
            frase = frase_da_decisao(
                decisao.get("acao", ""),
                analista,
                ponto.valor_proposto,
                ponto.valor_final,
                decisao.get("motivo"),
            )
            linhas.append(f"- Decisão do analista: {frase}")
            linhas.append(f"- Valor final: **{ponto.valor_final}**")
            linhas.append(f"- Analista: {analista}")
            linhas.append(f"- Registrado em: {_data(decisao.get('ts'))}")
        else:
            linhas.append(f"- Valor final: **{ponto.valor_final}**")

        porque = justificativa.get("porque", [])
        if porque:
            linhas += ["", "Regra e evidência que sustentam:"]
            linhas += _secao_referencias(porque, trechos)

        como = justificativa.get("como", [])
        if como:
            linhas += ["", "Como a análise foi feita:"]
            linhas += [f"- {passo}" for passo in como]

        contrarias = justificativa.get("evidencias_contrarias", [])
        if contrarias:
            linhas += ["", "Evidências contrárias:"]
            linhas += [f"- {item}" for item in contrarias]

        lacunas = justificativa.get("lacunas", [])
        if lacunas:
            linhas += ["", "Lacunas:"]
            linhas += [f"- {item}" for item in lacunas]

        reaberturas = [e for e in ponto.eventos if e["evento"] == "ponto_reaberto"]
        if reaberturas:
            linhas.append(f"- Reaberto {len(reaberturas)} vez(es) por dependência.")

        linhas.append("")

    linhas += ["## O que não foi verificado", ""]
    linhas += [f"- {item}" for item in nao_verificado] or ["- Nada registrado."]
    linhas.append("")

    linhas += ["## Analistas envolvidos", ""]
    linhas += [f"- {a}" for a in sorted(analistas) if a]
    linhas.append("")

    return "\n".join(linhas)
