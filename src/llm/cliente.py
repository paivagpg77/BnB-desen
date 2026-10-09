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
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from src.config import carregar_env

URL_OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
VARIAVEL_CHAVE = "OPENROUTER_API_KEY"
VARIAVEL_MODELO = "OPENROUTER_MODEL"
# low, medium ou high. Em modelos que raciocinam antes de responder, a maior
# parte do tempo de resposta vem dai. Vazio = padrao do modelo.
VARIAVEL_RACIOCINIO = "OPENROUTER_RACIOCINIO"
# Gratuito, para testes. Sujeito a limite diario de requisicoes.
MODELO_PADRAO = "nvidia/nemotron-3-super-120b-a12b:free"
TEMPO_LIMITE_S = 180
TENTATIVAS_DE_CONEXAO = 3
ESPERA_ENTRE_TENTATIVAS_S = 2.0
STATUS_TRANSITORIOS = (502, 503, 504)

# (url, cabecalhos, corpo) -> (status HTTP, corpo da resposta)
Transporte = Callable[[str, dict[str, str], bytes], tuple[int, bytes]]


class ErroLLM(RuntimeError):
    pass


class ErroDeConexao(ErroLLM):
    """A rede caiu antes de a resposta chegar inteira; vale tentar de novo."""


class LimiteDeUso(ErroLLM):
    """HTTP 429: cota do provedor, nao um resultado de analise."""


@dataclass(frozen=True)
class RespostaLLM:
    texto: str
    modelo: str                 # modelo que de fato respondeu
    uso: dict = field(default_factory=dict)
    provedor: str = ""


@dataclass(frozen=True)
class Provedor:
    """Um servico com API de chat no formato OpenAI."""

    nome: str
    url: str
    variavel_chave: str
    variavel_modelo: str
    modelo_padrao: str


# Os tres provedores tem camada gratuita. Os modelos padrao sao trocaveis pelo
# .env; a disponibilidade gratuita de cada um muda com o tempo.
OPENROUTER = Provedor(
    "openrouter", URL_OPENROUTER, VARIAVEL_CHAVE, VARIAVEL_MODELO, MODELO_PADRAO
)
GEMINI = Provedor(
    "gemini",
    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "gemini-3.6-flash",
)
GROQ = Provedor(
    "groq",
    "https://api.groq.com/openai/v1/chat/completions",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "openai/gpt-oss-120b",
)
PROVEDORES = {p.nome: p for p in (OPENROUTER, GEMINI, GROQ)}


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
        raise ErroDeConexao(f"Falha de conexao com o provedor: {erro.reason}") from erro
    except OSError as erro:
        # Conexao derrubada ou tempo esgotado durante a leitura da resposta.
        raise ErroDeConexao(f"Conexao com o provedor interrompida: {erro}") from erro


class ClienteChat:
    """Cliente de qualquer provedor com API de chat no formato OpenAI."""

    def __init__(
        self,
        provedor: Provedor,
        chave: Optional[str] = None,
        modelo: Optional[str] = None,
        transporte: Transporte = _transporte_http,
        espera: float = ESPERA_ENTRE_TENTATIVAS_S,
        raciocinio: Optional[str] = None,
    ):
        carregar_env()
        self.provedor = provedor.nome
        self._url = provedor.url
        self._chave = chave or os.environ.get(provedor.variavel_chave)
        if not self._chave:
            raise ErroLLM(
                f"Defina {provedor.variavel_chave} no arquivo .env com a chave do {provedor.nome}."
            )
        self.modelo = modelo or os.environ.get(provedor.variavel_modelo) or provedor.modelo_padrao
        # O esforco de raciocinio e um parametro do OpenRouter.
        self.raciocinio = ""
        if provedor.nome == OPENROUTER.nome:
            self.raciocinio = (
                raciocinio if raciocinio is not None else os.environ.get(VARIAVEL_RACIOCINIO, "")
            ).strip().lower()
        self._transporte = transporte
        self._espera = espera

    def _enviar(self, cabecalhos: dict[str, str], corpo: bytes) -> tuple[int, bytes]:
        for tentativa in range(1, TENTATIVAS_DE_CONEXAO + 1):
            ultima = tentativa == TENTATIVAS_DE_CONEXAO
            try:
                status, bruto = self._transporte(self._url, cabecalhos, corpo)
            except ErroDeConexao:
                if ultima:
                    raise
            else:
                # Sobrecarga momentanea do provedor: vale tentar de novo.
                if status not in STATUS_TRANSITORIOS or ultima:
                    return status, bruto
            time.sleep(self._espera * tentativa)
        raise AssertionError("inalcancavel")

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
        if self.raciocinio:
            corpo["reasoning"] = {"effort": self.raciocinio}
        if esquema is not None:
            corpo["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "resposta", "strict": True, "schema": esquema},
            }

        status, bruto = self._enviar(
            {
                "Authorization": f"Bearer {self._chave}",
                "Content-Type": "application/json",
                # Sem identificacao, o Groq recusa a requisicao (HTTP 403, codigo 1010).
                "User-Agent": "lei-do-bem-analise/0.1",
            },
            json.dumps(corpo).encode("utf-8"),
        )
        if status == 429:
            raise LimiteDeUso(f"Limite de uso do modelo {self.modelo} ({self.provedor}) atingido.")
        if status != 200:
            raise ErroLLM(f"{self.provedor} respondeu HTTP {status}: {bruto[:300]!r}")

        try:
            dados = json.loads(bruto)
        except json.JSONDecodeError as erro:
            raise ErroLLM(f"Resposta do {self.provedor} nao e JSON valido.") from erro
        # Alguns provedores devolvem erro do modelo dentro de um HTTP 200.
        if not isinstance(dados, dict) or "error" in dados:
            raise ErroLLM(f"Erro do {self.provedor}: {dados.get('error') if isinstance(dados, dict) else dados}")
        try:
            texto = dados["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as erro:
            raise ErroLLM(f"Resposta do {self.provedor} sem conteudo.") from erro
        if not texto:
            raise ErroLLM(f"Resposta do {self.provedor} vazia.")
        return RespostaLLM(
            texto=texto,
            modelo=dados.get("model") or self.modelo,
            uso=dados.get("usage") or {},
            provedor=self.provedor,
        )


class ClienteOpenRouter(ClienteChat):
    def __init__(self, chave=None, modelo=None, transporte=_transporte_http,
                 espera=ESPERA_ENTRE_TENTATIVAS_S, raciocinio=None):
        super().__init__(OPENROUTER, chave, modelo, transporte, espera, raciocinio)


def cliente_padrao() -> ClienteLLM:
    """Cliente do OpenRouter configurado pelo .env."""
    return ClienteOpenRouter()


def cliente_do_provedor(nome: str) -> Optional[ClienteChat]:
    """Cliente do provedor, ou None quando a chave dele nao esta no .env."""
    carregar_env()
    provedor = PROVEDORES[nome]
    if not os.environ.get(provedor.variavel_chave):
        return None
    return ClienteChat(provedor)
