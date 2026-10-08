"""
Formato da proposta do modelo e da analise conferida.

A saida do modelo e validada duas vezes: aqui (forma) e no analisador
(fontes citadas existem e estavam no contexto).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from src.motor.regras import CLASSIFICACOES, Criterio


class Entendimento(BaseModel):
    problema: str
    estado_anterior: str
    trabalho_realizado: str
    fontes: list[str] = Field(default_factory=list)


class AvaliacaoCriterio(BaseModel):
    criterio: Criterio
    estado: str
    justificativa: str
    regra: str = ""
    fontes: list[str] = Field(default_factory=list)

    @field_validator("estado")
    @classmethod
    def _maiusculas(cls, valor: str) -> str:
        return valor.strip().upper()


class AvaliacaoAtividade(BaseModel):
    id_atividade: str
    natureza: Literal["investigacao", "rotina", "apoio", "indeterminada"]
    justificativa: str = ""


class Divergencia(BaseModel):
    depoimento: str
    fonte_depoimento: str
    registro: str
    fonte_registro: str
    prevalece: str


class Apontamento(BaseModel):
    texto: str
    fontes: list[str] = Field(default_factory=list)


class PropostaModelo(BaseModel):
    """O que o modelo devolve."""

    entendimento: Entendimento
    criterios: list[AvaliacaoCriterio]
    atividades: list[AvaliacaoAtividade] = Field(default_factory=list)
    divergencias: list[Divergencia] = Field(default_factory=list)
    favoraveis: list[Apontamento] = Field(default_factory=list)
    contrarias: list[Apontamento] = Field(default_factory=list)
    lacunas: list[str] = Field(default_factory=list)
    classificacao_sugerida: str
    justificativa: str
    recorte_sustentado: Optional[str] = None
    limitacao: Optional[str] = None
    evidencia_necessaria: Optional[str] = None
    elo_ausente: Optional[str] = None
    evidencias_a_solicitar: list[str] = Field(default_factory=list)

    @field_validator("classificacao_sugerida")
    @classmethod
    def _classe_conhecida(cls, valor: str) -> str:
        if valor.strip() not in CLASSIFICACOES:
            raise ValueError(f"classificação fora das quatro permitidas: {valor!r}")
        return valor.strip()

    @field_validator("criterios")
    @classmethod
    def _cinco_criterios(cls, valor: list[AvaliacaoCriterio]) -> list[AvaliacaoCriterio]:
        recebidos = sorted(c.criterio.value for c in valor)
        esperados = sorted(c.value for c in Criterio)
        if recebidos != esperados:
            raise ValueError(f"esperados os cinco critérios, recebidos {recebidos}")
        return valor

    def criterio(self, criterio: Criterio) -> AvaliacaoCriterio:
        return next(c for c in self.criterios if c.criterio == criterio)


class AnaliseConferida(BaseModel):
    """Proposta do modelo depois da conferencia automatica."""

    projeto_id: str
    modelo: str                         # modelo de linguagem que respondeu
    versao_prompt: str
    versao_regras: str
    proposta: PropostaModelo
    # Fontes citadas que nao existem no contexto, por ponto.
    fontes_descartadas: dict[str, list[str]] = Field(default_factory=dict)
    # Avisos para o analista: pontos rebaixados, discordancia com a regra etc.
    avisos: list[str] = Field(default_factory=list)
    # Identificadores dos trechos enviados ao modelo.
    contexto: list[str] = Field(default_factory=list)
    classificacao_derivada: Optional[str] = None
    regra_classificacao: str = ""
