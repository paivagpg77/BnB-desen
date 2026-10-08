"""
Modelos do pacote de projetos do desafio.

Os identificadores sao os do proprio pacote (EV, ATV, S, M, OBS, IN, CR) e as
ancoras seguem a convencao "arquivo#identificador". Valor ausente e None,
nunca zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Evidencia:
    id_evidencia: str           # ex.: "PRJ21-EV08"
    tipo: str
    arquivo: str                # relativo a pasta do projeto
    conteudo_esperado: str
    status: str                 # "Localizada" = arquivo entregue, nao alegacao comprovada
    observacao: str
    presente: bool              # o arquivo existe de fato na pasta


@dataclass(frozen=True)
class Atividade:
    id_atividade: str
    ciclo: str
    fase: str
    natureza_informada_pela_equipe: str   # autodeclaracao, nao conclusao
    descricao: str
    resultado_ou_saida: str
    evidencias_relacionadas: tuple[str, ...]
    responsavel_por_funcao: str


@dataclass(frozen=True)
class Medicao:
    registro_id: str            # ex.: "PRJ21-S01-M001"
    ensaio_id: str
    versao: str
    cenario: str
    tipo: str                   # contador, medicao ou histograma
    metrica: str
    valor: Optional[float]
    numerador: Optional[float]
    denominador: Optional[float]
    peso: Optional[float]
    unidade: str


@dataclass(frozen=True)
class Resultado:
    ensaio_id: str
    versao: str
    metrica: str
    operacao: str
    valor: Optional[float]
    base_de_calculo: Optional[float]
    descricao_base: str
    taxa_percentual: Optional[float]
    unidade: str
    fonte: str
    natureza: str               # desempenho ou entrega


@dataclass(frozen=True)
class EventoCronologia:
    evento_id: str
    data: str
    versao: str
    evento: str
    estado: str
    fonte: str


@dataclass(frozen=True)
class Observacao:
    observacao_id: str
    entrada: str
    referencia: str
    saida_ou_situacao: str
    escopo: str


@dataclass(frozen=True)
class Entrada:
    entrada_id: str
    conteudo_json: str


@dataclass(frozen=True)
class Secao:
    ancora: str                 # ex.: "evidencias/metodo.md#2"
    arquivo: str
    titulo: str
    texto: str


@dataclass
class ProjetoCarregado:
    projeto_id: str
    pasta: Path
    evidencias: list[Evidencia] = field(default_factory=list)
    atividades: list[Atividade] = field(default_factory=list)
    medicoes: list[Medicao] = field(default_factory=list)
    resultados: list[Resultado] = field(default_factory=list)
    cronologia: list[EventoCronologia] = field(default_factory=list)
    observacoes: list[Observacao] = field(default_factory=list)
    entradas: list[Entrada] = field(default_factory=list)
    configuracao: dict = field(default_factory=dict)
    secoes: list[Secao] = field(default_factory=list)
    # Texto integral por arquivo (relativo a pasta do projeto).
    textos: dict[str, str] = field(default_factory=dict)
    # Arquivos do inventario que nao estao na pasta ou nao puderam ser lidos.
    ausentes: list[str] = field(default_factory=list)

    @property
    def arquivos(self) -> set[str]:
        return {e.arquivo for e in self.evidencias if e.presente}

    def secao(self, ancora: str) -> Optional[Secao]:
        return next((s for s in self.secoes if s.ancora == ancora), None)

    def ensaios(self) -> set[str]:
        return {m.ensaio_id for m in self.medicoes} | {r.ensaio_id for r in self.resultados}
