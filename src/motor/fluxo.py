"""
Liga a analise conferida aos pontos de decisao D1 a D5.

D1 a D4 sao propostos de uma vez. D5 so e proposto depois que o analista
decidiu os cinco criterios: a classificacao e derivada dos estados que ele
confirmou, nao dos que o modelo sugeriu.
"""

from __future__ import annotations

from src.decisoes.maquina_estados import Ponto, PontoDecisao, Status
from src.documentos.modelos import Trecho
from src.motor.regras import (
    EVIDENCIA_INSUFICIENTE,
    ROTULO_CRITERIO,
    Criterio,
    derivar_classificacao,
)
from src.motor.schemas import AnaliseConferida, Apontamento
from src.rag.corpus import CorpusProjeto, carregar_regras

SEM_FONTE = "Sem fonte verificável: confira antes de decidir."
NATUREZAS = {
    "investigacao": "investigação",
    "rotina": "rotina",
    "apoio": "apoio",
    "indeterminada": "indeterminada",
}


def trechos_do_dossie(corpus: CorpusProjeto) -> dict[str, Trecho]:
    """Evidencias do projeto e regras, para o dossie conferir cada referencia."""
    trechos = dict(corpus.trechos)
    trechos.update({t.trecho_id: t for t in carregar_regras()})
    return trechos


def _porque(afirmacao: str, fontes: list[str]) -> list[dict]:
    return [{"afirmacao": afirmacao, "trecho_id": fonte} for fonte in fontes]


def _apontamentos(itens: list[Apontamento]) -> list[str]:
    return [f"{a.texto} (fontes: {', '.join(a.fontes)})" for a in itens]


def criar_pontos(analise: AnaliseConferida) -> list[PontoDecisao]:
    projeto_id = analise.projeto_id
    proposta = analise.proposta
    como = [
        f"Proposta gerada pelo modelo {analise.modelo}, prompt {analise.versao_prompt}, "
        f"base de regras {analise.versao_regras}.",
        "Fontes citadas conferidas contra os trechos enviados ao modelo.",
    ]
    pontos: list[PontoDecisao] = []

    d1 = PontoDecisao(projeto_id=projeto_id, ponto=Ponto.D1)
    entendimento = proposta.entendimento
    d1.propor(
        f"Problema: {entendimento.problema} Estado anterior: {entendimento.estado_anterior} "
        f"Trabalho realizado: {entendimento.trabalho_realizado}",
        {
            "porque": _porque("Entendimento do projeto", entendimento.fontes),
            "como": como,
            "lacunas": [] if entendimento.fontes else [SEM_FONTE],
        },
    )
    pontos.append(d1)

    for criterio in Criterio:
        avaliacao = proposta.criterio(criterio)
        ponto = PontoDecisao(projeto_id=projeto_id, ponto=Ponto.D2, criterio=criterio.value)
        porque = _porque(avaliacao.justificativa, avaliacao.fontes)
        if avaliacao.regra:
            porque.append(
                {"afirmacao": f"Regra aplicada: {ROTULO_CRITERIO[criterio]}", "trecho_id": avaliacao.regra}
            )
        ponto.propor(
            avaliacao.estado,
            {
                "porque": porque,
                "como": como,
                "lacunas": [] if avaliacao.fontes else [SEM_FONTE],
            },
        )
        pontos.append(ponto)

    d3 = PontoDecisao(projeto_id=projeto_id, ponto=Ponto.D3)
    if proposta.atividades:
        valor = "; ".join(
            f"{a.id_atividade}: {NATUREZAS[a.natureza]}" for a in proposta.atividades
        )
    else:
        valor = "Nenhuma atividade classificada pelo modelo."
    d3.propor(
        valor,
        {
            "porque": [
                {"afirmacao": a.justificativa or NATUREZAS[a.natureza], "trecho_id": a.id_atividade}
                for a in proposta.atividades
            ],
            "como": como
            + ["A natureza informada pela equipe é autodeclaração e não foi usada como prova."],
        },
    )
    pontos.append(d3)

    d4 = PontoDecisao(projeto_id=projeto_id, ponto=Ponto.D4)
    divergencias = [
        f"Divergência: a entrevista afirma \"{d.depoimento}\" ({d.fonte_depoimento}); "
        f"o registro mostra \"{d.registro}\" ({d.fonte_registro}). Prevalece: {d.prevalece}"
        for d in proposta.divergencias
    ]
    d4.propor(
        f"{len(proposta.contrarias)} evidência(s) contrária(s), "
        f"{len(proposta.divergencias)} divergência(s) entre depoimento e registro, "
        f"{len(proposta.lacunas)} lacuna(s).",
        {
            "porque": [
                item
                for a in proposta.favoraveis
                for item in _porque(f"Favorável: {a.texto}", a.fontes)
            ],
            "como": como,
            "evidencias_contrarias": _apontamentos(proposta.contrarias) + divergencias,
            "lacunas": list(proposta.lacunas),
        },
    )
    pontos.append(d4)

    pontos.append(PontoDecisao(projeto_id=projeto_id, ponto=Ponto.D5))
    return pontos


def estados_confirmados(pontos: list[PontoDecisao]) -> dict[Criterio, str]:
    return {
        Criterio(p.criterio): p.valor_final
        for p in pontos
        if p.ponto == Ponto.D2 and p.decidido and p.valor_final
    }


def propor_classificacao(pontos: list[PontoDecisao], analise: AnaliseConferida) -> PontoDecisao:
    """
    Propoe D5 a partir dos criterios ja decididos pelo analista. Sem regra
    aplicavel, a proposta e o status padrao e o aviso vai na justificativa.
    """
    d5 = next(p for p in pontos if p.ponto == Ponto.D5)
    if d5.status not in (Status.PROPOSTA, Status.REJEITADA, Status.REABERTA):
        return d5

    classificacao, regra = derivar_classificacao(estados_confirmados(pontos))
    proposta = analise.proposta
    complementos = [
        (rotulo, texto)
        for rotulo, texto in (
            ("Recorte sustentado", proposta.recorte_sustentado),
            ("Limitação", proposta.limitacao),
            ("Evidência necessária", proposta.evidencia_necessaria),
            ("Elo ausente", proposta.elo_ausente),
        )
        if texto
    ]
    d5.propor(
        classificacao or EVIDENCIA_INSUFICIENTE,
        {
            "porque": [
                {"afirmacao": f"{ROTULO_CRITERIO[Criterio(p.criterio)]}: {p.valor_final}", "trecho_id": j["trecho_id"]}
                for p in pontos
                if p.ponto == Ponto.D2
                for j in p.justificativa.get("porque", [])[:1]
            ],
            "como": [
                f"Classificação derivada dos estados confirmados pelo analista. {regra}",
                f"Justificativa do modelo: {proposta.justificativa}",
            ]
            + [f"{rotulo}: {texto}" for rotulo, texto in complementos],
            "lacunas": list(proposta.evidencias_a_solicitar)
            + (
                []
                if classificacao
                else ["Sem regra aplicável: o status padrão foi proposto e a decisão é do analista."]
            ),
        },
    )
    return d5
