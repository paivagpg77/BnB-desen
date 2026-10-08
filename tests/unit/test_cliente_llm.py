import json

import pytest

from src.llm.cliente import (
    MODELO_PADRAO,
    ClienteOpenRouter,
    ErroLLM,
    LimiteDeUso,
)


def _transporte_fixo(status, corpo, capturado=None):
    def transporte(url, cabecalhos, dados):
        if capturado is not None:
            capturado.update(url=url, cabecalhos=cabecalhos, corpo=json.loads(dados))
        return status, json.dumps(corpo).encode("utf-8") if isinstance(corpo, dict) else corpo
    return transporte


RESPOSTA_OK = {
    "model": "modelo/que-respondeu",
    "choices": [{"message": {"content": '{"ok": true}'}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 3},
}


def test_sem_chave_o_cliente_nao_e_criado(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ErroLLM, match="OPENROUTER_API_KEY"):
        ClienteOpenRouter()


def test_modelo_vem_do_argumento_do_ambiente_ou_do_padrao(monkeypatch):
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    assert ClienteOpenRouter(chave="k").modelo == MODELO_PADRAO
    monkeypatch.setenv("OPENROUTER_MODEL", "do/ambiente")
    assert ClienteOpenRouter(chave="k").modelo == "do/ambiente"
    assert ClienteOpenRouter(chave="k", modelo="do/argumento").modelo == "do/argumento"


def test_envia_esquema_e_devolve_o_modelo_que_respondeu():
    capturado = {}
    cliente = ClienteOpenRouter(
        chave="segredo",
        modelo="pedido/modelo",
        transporte=_transporte_fixo(200, RESPOSTA_OK, capturado),
    )
    esquema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    resposta = cliente.completar("sistema", "usuario", esquema=esquema)

    assert capturado["cabecalhos"]["Authorization"] == "Bearer segredo"
    assert capturado["corpo"]["model"] == "pedido/modelo"
    assert [m["role"] for m in capturado["corpo"]["messages"]] == ["system", "user"]
    assert capturado["corpo"]["response_format"]["json_schema"]["schema"] == esquema
    assert resposta.texto == '{"ok": true}'
    assert resposta.modelo == "modelo/que-respondeu"
    assert resposta.uso["prompt_tokens"] == 10


def test_sem_esquema_nao_envia_response_format():
    capturado = {}
    cliente = ClienteOpenRouter(chave="k", transporte=_transporte_fixo(200, RESPOSTA_OK, capturado))
    cliente.completar("s", "u")
    assert "response_format" not in capturado["corpo"]


def test_limite_de_uso_tem_erro_proprio():
    cliente = ClienteOpenRouter(chave="k", transporte=_transporte_fixo(429, {"error": "rate"}))
    with pytest.raises(LimiteDeUso):
        cliente.completar("s", "u")


@pytest.mark.parametrize(
    "status, corpo",
    [
        (500, {"error": "interno"}),
        (200, {"error": {"message": "modelo indisponivel"}}),
        (200, {"choices": []}),
        (200, {"choices": [{"message": {"content": ""}}]}),
        (200, b"<html>nao e json</html>"),
    ],
)
def test_respostas_invalidas_viram_erro_e_nunca_texto(status, corpo):
    cliente = ClienteOpenRouter(chave="k", transporte=_transporte_fixo(status, corpo))
    with pytest.raises(ErroLLM):
        cliente.completar("s", "u")
