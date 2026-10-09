"""
Criterios, estados e regra de classificacao.

Cada criterio tem um vocabulario fechado de estados. A classificacao final nao
e opiniao do modelo: e derivada dos estados que o analista confirmou, por uma
regra explicita. Quando os estados nao se encaixam em nenhuma linha da regra,
a ferramenta nao sugere classe e a decisao fica inteiramente com o analista.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class Criterio(str, Enum):
    NOVIDADE = "novidade"
    CRIATIVIDADE = "criatividade"
    INCERTEZA = "incerteza"
    SISTEMATICIDADE = "sistematicidade"
    TRANSFERENCIA = "transferencia"


ROTULO_CRITERIO: dict[Criterio, str] = {
    Criterio.NOVIDADE: "Novidade",
    Criterio.CRIATIVIDADE: "Criatividade técnica",
    Criterio.INCERTEZA: "Incerteza tecnológica",
    Criterio.SISTEMATICIDADE: "Sistematicidade",
    Criterio.TRANSFERENCIA: "Transferência/reprodução",
}


class Sinal(str, Enum):
    POSITIVO = "positivo"
    COM_LIMITE = "com_limite"
    NEGATIVO = "negativo"
    INDETERMINADO = "indeterminado"


# Estado -> sinal, por criterio. A ordem lista primeiro o estado favoravel.
ESTADOS: dict[Criterio, dict[str, Sinal]] = {
    Criterio.NOVIDADE: {
        "DEMONSTRADA NO RECORTE": Sinal.POSITIVO,
        "NÃO DEMONSTRADA": Sinal.NEGATIVO,
        "INDETERMINADA": Sinal.INDETERMINADO,
    },
    Criterio.CRIATIVIDADE: {
        "DEMONSTRADA NO RECORTE": Sinal.POSITIVO,
        "NÃO DEMONSTRADA": Sinal.NEGATIVO,
        "INDETERMINADA": Sinal.INDETERMINADO,
    },
    Criterio.INCERTEZA: {
        "INVESTIGADA": Sinal.POSITIVO,
        "NÃO CARACTERIZADA": Sinal.NEGATIVO,
        "ALEGADA, NÃO VERIFICÁVEL": Sinal.INDETERMINADO,
    },
    Criterio.SISTEMATICIDADE: {
        "DOCUMENTADA": Sinal.POSITIVO,
        "DOCUMENTADA COMO ACEITE": Sinal.NEGATIVO,
        "PARCIAL": Sinal.INDETERMINADO,
    },
    Criterio.TRANSFERENCIA: {
        "DOCUMENTADA NO ESCOPO": Sinal.POSITIVO,
        "DOCUMENTADA COM LIMITE": Sinal.COM_LIMITE,
        "DOCUMENTADA PARA A CONFIGURAÇÃO": Sinal.NEGATIVO,
        "INSUFICIENTE PARA O NÚCLEO ALEGADO": Sinal.INDETERMINADO,
    },
}

ELEGIVEL = "Elegível"
COM_RESSALVAS = "Com ressalvas"
NAO_ELEGIVEL = "Não elegível"
EVIDENCIA_INSUFICIENTE = "Evidência insuficiente"
CLASSIFICACOES = (ELEGIVEL, COM_RESSALVAS, NAO_ELEGIVEL, EVIDENCIA_INSUFICIENTE)

NUCLEO = (Criterio.NOVIDADE, Criterio.CRIATIVIDADE, Criterio.INCERTEZA)


def estado_indeterminado(criterio: Criterio) -> str:
    """Estado usado quando a proposta do modelo nao tem fonte verificavel."""
    return next(e for e, s in ESTADOS[criterio].items() if s == Sinal.INDETERMINADO)


def sinal(criterio: Criterio, estado: str) -> Optional[Sinal]:
    return ESTADOS[criterio].get(estado.strip().upper())


def derivar_classificacao(estados: dict[Criterio, str]) -> tuple[Optional[str], str]:
    """
    Devolve (classificacao, regra aplicada). Classificacao None significa que a
    combinacao de estados nao esta coberta: o analista decide sem sugestao.
    """
    sinais: dict[Criterio, Optional[Sinal]] = {
        c: sinal(c, estados.get(c, "")) for c in Criterio
    }
    faltando = [ROTULO_CRITERIO[c] for c, s in sinais.items() if s is None]
    if faltando:
        return None, f"Sem regra: critério sem estado válido ({', '.join(faltando)})."

    nucleo = [sinais[c] for c in NUCLEO]
    if Sinal.INDETERMINADO in nucleo:
        return (
            EVIDENCIA_INSUFICIENTE,
            "R1: novidade, criatividade ou incerteza não pôde ser verificada; "
            "falta informação essencial sobre o núcleo alegado.",
        )
    if all(s == Sinal.NEGATIVO for s in nucleo):
        return (
            NAO_ELEGIVEL,
            "R2: novidade, criatividade e incerteza têm conclusão negativa "
            "fundamentada; o trabalho caracteriza aplicação conhecida.",
        )
    if all(s == Sinal.POSITIVO for s in nucleo):
        sistematicidade = sinais[Criterio.SISTEMATICIDADE]
        transferencia = sinais[Criterio.TRANSFERENCIA]
        if sistematicidade == Sinal.POSITIVO and transferencia == Sinal.POSITIVO:
            return ELEGIVEL, "R3: os cinco critérios estão demonstrados no escopo."
        if sistematicidade == Sinal.POSITIVO and transferencia == Sinal.COM_LIMITE:
            return (
                COM_RESSALVAS,
                "R4: P&D demonstrado, com limitação concreta que restringe parte "
                "da conclusão pretendida.",
            )
    return (
        None,
        "Sem regra: combinação de estados não coberta. A classificação fica "
        "com o analista, sem sugestão da ferramenta.",
    )
