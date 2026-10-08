"""Percorre a tela do analista de ponta a ponta com um modelo falso."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from src.llm import cliente as llm  # noqa: E402
from tests.unit.proposta_exemplo import ClienteFalso, proposta  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
PACOTE = RAIZ / "dados" / "fixtures" / "pacote_exemplo"
MOTIVO = "O protocolo compara duas versões com critério prévio."


@pytest.fixture
def tela(monkeypatch, tmp_path):
    monkeypatch.setenv("LEI_DO_BEM_PACOTE", str(PACOTE))
    monkeypatch.setattr(llm, "cliente_padrao", lambda: ClienteFalso(proposta()))
    app = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=30)
    app.run()
    return app


def _clicar(app, rotulo):
    next(b for b in app.button if b.label == rotulo).click().run()
    assert not app.exception


def _decidir(app, acao="Aceitar", motivo=""):
    app.radio[0].set_value(acao)
    if motivo:
        app.text_area[-1].set_value(motivo)
    _clicar(app, "Registrar decisão")


def test_sem_pacote_configurado_a_tela_explica(monkeypatch):
    monkeypatch.delenv("LEI_DO_BEM_PACOTE", raising=False)
    app = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=30).run()
    assert "LEI_DO_BEM_PACOTE" in app.error[0].value


def test_decisao_exige_identificacao_do_analista(tela):
    _clicar(tela, "Analisar projeto")
    assert not tela.exception
    assert "D1" in tela.subheader[-1].value
    assert len(tela.radio) == 0
    assert any("identificação" in i.value for i in tela.info)


def test_fluxo_completo_gera_o_dossie(tela):
    tela.sidebar.text_input[0].set_value("ANL-01")
    _clicar(tela, "Analisar projeto")
    assert not tela.exception
    assert any("conferem com as medições" in s.value for s in tela.success)

    # Alterar sem motivo e recusado e o ponto continua pendente.
    _decidir(tela, "Alterar")
    assert any("20 caracteres" in e.value for e in tela.error)
    assert "D1" in tela.subheader[-1].value

    for _ in range(8):          # D1, cinco criterios, D3 e D4
        _decidir(tela)
    assert "D5" in tela.subheader[-1].value
    assert any("Não elegível" in m.value for m in tela.markdown)
    _decidir(tela)

    assert tela.subheader[-1].value == "Dossiê"
    dossie = (RAIZ / "saida" / "dossie_PRJ99.md").read_text(encoding="utf-8")
    assert "Valor final: **Não elegível**" in dossie
    assert "- Analista: ANL-01" in dossie


def test_rejeicao_pede_nova_proposta(tela):
    tela.sidebar.text_input[0].set_value("ANL-01")
    _clicar(tela, "Analisar projeto")
    _decidir(tela, "Rejeitar", MOTIVO)
    assert any("rejeitou a proposta" in w.value for w in tela.warning)
    _clicar(tela, "Pedir nova proposta")
    assert len(tela.radio) == 1
