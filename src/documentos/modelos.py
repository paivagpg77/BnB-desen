"""Modelos de documento e de trecho. Todo trecho carrega sua origem e versao."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

TIPO_NORMA = "norma"
TIPO_PROJETO = "projeto"


@dataclass(frozen=True)
class Documento:
    doc_id: str                 # ex.: "lei-11196-2005" ou "PRJ-TESTE-dossie"
    tipo: str                   # TIPO_NORMA ou TIPO_PROJETO
    titulo: str
    texto: str
    versao: Optional[str] = None
    projeto_id: Optional[str] = None
    origem: Optional[str] = None   # nome do arquivo de origem


@dataclass(frozen=True)
class Trecho:
    trecho_id: str              # ex.: "PRJ-TESTE-dossie#003"
    doc_id: str
    tipo: str
    projeto_id: Optional[str]
    secao: str                  # titulo da secao, artigo ou ID da atividade
    texto: str
    versao: Optional[str] = None
