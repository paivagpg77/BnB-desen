"""
Divisao de documentos em trechos por unidade logica.

Criterios de divisao, em ordem:
1. Cabecalhos markdown (#, ##, ###) abrem uma nova secao.
2. Linhas que comecam com "Art. N" (padrao de norma) abrem uma nova secao.
3. Secoes longas sao quebradas por paragrafo, respeitando o tamanho maximo.

Cada trecho recebe um trecho_id estavel: "<doc_id>#<numero com 3 digitos>".
"""

from __future__ import annotations

import re

from src.documentos.modelos import Documento, Trecho

TAMANHO_MAXIMO_PADRAO = 1200

_CABECALHO = re.compile(r"^(#{1,3})\s+(.*\S)\s*$")
_ARTIGO = re.compile(r"^(Art\.\s*\d+.*)$", re.IGNORECASE)


def _quebrar_por_paragrafo(texto: str, tamanho_maximo: int) -> list[str]:
    paragrafos = [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]
    partes: list[str] = []
    atual = ""
    for paragrafo in paragrafos:
        if not atual:
            atual = paragrafo
        elif len(atual) + 2 + len(paragrafo) <= tamanho_maximo:
            atual = f"{atual}\n\n{paragrafo}"
        else:
            partes.append(atual)
            atual = paragrafo
    if atual:
        partes.append(atual)
    return partes


def dividir(documento: Documento, tamanho_maximo: int = TAMANHO_MAXIMO_PADRAO) -> list[Trecho]:
    secoes: list[tuple[str, list[str]]] = []
    titulo_atual = "inicio"
    linhas_atuais: list[str] = []

    for linha in documento.texto.splitlines():
        cabecalho = _CABECALHO.match(linha)
        artigo = _ARTIGO.match(linha.strip())
        if cabecalho or artigo:
            if any(l.strip() for l in linhas_atuais):
                secoes.append((titulo_atual, linhas_atuais))
            titulo_atual = cabecalho.group(2) if cabecalho else artigo.group(1)[:120]
            linhas_atuais = []
        else:
            linhas_atuais.append(linha)
    if any(l.strip() for l in linhas_atuais):
        secoes.append((titulo_atual, linhas_atuais))

    trechos: list[Trecho] = []
    numero = 0
    for titulo, linhas in secoes:
        corpo = "\n".join(linhas).strip()
        if not corpo:
            continue
        for parte in _quebrar_por_paragrafo(corpo, tamanho_maximo):
            numero += 1
            texto = f"{titulo}\n\n{parte}" if titulo != "inicio" else parte
            trechos.append(
                Trecho(
                    trecho_id=f"{documento.doc_id}#{numero:03d}",
                    doc_id=documento.doc_id,
                    tipo=documento.tipo,
                    projeto_id=documento.projeto_id,
                    secao=titulo,
                    texto=texto,
                    versao=documento.versao,
                )
            )
    return trechos
