"""
Regras do modulo de discordancias, sem depender da tela.

Uma discordancia nasce quando o analista altera ou rejeita uma proposta da IA.
Ela vai para a revisao cega de um segundo analista, que ve o caso e a evidencia
mas nao a decisao do primeiro. As que convergem contra a IA viram precedentes
internos: contexto para o analista, nunca fundamento, e nunca alteram proposta,
status ou classificacao.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.decisoes.maquina_estados import Ponto, PontoDecisao, Status
from src.motor.schemas import AnaliseConferida
from src.schemas.discordancia import (
    ClassificacaoPreliminar,
    PrecedenteInterno,
    RegistroDiscordancia,
    ResultadoAnalista,
    ResumoPrecedentes,
    RevisaoCega,
    StatusDiscordancia,
    TipoDiscordancia,
)

# A identificacao do analista entra no registro como pseudonimo.
IDENTIFICACAO_MIN_CARACTERES = 3
LIMITE_MOTIVO_RESUMIDO = 300

ROTULO_TIPO = {
    TipoDiscordancia.EVIDENCIA_MAL_LIDA: "Evidência mal lida: o trecho citado não sustenta a afirmação",
    TipoDiscordancia.EVIDENCIA_AUSENTE: "Evidência ausente: a IA concluiu sem trecho suficiente",
    TipoDiscordancia.REGRA_MAL_APLICADA: "Regra mal aplicada: critério aplicado de forma diferente da norma",
    TipoDiscordancia.DIVERGENCIA_DE_MERITO: "Divergência de mérito: leitura diferente do mesmo caso",
}

ROTULO_STATUS = {
    StatusDiscordancia.REGISTRADA: "Aguardando revisão cega",
    StatusDiscordancia.EM_REVISAO_CEGA: "Em revisão cega",
    StatusDiscordancia.CONVERGENCIA_CONTRA_IA: "Convergência contra a IA",
    StatusDiscordancia.NAO_CONFIRMADA: "Discordância não confirmada",
    StatusDiscordancia.DIVERGENCIA_ENTRE_ANALISTAS: "Divergência entre analistas",
    StatusDiscordancia.ENCAMINHADA_CURADOR: "Encaminhada ao curador",
}

# O que acontece com a discordancia depois da revisao cega.
DESFECHO = {
    StatusDiscordancia.CONVERGENCIA_CONTRA_IA: "Registrada como precedente interno (não normativo).",
    StatusDiscordancia.NAO_CONFIRMADA: "Registrada, sem ajuste de caso.",
    StatusDiscordancia.DIVERGENCIA_ENTRE_ANALISTAS: "Encaminhada ao responsável da equipe.",
}


def criterio_do_ponto(ponto: PontoDecisao) -> str:
    """Chave que agrupa discordancias e precedentes: o criterio em D2, o ponto nos demais."""
    return ponto.criterio or ponto.ponto.value


def abrir_discordancia(
    ponto: PontoDecisao,
    tipo: TipoDiscordancia,
    analise: AnaliseConferida,
    discordancia_id: str,
    agora: Optional[datetime] = None,
) -> RegistroDiscordancia:
    """Discordancia a partir de um ponto que o analista acabou de alterar ou rejeitar."""
    if ponto.status not in (Status.ALTERADA, Status.REJEITADA):
        raise ValueError("Só há discordância quando o analista altera ou rejeita a proposta.")
    e_classificacao = ponto.ponto == Ponto.D5
    return RegistroDiscordancia(
        discordancia_id=discordancia_id,
        projeto_id=ponto.projeto_id,
        decision_id=ponto.decision_id,
        criterio=criterio_do_ponto(ponto),
        tipo=tipo,
        versao_norma=f"base de regras {analise.versao_regras}",
        versao_motor=f"{analise.versao_prompt} / {analise.modelo}",
        analista_origem_pseudonimo=ponto.analista.strip(),
        motivo=ponto.motivo.strip(),
        valor_ia=ponto.valor_proposto,
        valor_analista=ponto.valor_final,
        justificativa_ia=ponto.justificativa,
        classificacao_ia=(
            ClassificacaoPreliminar.de_rotulo(ponto.valor_proposto) if e_classificacao else None
        ),
        classificacao_analista=(
            ClassificacaoPreliminar.de_rotulo(ponto.valor_final) if e_classificacao else None
        ),
        registrada_em=agora or datetime.now(timezone.utc),
    )


def ponto_da_discordancia(registro: RegistroDiscordancia) -> PontoDecisao:
    """
    O ponto como a IA o propos, para a revisao cega: so a proposta e as fontes,
    sem a decisao, o motivo ou a identificacao do primeiro analista.
    """
    resto = registro.decision_id.removeprefix(f"{registro.projeto_id}-")
    ponto, _, criterio = resto.partition("-")
    return PontoDecisao(
        projeto_id=registro.projeto_id,
        ponto=Ponto(ponto),
        criterio=criterio or None,
        status=Status.AGUARDANDO_ANALISTA,
        valor_proposto=registro.valor_ia,
        justificativa=registro.justificativa_ia,
    )


def fila_de_revisao(
    registros: list[RegistroDiscordancia], analista: str
) -> list[RegistroDiscordancia]:
    """Discordancias sem revisao que este analista pode revisar: as que nao sao dele."""
    eu = analista.strip().casefold()
    return [
        r for r in registros
        if r.status == StatusDiscordancia.REGISTRADA
        and r.analista_origem_pseudonimo.casefold() != eu
    ]


def nova_revisao(
    analista: str,
    concorda_com_a_ia: bool,
    motivo: str,
    valor: Optional[str] = None,
    agora: Optional[datetime] = None,
) -> RevisaoCega:
    return RevisaoCega(
        analista_pseudonimo=analista.strip(),
        decisao=ResultadoAnalista.ACEITA_IA if concorda_com_a_ia else ResultadoAnalista.DISCORDA_IA,
        valor=None if concorda_com_a_ia else valor,
        motivo=motivo.strip(),
        registrada_em=agora or datetime.now(timezone.utc),
    )


def _resumir(motivo: str) -> str:
    if len(motivo) <= LIMITE_MOTIVO_RESUMIDO:
        return motivo
    return motivo[: LIMITE_MOTIVO_RESUMIDO - 1].rstrip() + "…"


def precedentes_do_criterio(
    registros: list[RegistroDiscordancia], criterio: str
) -> list[ResumoPrecedentes]:
    """
    Precedentes internos de um criterio, agrupados por tipo de discordancia. So
    entram as discordancias confirmadas por um segundo analista.
    """
    grupos: dict[TipoDiscordancia, list[PrecedenteInterno]] = {}
    for r in registros:
        if r.criterio != criterio or r.status != StatusDiscordancia.CONVERGENCIA_CONTRA_IA:
            continue
        grupos.setdefault(r.tipo, []).append(
            PrecedenteInterno(
                precedente_id=f"PRC-{r.discordancia_id}",
                discordancia_id=r.discordancia_id,
                projeto_origem=r.projeto_id,
                criterio=r.criterio,
                tipo=r.tipo,
                motivo_resumido=_resumir(r.motivo),
                valor_resultante=r.valor_analista,
                classificacao_resultante=r.classificacao_analista,
                data=r.registrada_em,
            )
        )
    return [
        ResumoPrecedentes(criterio=criterio, tipo=tipo, quantidade_casos=len(casos), casos=casos)
        for tipo, casos in grupos.items()
    ]


def metricas(registros: list[RegistroDiscordancia]) -> dict:
    """Numeros de acompanhamento do modulo (base v0.2, item 11.7)."""
    por_status = {
        status: sum(r.status == status for r in registros) for status in StatusDiscordancia
    }
    convergentes = por_status[StatusDiscordancia.CONVERGENCIA_CONTRA_IA]
    revisadas = sum(r.revisao is not None for r in registros)
    por_criterio_e_tipo: dict[tuple[str, TipoDiscordancia], int] = {}
    for r in registros:
        chave = (r.criterio, r.tipo)
        por_criterio_e_tipo[chave] = por_criterio_e_tipo.get(chave, 0) + 1
    return {
        "total": len(registros),
        "aguardando_revisao": por_status[StatusDiscordancia.REGISTRADA],
        "revisadas": revisadas,
        "convergentes": convergentes,
        "nao_confirmadas": por_status[StatusDiscordancia.NAO_CONFIRMADA],
        "divergentes": por_status[StatusDiscordancia.DIVERGENCIA_ENTRE_ANALISTAS],
        # Convergencia contra a IA sobre o total de discordancias.
        "taxa_convergencia": convergentes / len(registros) if registros else None,
        # Revisoes cegas em que o segundo analista decidiu como o primeiro.
        "concordancia_entre_analistas": convergentes / revisadas if revisadas else None,
        "por_criterio_e_tipo": por_criterio_e_tipo,
    }
