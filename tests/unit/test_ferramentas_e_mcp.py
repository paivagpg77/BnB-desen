import asyncio
from pathlib import Path

import pytest

from src import ferramentas
from src.pacote.carregador import PacoteInvalido

PACOTE = Path(__file__).resolve().parents[2] / "dados" / "fixtures" / "pacote_exemplo"


@pytest.fixture(autouse=True)
def pacote_de_exemplo(monkeypatch):
    monkeypatch.setenv("LEI_DO_BEM_PACOTE", str(PACOTE))


def test_lista_e_resume_projetos():
    assert ferramentas.listar_projetos() == [{"projeto_id": "PRJ99", "grupo": "caso para análise"}]
    resumo = ferramentas.resumo_do_projeto("prj99")
    assert resumo["versoes"] == ["filtro-v1", "filtro-v2"]
    assert resumo["arquivos_ausentes"] == ["dossie_projeto.pdf", "transcricao_entrevista_tecnica.pdf"]
    assert resumo["so_contagem_de_entrega"] is False


def test_busca_devolve_trecho_com_identificador_e_natureza():
    achados = ferramentas.buscar_evidencias("PRJ99", "janela de descarte", k=3)
    assert achados[0]["trecho_id"] == "evidencias/metodo.md#2"
    assert achados[0]["natureza"] == "especificação"
    assert ferramentas.buscar_evidencias("PRJ99", "zzz inexistente") == []


def test_le_referencia_e_diz_quando_nao_existe():
    lida = ferramentas.ler_referencia("PRJ99", "evidencias/medicoes.csv#PRJ99-S03")
    assert lida["existe"] and lida["trecho_id"] == "PRJ99-S03"
    assert "frequência 2" in lida["texto"]
    ausente = ferramentas.ler_referencia("PRJ99", "PRJ99-EV01")
    assert ausente["existe"] is False and ausente["texto"] == ""


def test_conferencia_e_regras():
    assert {c["situacao"] for c in ferramentas.conferir_resultados("PRJ99")} == {
        "confere", "transcricao_confere"
    }
    assert ferramentas.buscar_regras("contagem de entrega desempenho", k=1)[0]["secao"] == (
        "Tratamento das evidências"
    )


def test_projeto_inexistente_e_pacote_sem_historicos_dao_erro_claro():
    with pytest.raises(ferramentas.ProjetoDesconhecido, match="PRJ01"):
        ferramentas.resumo_do_projeto("PRJ01")
    with pytest.raises(ferramentas.ProjetoDesconhecido, match="históricos"):
        ferramentas.parecer_historico("PRJ01")


def test_sem_pacote_configurado_o_erro_cita_o_env(monkeypatch):
    monkeypatch.delenv("LEI_DO_BEM_PACOTE")
    with pytest.raises(PacoteInvalido, match=".env"):
        ferramentas.listar_projetos()


def test_servidor_mcp_expoe_as_ferramentas_e_responde():
    pytest.importorskip("mcp")
    from src.mcp_servidor import servidor

    nomes = {t.name for t in asyncio.run(servidor.list_tools())}
    assert nomes == {
        "listar_projetos", "resumo_do_projeto", "buscar_evidencias", "ler_referencia",
        "conferir_resultados", "buscar_regras", "parecer_historico",
    }
    resultado = asyncio.run(
        servidor.call_tool("buscar_evidencias", {"projeto_id": "PRJ99", "consulta": "janela de descarte", "k": 1})
    )
    assert resultado.is_error is False
    assert resultado.structured_content["result"][0]["trecho_id"] == "evidencias/metodo.md#2"
