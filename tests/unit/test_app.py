"""Percorre a tela do analista de ponta a ponta com um modelo falso."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from src.motor import orquestrador  # noqa: E402
from tests.unit.proposta_exemplo import ClienteFalso, proposta  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
PACOTE = RAIZ / "dados" / "fixtures" / "pacote_exemplo"
MOTIVO = "O protocolo compara duas versões com critério prévio."
MOTIVO_DO_REVISOR = "A referência anterior não cobria os dois cenários."


@pytest.fixture
def tela(monkeypatch, tmp_path):
    monkeypatch.setenv("LEI_DO_BEM_PACOTE", str(PACOTE))
    # As discordancias dos testes nao podem virar precedente na tela de verdade.
    monkeypatch.setenv("LEI_DO_BEM_DISCORDANCIAS", str(tmp_path / "eventos.jsonl"))
    monkeypatch.setattr(
        orquestrador, "papeis_padrao", lambda: orquestrador.Papeis(analista=ClienteFalso(proposta()))
    )
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
    metricas = {m.label: m.value for m in tela.metric}
    assert metricas["Resultados conferidos"] == "5"
    assert metricas["Com problema"] == "0"
    assert metricas["Fontes do modelo descartadas"] == "2"
    textos = " ".join(m.value for m in tela.markdown)
    assert "33 de 40 casos (82,5%)" in textos
    assert ":green-badge[Confere]" in textos

    # Alterar sem motivo e recusado e o ponto continua pendente.
    _decidir(tela, "Alterar")
    assert any("20 caracteres" in e.value for e in tela.error)
    assert "D1" in tela.subheader[-1].value

    for _ in range(8):          # D1, cinco criterios, D3 e D4
        _decidir(tela)
    assert "D5" in tela.subheader[-1].value
    assert any("Não elegível, porque novidade, criatividade e incerteza" in m.value for m in tela.markdown)
    assert any("ANL-01 aceitou a proposta da IA." in m.value for m in tela.markdown)
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


def test_analise_salva_pode_ser_reaberta_sem_chamar_o_modelo(tela, monkeypatch):
    tela.sidebar.text_input[0].set_value("ANL-01")
    _clicar(tela, "Analisar projeto")

    def sem_modelo():
        raise AssertionError("o modelo não deveria ser chamado")

    monkeypatch.setattr(orquestrador, "papeis_padrao", sem_modelo)
    _clicar(tela, "Abrir análise salva")
    assert "D1" in tela.subheader[-1].value
    assert len(tela.radio) == 1


def _textos(app):
    elementos = [*app.markdown, *app.caption, *app.info, *app.warning, *app.success, *app.error]
    return " ".join(e.value for e in elementos)


def test_discordancia_passa_pela_revisao_cega_e_vira_precedente(tela):
    tela.sidebar.text_input[0].set_value("ANL-01")
    _clicar(tela, "Analisar projeto")
    _decidir(tela)                                      # D1
    _decidir(tela, "Alterar", MOTIVO)                   # D2 novidade: discorda da IA
    assert "DSC-0001 · Aguardando revisão cega" in _textos(tela)

    # Quem abriu a discordancia nao a revisa.
    tela.selectbox(key="modo").set_value("Revisão cega").run()
    assert any("Nenhuma discordância" in i.value for i in tela.info)

    # O segundo analista ve a proposta e as fontes, nao a decisao do primeiro.
    tela.sidebar.text_input[0].set_value("ANL-02").run()
    assert not tela.exception
    assert tela.subheader[-1].value == "PRJ99 · D2 · Novidade"
    assert "Valor proposto pela IA: NÃO DEMONSTRADA" in _textos(tela)
    assert MOTIVO not in _textos(tela)
    assert "ANL-01" not in _textos(tela)

    tela.radio[0].set_value("Discordo da proposta da IA")
    _clicar(tela, "Registrar revisão")
    assert any("20 caracteres" in e.value for e in tela.error)
    tela.radio[0].set_value("Discordo da proposta da IA")
    tela.text_area[-1].set_value(MOTIVO_DO_REVISOR)
    _clicar(tela, "Registrar revisão")
    assert any("Convergência contra a IA" in s.value for s in tela.success)
    assert MOTIVO in _textos(tela)                      # so agora a primeira decisao aparece
    assert any("Nenhuma discordância" in i.value for i in tela.info)

    # O precedente aparece no cartao do mesmo criterio e nao muda a proposta.
    tela.selectbox(key="modo").set_value("Análise do projeto").run()
    _clicar(tela, "Abrir análise salva")
    assert not any("Precedentes internos" in e.label for e in tela.expander)   # D1 nao tem
    _decidir(tela)
    assert any(
        e.label == "Precedentes internos (não normativos): 1 caso(s)" for e in tela.expander
    )
    assert "Valor proposto pela IA: NÃO DEMONSTRADA" in _textos(tela)

    tela.selectbox(key="modo").set_value("Discordâncias e precedentes").run()
    assert not tela.exception
    metricas = {m.label: m.value for m in tela.metric}
    assert metricas["Discordâncias registradas"] == "1"
    assert metricas["Convergência contra a IA"] == "1"
    assert "Nenhum padrão candidato" in _textos(tela)


def test_painel_nao_mostra_discordancia_que_aguarda_revisao(tela):
    tela.sidebar.text_input[0].set_value("ANL-01")
    _clicar(tela, "Analisar projeto")
    _decidir(tela, "Rejeitar", MOTIVO)
    tela.selectbox(key="modo").set_value("Discordâncias e precedentes").run()
    assert not tela.exception
    assert {m.label: m.value for m in tela.metric}["Aguardando revisão cega"] == "1"
    assert "Nenhuma discordância revisada" in _textos(tela)
    assert len(tela.dataframe) == 0
