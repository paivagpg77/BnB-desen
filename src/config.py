"""
Configuracao local a partir do arquivo .env na raiz do projeto.

O .env guarda a chave do modelo de linguagem e o caminho da massa do hackathon.
Ele nunca e versionado; o modelo sem valores esta em .env.example.

Variavel ja definida no ambiente tem prioridade sobre o arquivo. Linha com
valor vazio e ignorada, para que um campo em branco nao conte como definido.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

ARQUIVO_ENV = Path(__file__).resolve().parents[1] / ".env"

_carregado = False


def ler_env(caminho: Path) -> dict[str, str]:
    valores: dict[str, str] = {}
    if not caminho.is_file():
        return valores
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.removeprefix("export ").partition("=")
        chave, valor = chave.strip(), valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        if chave and valor:
            valores[chave] = valor
    return valores


def carregar_env(caminho: Optional[Path] = None, forcar: bool = False) -> list[str]:
    """
    Carrega o .env uma vez por processo. Devolve as variaveis que definiu.
    """
    global _carregado
    if _carregado and not forcar:
        return []
    _carregado = True
    definidas = []
    for chave, valor in ler_env(caminho or ARQUIVO_ENV).items():
        if chave not in os.environ:
            os.environ[chave] = valor
            definidas.append(chave)
    return definidas
