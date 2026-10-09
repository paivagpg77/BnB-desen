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
from dataclasses import dataclass, field, replace
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
# Quanto tempo um modelo fica fora da fila depois de falhar. Cota costuma
# voltar em um minuto; modelo recusado (inexistente, chave invalida) nao volta
# sozinho, e insistir so gasta requisicao.
ESPERA_APOS_LIMITE_S = 60.0
ESPERA_APOS_RECUSA_S = 600.0

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
    # O modelo recebeu a versao reduzida da mensagem, por limite de tamanho.
    mensagem_reduzida: bool = False


@dataclass(frozen=True)
class Provedor:
    """Um servico com API de chat no formato OpenAI."""

    nome: str
    url: str
    variavel_chave: str
    variavel_modelo: str
    modelo_padrao: str
    # Maior mensagem (sistema + usuario, em caracteres) que a camada gratuita
    # aceita em uma chamada. None = sem limite pratico para este projeto.
    limite_caracteres: Optional[int] = None
    # Pede a resposta em JSON valido quando a chamada nao traz esquema. Para
    # modelo que, sem isso, as vezes devolve JSON quebrado.
    modo_json: bool = False
    # Parametros a mais no corpo de toda chamada a este provedor.
    parametros: dict = field(default_factory=dict)


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
    "gemini-3.8-flash",
)
GROQ = Provedor(
    "groq",
    "https://api.groq.com/openai/v1/chat/completions",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "openai/gpt-oss-120b",
    # 8 mil tokens por minuto, somando a entrada e o teto da resposta. Com 19 mil
    # caracteres a entrada fica perto de 5 mil tokens e sobra espaco para a resposta.
    limite_caracteres=19000,
    modo_json=True,
    # Sem isso o raciocinio do modelo consome o teto padrao de 2 mil tokens e a
    # resposta chega cortada, com o JSON pela metade.
    parametros={"reasoning_effort": "low", "max_completion_tokens": 2700},
)
PROVEDORES = {p.nome: p for p in (OPENROUTER, GEMINI, GROQ)}


class ClienteLLM(Protocol):
    def completar(
        self, sistema: str, usuario: str, esquema: Optional[dict] = None
    ) -> RespostaLLM: ...


def modelos_do_provedor(provedor: Provedor) -> list[str]:
    """Modelos do provedor, na ordem do .env. Varios separados por virgula sao reservas."""
    carregar_env()
    nomes = [m.strip() for m in os.environ.get(provedor.variavel_modelo, "").split(",")]
    return [m for m in nomes if m] or [provedor.modelo_padrao]


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
        self.modelo = modelo or modelos_do_provedor(provedor)[0]
        self.limite_caracteres = provedor.limite_caracteres
        self._modo_json = provedor.modo_json
        self._parametros = dict(provedor.parametros)
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
        corpo.update(self._parametros)
        if self.raciocinio:
            corpo["reasoning"] = {"effort": self.raciocinio}
        if esquema is not None:
            corpo["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "resposta", "strict": True, "schema": esquema},
            }
        elif self._modo_json:
            corpo["response_format"] = {"type": "json_object"}

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


def clientes_do_provedor(nome: str) -> list[ClienteChat]:
    """Um cliente por modelo configurado; lista vazia quando a chave nao esta no .env."""
    carregar_env()
    provedor = PROVEDORES[nome]
    if not os.environ.get(provedor.variavel_chave):
        return []
    return [ClienteChat(provedor, modelo=modelo) for modelo in modelos_do_provedor(provedor)]


def cliente_do_provedor(nome: str) -> Optional[ClienteChat]:
    """Cliente do provedor, ou None quando a chave dele nao esta no .env."""
    clientes = clientes_do_provedor(nome)
    return clientes[0] if clientes else None


# (provedor, modelo) -> instante em que volta a ser tentado. Vale para o
# processo inteiro: um papel nao insiste no modelo que outro acabou de esgotar.
_FORA_DA_FILA: dict[tuple[str, str], float] = {}


class ClienteComReserva:
    """
    Fila de modelos para um mesmo papel. Quando o primeiro esta sem cota ou
    falha, a mesma pergunta vai para o seguinte. Quem falhou sai da fila por um
    tempo, para as proximas chamadas nao perderem tempo com ele.

    `trocas` guarda, em ordem, cada modelo que deixou de responder e por que.
    """

    def __init__(
        self,
        clientes: list[ClienteLLM],
        rodadas_de_espera: int = 0,
        relogio: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
        fora_da_fila: Optional[dict[tuple[str, str], float]] = None,
    ):
        if not clientes:
            raise ErroLLM("Nenhum modelo configurado para este papel.")
        self._clientes = list(clientes)
        # Com a fila toda sem cota, quantas vezes esperar a cota voltar antes de desistir.
        self._rodadas_de_espera = rodadas_de_espera
        self._relogio = relogio
        self._dormir = dormir
        self._fora = _FORA_DA_FILA if fora_da_fila is None else fora_da_fila
        self.provedor = getattr(clientes[0], "provedor", "") or ""
        self.modelo = getattr(clientes[0], "modelo", "") or ""
        self.trocas: list[str] = []

    # Aceita uma segunda versao da mensagem, menor, para modelo com limite de tamanho.
    aceita_reduzida = True

    @staticmethod
    def _chave(cliente: ClienteLLM) -> tuple[str, str]:
        return getattr(cliente, "provedor", "") or "", getattr(cliente, "modelo", "") or ""

    def completar(
        self,
        sistema: str,
        usuario: str,
        esquema: Optional[dict] = None,
        reduzida: Optional[tuple[str, str]] = None,
    ) -> RespostaLLM:
        """`reduzida` e o par (sistema, usuario) em versao menor, para modelo com limite."""
        ultimo_erro: Optional[ErroLLM] = None
        for rodada in range(self._rodadas_de_espera + 1):
            for cliente in self._clientes:
                chave = self._chave(cliente)
                if self._fora.get(chave, 0.0) > self._relogio():
                    continue
                nome = f"{chave[0]} ({chave[1]})"
                limite = getattr(cliente, "limite_caracteres", None)
                envio = (sistema, usuario)
                if limite and len(sistema) + len(usuario) > limite:
                    if reduzida is None or sum(map(len, reduzida)) > limite:
                        self.trocas.append(f"{nome} não aceita mensagem deste tamanho")
                        ultimo_erro = ultimo_erro or ErroLLM(
                            f"A mensagem passa do limite de tamanho de {nome}."
                        )
                        continue
                    envio = reduzida
                try:
                    resposta = cliente.completar(envio[0], envio[1], esquema)
                    return replace(resposta, mensagem_reduzida=envio is reduzida)
                except LimiteDeUso as erro:
                    self._fora[chave] = self._relogio() + ESPERA_APOS_LIMITE_S
                    self.trocas.append(f"{nome} está sem cota")
                    ultimo_erro = erro
                except ErroDeConexao as erro:
                    # Problema de rede, nao do modelo: ele continua na fila.
                    self.trocas.append(f"{nome} não respondeu por falha de conexão")
                    ultimo_erro = erro
                except ErroLLM as erro:
                    self._fora[chave] = self._relogio() + ESPERA_APOS_RECUSA_S
                    self.trocas.append(f"{nome} recusou a chamada: {str(erro)[:120]}")
                    ultimo_erro = erro
            if rodada == self._rodadas_de_espera:
                break
            agora = self._relogio()
            esperas = [
                volta - agora
                for c in self._clientes
                if (volta := self._fora.get(self._chave(c), 0.0)) > agora
            ]
            # So vale esperar por cota; modelo recusado nao volta em um minuto.
            if not esperas or min(esperas) > ESPERA_APOS_LIMITE_S:
                break
            self._dormir(min(esperas) + 1.0)

        nomes = ", ".join(f"{p} ({m})" for p, m in map(self._chave, self._clientes))
        if ultimo_erro is None or isinstance(ultimo_erro, LimiteDeUso):
            raise LimiteDeUso(f"Todos os modelos da fila estão sem cota no momento: {nomes}.")
        raise ultimo_erro
