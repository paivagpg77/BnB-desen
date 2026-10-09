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


@pytest.fixture
def tela(monkeypatch, tmp_path):
    monkeypatch.setenv("LEI_DO_BEM_PACOTE", str(PACOTE))
    # Analises, logs e dossies do teste ficam fora da pasta saida/ do projeto.
    monkeypatch.setenv("LEI_DO_BEM_SAIDA", str(tmp_path))
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


def test_fluxo_completo_gera_o_dossie(tela, tmp_path):
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
    dossie = (tmp_path / "dossie_PRJ99.md").read_text(encoding="utf-8")
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


def test_analise_salva_volta_com_as_decisoes_ja_registradas(tela):
    tela.sidebar.text_input[0].set_value("ANL-01")
    _clicar(tela, "Analisar projeto")
    _decidir(tela)
    _decidir(tela, "Alterar", MOTIVO)
    assert "Criatividade" in tela.subheader[-1].value

    # Outra sessao do navegador: nada do que esta na tela e reaproveitado.
    outra = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=30).run()
    outra.sidebar.text_input[0].set_value("ANL-01")
    _clicar(outra, "Abrir análise salva")
    assert "Criatividade" in outra.subheader[-1].value
    assert any("ANL-01 alterou" in m.value for m in outra.markdown)


def test_ponto_decidido_pode_ser_revisto(tela):
    tela.sidebar.text_input[0].set_value("ANL-01")
    _clicar(tela, "Analisar projeto")
    _decidir(tela)
    assert "Novidade" in tela.subheader[-1].value
    _clicar(tela, "Rever este ponto")
    assert "D1" in tela.subheader[-1].value
    assert len(tela.radio) == 1


def _abrir_revisao(app, analista):
    app.sidebar.text_input[0].set_value(analista)
    app.sidebar.selectbox[0].set_value("Discordâncias e revisão cega").run()
    assert not app.exception


def test_discordancia_passa_por_revisao_cega_de_outro_analista(tela):
    tela.sidebar.text_input[0].set_value("ANL-01")
    _clicar(tela, "Analisar projeto")
    _decidir(tela)
    _decidir(tela, "Alterar", MOTIVO)        # novidade: INDETERMINADA no lugar da proposta

    # Quem abriu a discordancia nao a revisa.
    _abrir_revisao(tela, "ANL-01")
    assert {m.label: m.value for m in tela.metric}["Aguardando revisão cega"] == "1"
    assert len(tela.radio) == 0

    # O segundo analista ve a proposta da IA, nao a decisao do primeiro.
    _abrir_revisao(tela, "ANL-02")
    textos = " ".join(m.value for m in tela.markdown) + " ".join(c.value for c in tela.caption)
    assert "Novidade" in textos
    assert "NÃO DEMONSTRADA" in textos
    assert MOTIVO not in textos and "INDETERMINADA" not in textos and "ANL-01" not in textos

    _clicar(tela, "Registrar revisão")
    assert any("20 caracteres" in e.value for e in tela.error)
    tela.radio[0].set_value("Discordo da proposta da IA")
    tela.text_area[0].set_value(MOTIVO)
    _clicar(tela, "Registrar revisão")
    metricas = {m.label: m.value for m in tela.metric}
    assert metricas["Aguardando revisão cega"] == "0"
    assert metricas["Confirmadas contra a IA"] == "1"
    assert metricas["Taxa de convergência contra a IA"] == "100%"
    assert metricas["Concordância entre analistas"] == "100%"
    assert len(tela.radio) == 0


def test_revisor_com_outro_valor_abre_divergencia_entre_analistas(tela):
    tela.sidebar.text_input[0].set_value("ANL-01")
    _clicar(tela, "Analisar projeto")
    _decidir(tela)
    _decidir(tela, "Alterar", MOTIVO)        # novidade: primeira opção da lista no lugar da proposta

    _abrir_revisao(tela, "ANL-02")
    assert {m.label: m.value for m in tela.metric}["Taxa de convergência contra a IA"] == "0%"
    # A lista nao traz a proposta da IA nem destaca a escolha do primeiro analista.
    valor = next(s for s in tela.selectbox if s.label.startswith("Valor que você daria"))
    assert valor.value is None
    assert "NÃO DEMONSTRADA" not in valor.options
    tela.radio[0].set_value("Discordo da proposta da IA")
    valor.set_value("INDETERMINADA")
    tela.text_area[0].set_value(MOTIVO)
    _clicar(tela, "Registrar revisão")

    metricas = {m.label: m.value for m in tela.metric}
    assert metricas["Divergência entre analistas"] == "1"
    assert metricas["Confirmadas contra a IA"] == "0"
    assert metricas["Concordância entre analistas"] == "0%"
