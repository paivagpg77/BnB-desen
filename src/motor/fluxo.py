"""
Liga a analise conferida aos pontos de decisao D1 a D5.

D1 a D4 sao propostos de uma vez. D5 so e proposto depois que o analista
decidiu os cinco criterios: a classificacao e derivada dos estados que ele
confirmou, nao dos que o modelo sugeriu.
"""

from __future__ import annotations

from src.decisoes.maquina_estados import Ponto, PontoDecisao, Status, reabrir_dependentes
from src.documentos.modelos import Trecho
from src.motor.linguagem import (
    NATUREZA_DA_ATIVIDADE,
    com_motivo,
    em_continuacao,
    parecer_da_classificacao,
    parecer_do_criterio,
)
from src.motor.regras import (
    EVIDENCIA_INSUFICIENTE,
    ROTULO_CRITERIO,
    Criterio,
    derivar_classificacao,
)
from src.motor.schemas import AnaliseConferida, Apontamento
from src.pacote.carregador import PacoteInvalido, raiz_do_pacote
from src.rag.biblioteca import PREFIXO_HISTORICO, carregar_orientacoes
from src.rag.corpus import CorpusProjeto, carregar_regras

SEM_FONTE = "Sem fonte verificável: confira antes de decidir."
VEREDITOS = {
    "sustenta": "as fontes citadas sustentam a justificativa",
    "sustenta_em_parte": "as fontes citadas sustentam só parte da justificativa",
    "nao_sustenta": "as fontes citadas não sustentam a justificativa",
}
NATUREZAS = NATUREZA_DA_ATIVIDADE
TITULOS = {
    Ponto.D1: "D1 · Entendimento do projeto",
    Ponto.D3: "D3 · Atividades: investigação ou rotina",
    Ponto.D4: "D4 · Evidências contrárias, divergências e lacunas",
    Ponto.D5: "D5 · Classificação final",
}


def titulo_do_ponto(ponto: PontoDecisao) -> str:
    if ponto.ponto == Ponto.D2:
        return f"D2 · {ROTULO_CRITERIO[Criterio(ponto.criterio)]}"
    return TITULOS[ponto.ponto]


def _plural(quantidade: int, singular: str, plural: str) -> str:
    return f"{quantidade} {singular if quantidade == 1 else plural}"


def trechos_do_dossie(corpus: CorpusProjeto) -> dict[str, Trecho]:
    """Evidencias do projeto e regras, para o dossie conferir cada referencia."""
    trechos = dict(corpus.trechos)
    trechos.update({t.trecho_id: t for t in carregar_regras()})
    try:
        trechos.update({t.trecho_id: t for t in carregar_orientacoes(raiz_do_pacote())})
    except PacoteInvalido:
        pass
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
    if analise.exemplos:
        referencias = ", ".join(e.removeprefix(PREFIXO_HISTORICO) for e in analise.exemplos)
        como.append(
            f"Pareceres históricos usados como exemplo de fundamentação: {referencias}. "
            "Não foram usados para classificar por semelhança."
        )
    pontos: list[PontoDecisao] = []

    d1 = PontoDecisao(projeto_id=projeto_id, ponto=Ponto.D1)
    entendimento = proposta.entendimento
    d1.propor(
        f"Problema: {entendimento.problema} Estado anterior: {entendimento.estado_anterior} "
        f"Trabalho realizado: {entendimento.trabalho_realizado}",
        {
            "titulo": TITULOS[Ponto.D1],
            "parecer": (
                f"{entendimento.problema.rstrip('. ')}. "
                f"Antes do projeto: {em_continuacao(entendimento.estado_anterior)}. "
                f"O que a equipe fez: {em_continuacao(entendimento.trabalho_realizado)}."
            ),
            "porque": _porque("Entendimento do projeto", entendimento.fontes),
            "como": como,
            "lacunas": [] if entendimento.fontes else [SEM_FONTE],
        },
    )
    pontos.append(d1)

    auditoria = {a.criterio: a for a in (analise.orquestracao.auditoria if analise.orquestracao else [])}
    if analise.orquestracao:
        como.append(
            "Modelos por papel: "
            + "; ".join(
                f"{p.papel}: {p.provedor} ({p.modelo})"
                + ("" if p.concluido else " — não respondeu")
                for p in analise.orquestracao.papeis
            )
            + "."
        )

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
                "titulo": titulo_do_ponto(ponto),
                "parecer": parecer_do_criterio(criterio, avaliacao.estado, avaliacao.justificativa),
                "auditoria": (
                    {
                        "veredito": auditoria[criterio].veredito,
                        "texto": com_motivo(
                            f"Auditoria das fontes: {VEREDITOS[auditoria[criterio].veredito]}",
                            auditoria[criterio].comentario,
                        ),
                    }
                    if criterio in auditoria
                    else None
                ),
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
    grupos = {
        rotulo: [a.id_atividade for a in proposta.atividades if a.natureza == natureza]
        for natureza, rotulo in NATUREZAS.items()
    }
    parecer_d3 = " ".join(
        f"{_plural(len(ids), 'atividade', 'atividades')} de {rotulo} ({', '.join(ids)})."
        for rotulo, ids in grupos.items()
        if ids
    )
    d3.propor(
        valor,
        {
            "titulo": TITULOS[Ponto.D3],
            "parecer": parecer_d3 or "O modelo não classificou nenhuma atividade.",
            "porque": [
                {
                    "afirmacao": com_motivo(
                        f"{a.id_atividade} é {NATUREZAS[a.natureza]}", a.justificativa
                    ),
                    "trecho_id": a.id_atividade,
                }
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
    achados = [
        texto
        for quantidade, texto in (
            (len(proposta.contrarias), _plural(len(proposta.contrarias), "evidência contrária à conclusão", "evidências contrárias à conclusão")),
            (len(proposta.divergencias), _plural(len(proposta.divergencias), "divergência entre a entrevista e os registros", "divergências entre a entrevista e os registros")),
            (len(proposta.lacunas), _plural(len(proposta.lacunas), "lacuna de informação", "lacunas de informação")),
        )
        if quantidade
    ]
    if achados:
        lista = achados[0] if len(achados) == 1 else ", ".join(achados[:-1]) + " e " + achados[-1]
        parecer_d4 = f"A análise encontrou {lista}. Confira cada item antes da classificação final."
    else:
        parecer_d4 = (
            "A análise não encontrou evidências contrárias, divergências entre a "
            "entrevista e os registros, nem lacunas de informação."
        )
    d4.propor(
        f"{len(proposta.contrarias)} evidência(s) contrária(s), "
        f"{len(proposta.divergencias)} divergência(s) entre depoimento e registro, "
        f"{len(proposta.lacunas)} lacuna(s).",
        {
            "titulo": TITULOS[Ponto.D4],
            "parecer": parecer_d4,
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


def rever_ponto(pontos: list[PontoDecisao], ponto: PontoDecisao, analista: str) -> list[PontoDecisao]:
    """
    O analista volta a um ponto ja decidido. O ponto e os que dependem dele sao
    reabertos e a ultima proposta da IA volta a aguardar decisao. D5 fica sem
    proposta: e derivado de novo quando os criterios estiverem decididos.
    """
    ponto.reabrir(causa=f"revisão pedida por {analista}")
    reabertos = [ponto] + reabrir_dependentes(pontos, ponto)
    for reaberto in reabertos:
        if reaberto.ponto != Ponto.D5:
            reaberto.propor(reaberto.valor_proposto, reaberto.justificativa)
    return reabertos


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

    estados = estados_confirmados(pontos)
    classificacao, regra = derivar_classificacao(estados)
    proposta = analise.proposta
    parecer = parecer_da_classificacao(classificacao, estados)
    # A justificativa do modelo so vale quando ele chegou a mesma classe.
    if classificacao and classificacao == proposta.classificacao_sugerida:
        parecer = f"{parecer} {proposta.justificativa.strip()}"
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
            "titulo": TITULOS[Ponto.D5],
            "parecer": parecer,
            "porque": [
                {"afirmacao": f"{ROTULO_CRITERIO[Criterio(p.criterio)]}: {p.valor_final}", "trecho_id": j["trecho_id"]}
                for p in pontos
                if p.ponto == Ponto.D2
                for j in p.justificativa.get("porque", [])[:1]
            ],
            "como": [
                f"Classificação derivada dos critérios confirmados pelo analista. {regra}",
                f"Classificação sugerida pelo modelo, sozinho: {proposta.classificacao_sugerida}.",
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
