"""
Redacao dos pareceres em linguagem direta.

Cada ponto de decisao mostra uma frase completa: a conclusao e o motivo, no
formato "conclusao, porque motivo". O valor tecnico (o estado do criterio ou a
classificacao) continua guardado a parte, para a regra e para o registro.
"""

from __future__ import annotations

from typing import Optional

from src.motor.regras import (
    COM_RESSALVAS,
    ELEGIVEL,
    EVIDENCIA_INSUFICIENTE,
    NAO_ELEGIVEL,
    ROTULO_CRITERIO,
    Criterio,
)

FRASE_DO_ESTADO: dict[Criterio, dict[str, str]] = {
    Criterio.NOVIDADE: {
        "DEMONSTRADA NO RECORTE": "A novidade está demonstrada no recorte analisado",
        "NÃO DEMONSTRADA": "A novidade não está demonstrada",
        "INDETERMINADA": "Não é possível dizer se há novidade",
    },
    Criterio.CRIATIVIDADE: {
        "DEMONSTRADA NO RECORTE": "A criatividade técnica está demonstrada no recorte analisado",
        "NÃO DEMONSTRADA": "A criatividade técnica não está demonstrada",
        "INDETERMINADA": "Não é possível dizer se há criatividade técnica",
    },
    Criterio.INCERTEZA: {
        "INVESTIGADA": "A incerteza tecnológica foi investigada",
        "NÃO CARACTERIZADA": "A incerteza tecnológica não está caracterizada",
        "ALEGADA, NÃO VERIFICÁVEL": "A incerteza tecnológica é alegada, mas não pode ser verificada",
    },
    Criterio.SISTEMATICIDADE: {
        "DOCUMENTADA": "O trabalho sistemático está documentado",
        "DOCUMENTADA COMO ACEITE": "O trabalho está documentado como aceite, não como investigação",
        "PARCIAL": "O trabalho sistemático está documentado só em parte",
    },
    Criterio.TRANSFERENCIA: {
        "DOCUMENTADA NO ESCOPO": "O conhecimento está registrado e pode ser reproduzido no escopo do projeto",
        "DOCUMENTADA COM LIMITE": "O conhecimento está registrado e pode ser reproduzido, com um limite",
        "DOCUMENTADA PARA A CONFIGURAÇÃO": "Só a configuração aplicada está registrada",
        "INSUFICIENTE PARA O NÚCLEO ALEGADO": "O registro é insuficiente para reproduzir o núcleo alegado",
    },
}

RAZAO_DA_CLASSIFICACAO: dict[str, str] = {
    ELEGIVEL: "os cinco critérios estão demonstrados pelas evidências do projeto",
    COM_RESSALVAS: (
        "há pesquisa e desenvolvimento demonstrados, mas uma limitação concreta "
        "restringe parte da conclusão pretendida"
    ),
    NAO_ELEGIVEL: (
        "novidade, criatividade e incerteza tecnológica têm conclusão negativa "
        "fundamentada: o trabalho aplicou uma solução já conhecida"
    ),
    EVIDENCIA_INSUFICIENTE: (
        "falta informação essencial para verificar novidade, criatividade ou "
        "incerteza tecnológica"
    ),
}

NATUREZA_DA_ATIVIDADE = {
    "investigacao": "investigação",
    "rotina": "rotina",
    "apoio": "apoio",
    "indeterminada": "natureza indeterminada",
}


def em_continuacao(texto: str) -> str:
    """Prepara o texto para continuar uma frase: inicial minuscula, sem ponto final."""
    motivo = " ".join(texto.split()).rstrip(". ")
    if not motivo:
        return motivo
    primeira = motivo.split()[0]
    # Siglas e identificadores (GW-7, PRJ21) mantem a caixa original.
    if primeira[0].isupper() and (len(primeira) == 1 or primeira[1:].islower()):
        motivo = motivo[0].lower() + motivo[1:]
    return motivo


def com_motivo(conclusao: str, motivo: Optional[str]) -> str:
    """'Conclusao, porque motivo.' Sem motivo, so a conclusao."""
    conclusao = conclusao.rstrip(". ")
    motivo = em_continuacao(motivo or "")
    return f"{conclusao}, porque {motivo}." if motivo else f"{conclusao}."


def frase_do_estado(criterio: Criterio, estado: Optional[str]) -> str:
    """Estado do criterio em frase. Estado desconhecido aparece como foi escrito."""
    if not estado:
        return f"{ROTULO_CRITERIO[criterio]}: sem avaliação"
    return FRASE_DO_ESTADO[criterio].get(
        estado.strip().upper(), f"{ROTULO_CRITERIO[criterio]}: {estado}"
    )


def parecer_do_criterio(criterio: Criterio, estado: str, justificativa: str) -> str:
    return com_motivo(frase_do_estado(criterio, estado), justificativa)


def parecer_da_classificacao(
    classificacao: Optional[str], estados: dict[Criterio, str]
) -> str:
    criterios = "; ".join(
        frase_do_estado(c, estados.get(c)).rstrip(".").lower() if c in estados else ""
        for c in Criterio
        if c in estados
    )
    if classificacao is None:
        return (
            "A ferramenta não sugere uma classificação, porque os critérios "
            "confirmados não se encaixam em nenhuma regra: a decisão é do analista. "
            f"Critérios confirmados: {criterios}."
        )
    return (
        f"{com_motivo(classificacao, RAZAO_DA_CLASSIFICACAO[classificacao])} "
        f"Critérios confirmados: {criterios}."
    )


def frase_da_decisao(
    acao: str,
    analista: str,
    valor_proposto: Optional[str],
    valor_final: Optional[str],
    motivo: Optional[str],
) -> str:
    """
    Decisao do analista em uma frase. O motivo aparece com as palavras exatas
    do analista: e o registro dele, e nao deve ser reescrito.
    """
    registrado = f" Motivo registrado: {motivo.strip()}" if motivo and motivo.strip() else ""
    if acao == "aceita":
        return f"{analista} aceitou a proposta da IA."
    if acao == "alterada":
        return (
            f"{analista} alterou a proposta de “{valor_proposto}” para “{valor_final}”."
            f"{registrado}"
        )
    if acao == "rejeitada":
        return f"{analista} rejeitou a proposta da IA.{registrado}"
    return f"{analista}: {acao}.{registrado}"
