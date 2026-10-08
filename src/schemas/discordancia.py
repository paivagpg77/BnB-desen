"""
Fase 1 - Modulo de discordancias e precedentes internos.

Schemas (Pydantic v2) para o registro de discordancias entre analista e IA,
a revisao cega por segundo analista e o precedente interno que a IA pode
consultar. Precedentes sao NAO normativos: nunca alteram proposta, status ou
classificacao, e nunca sao citados como fundamento legal.

Arquivo sugerido: src/schemas/discordancia.py
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class TipoDiscordancia(str, Enum):
    EVIDENCIA_MAL_LIDA = "EVIDENCIA_MAL_LIDA"
    EVIDENCIA_AUSENTE = "EVIDENCIA_AUSENTE"
    REGRA_MAL_APLICADA = "REGRA_MAL_APLICADA"
    DIVERGENCIA_DE_MERITO = "DIVERGENCIA_DE_MERITO"


class StatusDiscordancia(str, Enum):
    REGISTRADA = "registrada"                      # analista discordou, aguarda revisao
    EM_REVISAO_CEGA = "em_revisao_cega"            # segundo analista analisando
    CONVERGENCIA_CONTRA_IA = "convergencia_contra_ia"
    NAO_CONFIRMADA = "nao_confirmada"              # segundo analista concordou com a IA
    DIVERGENCIA_ENTRE_ANALISTAS = "divergencia_entre_analistas"
    ENCAMINHADA_CURADOR = "encaminhada_curador"    # padrao candidato enviado


class ResultadoAnalista(str, Enum):
    ACEITA_IA = "aceita_ia"
    DISCORDA_IA = "discorda_ia"


class ClassificacaoPreliminar(str, Enum):
    ELEGIVEL = "Elegivel"
    COM_RESSALVAS = "Com ressalvas"
    NAO_ELEGIVEL = "Nao elegivel"
    EVIDENCIA_INSUFICIENTE = "Evidencia insuficiente"


MOTIVO_MIN_CARACTERES = 20


class RevisaoCega(BaseModel):
    """Decisao do segundo analista, tomada sem ver a decisao do primeiro."""

    analista_pseudonimo: str = Field(min_length=3)
    decisao: ResultadoAnalista
    motivo: str = Field(min_length=MOTIVO_MIN_CARACTERES)
    registrada_em: datetime


class RegistroDiscordancia(BaseModel):
    """Evento principal: um analista discordou de uma proposta da IA."""

    discordancia_id: str
    projeto_id: str
    decision_id: str                      # ponto D1..D5 e criterio de origem
    criterio: str                         # ex.: "novidade"
    tipo: TipoDiscordancia
    versao_norma: str
    versao_motor: str                     # identificador do prompt e do modelo usados

    analista_origem_pseudonimo: str = Field(min_length=3)
    motivo: str = Field(min_length=MOTIVO_MIN_CARACTERES)
    classificacao_ia: ClassificacaoPreliminar
    classificacao_analista: ClassificacaoPreliminar
    registrada_em: datetime

    revisao: Optional[RevisaoCega] = None
    status: StatusDiscordancia = StatusDiscordancia.REGISTRADA

    @model_validator(mode="after")
    def revisor_deve_ser_diferente(self) -> "RegistroDiscordancia":
        if self.revisao and (
            self.revisao.analista_pseudonimo == self.analista_origem_pseudonimo
        ):
            raise ValueError("O segundo analista precisa ser diferente do primeiro.")
        return self

    def resolver_revisao(self, revisao: RevisaoCega) -> "RegistroDiscordancia":
        """Aplica a regra de convergencia e atualiza o status. Nao altera a decisao do caso."""
        if revisao.analista_pseudonimo == self.analista_origem_pseudonimo:
            raise ValueError("Revisao cega exige analista diferente do originador.")

        self.revisao = revisao

        if revisao.decisao == ResultadoAnalista.DISCORDA_IA:
            self.status = StatusDiscordancia.CONVERGENCIA_CONTRA_IA
        else:
            # Segundo analista concordou com a IA: discordancia nao confirmada.
            self.status = StatusDiscordancia.NAO_CONFIRMADA

        return self


class PrecedenteInterno(BaseModel):
    """
    Item recuperado pelo motor (terceiro corpus do RAG).
    Sempre rotulado como interno e nao normativo.
    """

    precedente_id: str
    discordancia_id: str
    projeto_origem: str
    criterio: str
    tipo: TipoDiscordancia
    motivo_resumido: str = Field(max_length=300)
    classificacao_resultante: ClassificacaoPreliminar
    data: datetime
    natureza: str = Field(default="interno_nao_normativo", frozen=True)


class ResumoPrecedentes(BaseModel):
    """O que o cartao de decisao exibe na secao 'Precedentes internos (nao normativos)'."""

    criterio: str
    tipo: TipoDiscordancia
    quantidade_casos: int = Field(ge=0)
    casos: list[PrecedenteInterno] = Field(default_factory=list)
    aviso: str = (
        "Precedentes internos. Nao sao fundamento legal e nao alteram "
        "a proposta atual."
    )


LIMIAR_PADRAO_CANDIDATO = 3  # valor a validar com o BNB (base v0.2, item 10.6)


def e_padrao_candidato(registros: list[RegistroDiscordancia]) -> bool:
    """
    Um padrao vai ao curador quando ha pelo menos LIMIAR casos independentes
    com CONVERGENCIA_CONTRA_IA, do mesmo criterio e tipo, de projetos distintos.
    """
    convergentes = [
        r for r in registros
        if r.status == StatusDiscordancia.CONVERGENCIA_CONTRA_IA
    ]
    projetos_distintos = {r.projeto_id for r in convergentes}
    return len(projetos_distintos) >= LIMIAR_PADRAO_CANDIDATO
