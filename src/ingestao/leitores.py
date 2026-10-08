"""
Leitura de documentos nos formatos aceitos pela ferramenta.

Formatos atuais: TXT, MD, CSV, JSON.
PDF: nao implementado nesta etapa. Exige biblioteca de extracao (pypdf ou
pdfplumber), que sera adicionada quando houver PDFs reais para testar.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional

from src.documentos.modelos import Documento


class FormatoNaoSuportado(ValueError):
    pass


def _linhas_para_secoes(registros: list[dict], chave: str) -> str:
    """Cada registro vira uma secao markdown, com o campo 'chave' como titulo."""
    partes = []
    for i, registro in enumerate(registros, start=1):
        titulo = str(registro.get(chave) or f"Registro {i}")
        partes.append(f"## {titulo}")
        for campo, valor in registro.items():
            if campo == chave:
                continue
            partes.append(f"{campo}: {valor}")
        partes.append("")
    return "\n".join(partes)


def _ler_csv(caminho: Path) -> str:
    with caminho.open(encoding="utf-8", newline="") as arquivo:
        registros = list(csv.DictReader(arquivo))
    if not registros:
        return ""
    chave = next(iter(registros[0].keys()))
    return _linhas_para_secoes(registros, chave)


def _ler_json(caminho: Path) -> str:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if isinstance(dados, dict) and isinstance(dados.get("texto"), str):
        return dados["texto"]
    if isinstance(dados, list) and dados and all(isinstance(x, dict) for x in dados):
        chave = next(iter(dados[0].keys()))
        return _linhas_para_secoes(dados, chave)
    if isinstance(dados, dict):
        return "\n".join(f"{k}: {v}" for k, v in dados.items())
    raise FormatoNaoSuportado(f"Estrutura JSON nao reconhecida em {caminho.name}.")


def ler_documento(
    caminho: str | Path,
    doc_id: str,
    tipo: str,
    titulo: Optional[str] = None,
    versao: Optional[str] = None,
    projeto_id: Optional[str] = None,
) -> Documento:
    p = Path(caminho)
    extensao = p.suffix.lower()

    if extensao in {".txt", ".md"}:
        texto = p.read_text(encoding="utf-8")
    elif extensao == ".csv":
        texto = _ler_csv(p)
    elif extensao == ".json":
        texto = _ler_json(p)
    elif extensao == ".pdf":
        raise FormatoNaoSuportado(
            "PDF ainda nao e suportado. Converta para TXT ou MD, ou aguarde a "
            "biblioteca de extracao de PDF."
        )
    else:
        raise FormatoNaoSuportado(f"Formato nao suportado: {extensao or '(sem extensao)'}")

    return Documento(
        doc_id=doc_id,
        tipo=tipo,
        titulo=titulo or p.stem,
        texto=texto,
        versao=versao,
        projeto_id=projeto_id,
        origem=p.name,
    )
