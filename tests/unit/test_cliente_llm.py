import json

import pytest

from src.llm.cliente import (
    ESPERA_APOS_LIMITE_S,
    GEMINI,
    MODELO_PADRAO,
    ClienteComReserva,
    ClienteOpenRouter,
    ErroDeConexao,
    ErroLLM,
    LimiteDeUso,
    RespostaLLM,
    cliente_do_provedor,
    clientes_do_provedor,
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


def _transporte_instavel(falhas):
    chamadas = {"n": 0}

    def transporte(url, cabecalhos, dados):
        chamadas["n"] += 1
        if chamadas["n"] <= falhas:
            raise ErroDeConexao("conexao interrompida")
        return 200, json.dumps(RESPOSTA_OK).encode("utf-8")

    return transporte, chamadas


def test_queda_de_conexao_e_tentada_de_novo():
    transporte, chamadas = _transporte_instavel(falhas=2)
    cliente = ClienteOpenRouter(chave="k", transporte=transporte, espera=0)
    assert cliente.completar("s", "u").texto == '{"ok": true}'
    assert chamadas["n"] == 3


def test_conexao_que_nao_volta_vira_erro_de_conexao():
    transporte, chamadas = _transporte_instavel(falhas=99)
    cliente = ClienteOpenRouter(chave="k", transporte=transporte, espera=0)
    with pytest.raises(ErroDeConexao):
        cliente.completar("s", "u")
    assert chamadas["n"] == 3


def test_esforco_de_raciocinio_so_e_enviado_quando_configurado(monkeypatch):
    monkeypatch.delenv("OPENROUTER_RACIOCINIO", raising=False)
    capturado = {}
    ClienteOpenRouter(chave="k", transporte=_transporte_fixo(200, RESPOSTA_OK, capturado)).completar("s", "u")
    assert "reasoning" not in capturado["corpo"]
    monkeypatch.setenv("OPENROUTER_RACIOCINIO", "Low")
    ClienteOpenRouter(chave="k", transporte=_transporte_fixo(200, RESPOSTA_OK, capturado)).completar("s", "u")
    assert capturado["corpo"]["reasoning"] == {"effort": "low"}


def test_sobrecarga_do_provedor_e_tentada_de_novo():
    respostas = [(503, b"alta demanda"), (200, json.dumps(RESPOSTA_OK).encode("utf-8"))]
    chamadas = []

    def transporte(url, cabecalhos, dados):
        chamadas.append(cabecalhos)
        return respostas[len(chamadas) - 1]

    cliente = ClienteOpenRouter(chave="k", transporte=transporte, espera=0)
    assert cliente.completar("s", "u").texto == '{"ok": true}'
    assert len(chamadas) == 2
    assert chamadas[0]["User-Agent"].startswith("lei-do-bem-analise")


def test_sobrecarga_que_persiste_vira_erro():
    cliente = ClienteOpenRouter(chave="k", transporte=lambda u, c, d: (503, b"alta demanda"), espera=0)
    with pytest.raises(ErroLLM, match="HTTP 503"):
        cliente.completar("s", "u")


# ----- fila de modelos: quando um fica sem cota, o seguinte responde -----

class _Falso:
    def __init__(self, provedor, *respostas):
        self.provedor = provedor
        self.modelo = f"{provedor}/modelo"
        self._respostas = list(respostas)
        self.chamadas = 0

    def completar(self, sistema, usuario, esquema=None):
        self.chamadas += 1
        resposta = self._respostas.pop(0) if len(self._respostas) > 1 else self._respostas[0]
        if isinstance(resposta, Exception):
            raise resposta
        return RespostaLLM(texto=resposta, modelo=self.modelo, provedor=self.provedor)


class _Relogio:
    def __init__(self):
        self.agora = 0.0
        self.esperas = []

    def __call__(self):
        return self.agora

    def dormir(self, segundos):
        self.esperas.append(segundos)
        self.agora += segundos


def _fila(*clientes, rodadas=0):
    relogio = _Relogio()
    fila = ClienteComReserva(
        list(clientes), rodadas_de_espera=rodadas, relogio=relogio, dormir=relogio.dormir, fora_da_fila={}
    )
    return fila, relogio


def test_sem_cota_no_primeiro_o_segundo_responde():
    gemini, groq = _Falso("gemini", LimiteDeUso("429")), _Falso("groq", "ok")
    fila, _ = _fila(gemini, groq)
    resposta = fila.completar("s", "u")
    assert (resposta.provedor, resposta.texto) == ("groq", "ok")
    assert fila.trocas == ["gemini (gemini/modelo) está sem cota"]
    assert (fila.provedor, fila.modelo) == ("gemini", "gemini/modelo")


def test_modelo_sem_cota_sai_da_fila_e_volta_depois():
    gemini, groq = _Falso("gemini", LimiteDeUso("429"), "voltou"), _Falso("groq", "ok")
    fila, relogio = _fila(gemini, groq)
    fila.completar("s", "u")
    fila.completar("s", "u")
    assert (gemini.chamadas, groq.chamadas) == (1, 2)

    relogio.agora += ESPERA_APOS_LIMITE_S + 1
    assert fila.completar("s", "u").texto == "voltou"


def test_modelo_recusado_tambem_passa_a_vez():
    gemini = _Falso("gemini", ErroLLM("gemini respondeu HTTP 404: modelo não existe"))
    fila, relogio = _fila(gemini, _Falso("groq", "ok"))
    assert fila.completar("s", "u").provedor == "groq"
    assert "recusou a chamada" in fila.trocas[0]
    # Um minuto nao basta para voltar a tentar um modelo recusado.
    relogio.agora += ESPERA_APOS_LIMITE_S + 1
    fila.completar("s", "u")
    assert gemini.chamadas == 1


def test_falha_de_conexao_nao_tira_o_modelo_da_fila():
    gemini = _Falso("gemini", ErroDeConexao("caiu"), "ok de novo")
    fila, _ = _fila(gemini, _Falso("groq", "ok"))
    assert fila.completar("s", "u").provedor == "groq"
    assert fila.completar("s", "u").texto == "ok de novo"


def test_todos_sem_cota_vira_limite_de_uso():
    fila, relogio = _fila(_Falso("gemini", LimiteDeUso("429")), _Falso("groq", LimiteDeUso("429")))
    with pytest.raises(LimiteDeUso, match=r"gemini \(gemini/modelo\), groq \(groq/modelo\)"):
        fila.completar("s", "u")
    assert relogio.esperas == []
    # Na chamada seguinte ninguem e tentado: o erro continua sendo de cota.
    with pytest.raises(LimiteDeUso):
        fila.completar("s", "u")


def test_em_lote_espera_a_cota_voltar():
    gemini = _Falso("gemini", LimiteDeUso("429"), "voltou")
    fila, relogio = _fila(gemini, _Falso("groq", LimiteDeUso("429")), rodadas=1)
    assert fila.completar("s", "u").texto == "voltou"
    assert relogio.esperas == [ESPERA_APOS_LIMITE_S + 1.0]


def test_ultimo_erro_que_nao_e_de_cota_e_o_que_sobe():
    fila, _ = _fila(_Falso("gemini", LimiteDeUso("429")), _Falso("groq", ErroLLM("chave inválida")))
    with pytest.raises(ErroLLM, match="chave inválida"):
        fila.completar("s", "u")


def test_varios_modelos_do_mesmo_provedor_pelo_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_MODEL", "modelo-a, modelo-b")
    assert [c.modelo for c in clientes_do_provedor("gemini")] == ["modelo-a", "modelo-b"]
    assert cliente_do_provedor("gemini").modelo == "modelo-a"
    monkeypatch.delenv("GEMINI_MODEL")
    assert [c.modelo for c in clientes_do_provedor("gemini")] == [GEMINI.modelo_padrao]
    monkeypatch.delenv("GEMINI_API_KEY")
    assert clientes_do_provedor("gemini") == []
