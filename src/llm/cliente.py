"""
Acesso ao modelo de linguagem, isolado atras de uma interface.

O provedor e o modelo sao configuracao, nao codigo: trocar de modelo nao muda o
motor. Toda resposta carrega o identificador do modelo que a produziu, para o
dossie registrar a origem de cada proposta.

Uso permitido apenas com a massa ficticia do hackathon. Dados reais nao vao
para servico publico.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from src.config import carregar_env

URL_OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
VARIAVEL_CHAVE = "OPENROUTER_API_KEY"
VARIAVEL_MODELO = "OPENROUTER_MODEL"
# Gratuito, para testes. Sujeito a limite diario de requisicoes.
MODELO_PADRAO = "nvidia/nemotron-3-super-120b-a12b:free"
TEMPO_LIMITE_S = 180

# (url, cabecalhos, corpo) -> (status HTTP, corpo da resposta)
Transporte = Callable[[str, dict[str, str], bytes], tuple[int, bytes]]


class ErroLLM(RuntimeError):
    pass


class LimiteDeUso(ErroLLM):
    """HTTP 429: cota do provedor, nao um resultado de analise."""


@dataclass(frozen=True)
class RespostaLLM:
    texto: str
    modelo: str                 # modelo que de fato respondeu
    uso: dict = field(default_factory=dict)


class ClienteLLM(Protocol):
    def completar(
        self, sistema: str, usuario: str, esquema: Optional[dict] = None
    ) -> RespostaLLM: ...


def _transporte_http(url: str, cabecalhos: dict[str, str], corpo: bytes) -> tuple[int, bytes]:
    requisicao = urllib.request.Request(url, data=corpo, headers=cabecalhos, method="POST")
    try:
        with urllib.request.urlopen(requisicao, timeout=TEMPO_LIMITE_S) as resposta:
            return resposta.status, resposta.read()
    except urllib.error.HTTPError as erro:
        return erro.code, erro.read()
    except urllib.error.URLError as erro:
        raise ErroLLM(f"Falha de conexao com o provedor: {erro.reason}") from erro


class ClienteOpenRouter:
    def __init__(
        self,
        chave: Optional[str] = None,
        modelo: Optional[str] = None,
        transporte: Transporte = _transporte_http,
    ):
        carregar_env()
        self._chave = chave or os.environ.get(VARIAVEL_CHAVE)
        if not self._chave:
            raise ErroLLM(f"Defina {VARIAVEL_CHAVE} no arquivo .env com a chave do OpenRouter.")
        self.modelo = modelo or os.environ.get(VARIAVEL_MODELO) or MODELO_PADRAO
        self._transporte = transporte

    def completar(
        self, sistema: str, usuario: str, esquema: Optional[dict] = None
    ) -> RespostaLLM:
        corpo: dict = {
            "model": self.modelo,
            "messages": [
                {"role": "system", "content": sistema},
                {"role": "user", "content": usuario},
            ],
        }
        if esquema is not None:
            corpo["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "resposta", "strict": True, "schema": esquema},
            }

        status, bruto = self._transporte(
            URL_OPENROUTER,
            {
                "Authorization": f"Bearer {self._chave}",
                "Content-Type": "application/json",
            },
            json.dumps(corpo).encode("utf-8"),
        )
        if status == 429:
            raise LimiteDeUso(f"Limite de uso do modelo {self.modelo} atingido.")
        if status != 200:
            raise ErroLLM(f"Provedor respondeu HTTP {status}: {bruto[:300]!r}")

        try:
            dados = json.loads(bruto)
        except json.JSONDecodeError as erro:
            raise ErroLLM("Resposta do provedor nao e JSON valido.") from erro
        # O OpenRouter pode devolver erro do modelo dentro de um HTTP 200.
        if "error" in dados:
            raise ErroLLM(f"Erro do provedor: {dados['error']}")
        try:
            texto = dados["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as erro:
            raise ErroLLM("Resposta do provedor sem conteudo.") from erro
        if not texto:
            raise ErroLLM("Resposta do provedor vazia.")
        return RespostaLLM(
            texto=texto,
            modelo=dados.get("model", self.modelo),
            uso=dados.get("usage", {}),
        )
