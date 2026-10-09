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

from src.texto.tokens import remover_acentos


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

    @classmethod
    def de_rotulo(cls, rotulo: Optional[str]) -> Optional["ClassificacaoPreliminar"]:
        """Classe a partir do rotulo acentuado da interface; None se nao for uma classe."""
        try:
            return cls(remover_acentos(rotulo or "").strip())
        except ValueError:
            return None


MOTIVO_MIN_CARACTERES = 20


class RevisaoCega(BaseModel):
    """Decisao do segundo analista, tomada sem ver a decisao do primeiro."""

    analista_pseudonimo: str = Field(min_length=3)
    decisao: ResultadoAnalista
    # Valor que o revisor daria ao ponto, quando discorda da IA e o ponto tem
    # vocabulario fechado. Permite distinguir convergencia de divergencia.
    valor: Optional[str] = None
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
    # Valor do ponto: o que a IA propos e o que o analista decidiu (None quando
    # ele rejeitou sem dar outro valor). Em D2 e o estado do criterio.
    valor_ia: str = ""
    valor_analista: Optional[str] = None
    # Proposta da IA como foi apresentada (parecer e fontes), para a revisao cega.
    justificativa_ia: dict = Field(default_factory=dict)
    # So em D5, onde o valor do ponto e a classificacao do projeto.
    classificacao_ia: Optional[ClassificacaoPreliminar] = None
    classificacao_analista: Optional[ClassificacaoPreliminar] = None
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
            if revisao.valor and self.valor_analista and revisao.valor != self.valor_analista:
                # Os dois discordam da IA, mas nao entre si: vai ao responsavel da equipe.
                self.status = StatusDiscordancia.DIVERGENCIA_ENTRE_ANALISTAS
            else:
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
    valor_resultante: Optional[str] = None
    classificacao_resultante: Optional[ClassificacaoPreliminar] = None
    data: datetime
    natureza: str = Field(default="interno_nao_normativo", frozen=True)


class ResumoPrecedentes(BaseModel):
    """O que o cartao de decisao exibe na secao 'Precedentes internos (nao normativos)'."""

    criterio: str
    tipo: TipoDiscordancia
    quantidade_casos: int = Field(ge=0)
    casos: list[PrecedenteInterno] = Field(default_factory=list)
    aviso: str = (
        "Precedentes internos. Não são fundamento legal e não alteram "
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


def padroes_candidatos(
    registros: list[RegistroDiscordancia],
) -> list[tuple[str, TipoDiscordancia, list[RegistroDiscordancia]]]:
    """Grupos de mesmo criterio e tipo que atingiram o limiar: a fila do curador."""
    grupos: dict[tuple[str, TipoDiscordancia], list[RegistroDiscordancia]] = {}
    for r in registros:
        if r.status == StatusDiscordancia.CONVERGENCIA_CONTRA_IA:
            grupos.setdefault((r.criterio, r.tipo), []).append(r)
    return [
        (criterio, tipo, casos)
        for (criterio, tipo), casos in grupos.items()
        if e_padrao_candidato(casos)
    ]
