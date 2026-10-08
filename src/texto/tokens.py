"""Normalizacao de texto em portugues para busca e verificacao lexical."""

from __future__ import annotations

import re
import unicodedata

STOPWORDS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "na", "no",
    "nas", "nos", "um", "uma", "uns", "umas", "que", "por", "para", "com", "se",
    "ao", "aos", "as", "sua", "seu", "suas", "seus", "ou", "mas", "como", "foi",
    "ser", "sao", "nao", "ja", "mais", "menos", "ha", "tem", "ter",
}


def remover_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def tokenizar(texto: str) -> list[str]:
    """Minusculas, sem acentos, sem stopwords e sem tokens de uma letra."""
    limpo = remover_acentos(texto.lower())
    return [
        palavra
        for palavra in re.findall(r"[a-z0-9]+", limpo)
        if len(palavra) >= 2 and palavra not in STOPWORDS
    ]
