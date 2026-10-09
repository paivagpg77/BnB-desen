from datetime import datetime

import pytest

from src.decisoes.maquina_estados import Ponto, PontoDecisao
from src.documentos.modelos import TIPO_PROJETO, Trecho
from src.dossie.gerador import DossieIncompleto, gerar_dossie

ANALISTA = "ANL-01"
MOTIVO = "A atividade A02 nao tem registro de hipotese inicial."
AGORA = datetime(2026, 10, 8, 15, 0)

TRECHO = Trecho(
    trecho_id="PRJ-TESTE-dossie#002",
    doc_id="PRJ-TESTE-dossie",
    tipo=TIPO_PROJETO,
    projeto_id="PRJ-TESTE",
    secao="Estado anterior",
    texto="O barramento ja possuia mecanismo de idempotencia por identificador de mensagem.",
)
TRECHOS = {TRECHO.trecho_id: TRECHO}


def justificativa(trecho_id: str = TRECHO.trecho_id) -> dict:
    return {
        "porque": [{"afirmacao": "Mecanismo ja existia", "trecho_id": trecho_id}],
        "como": ["Comparou o estado anterior com a hipotese"],
        "evidencias_contrarias": [],
        "lacunas": ["Falta registro da hipotese inicial"],
    }


def ponto(ponto_: Ponto, criterio=None, trecho_id=TRECHO.trecho_id) -> PontoDecisao:
    p = PontoDecisao(projeto_id="PRJ-TESTE", ponto=ponto_, criterio=criterio)
    p.propor("Nao elegivel" if ponto_ == Ponto.D5 else "atende", justificativa(trecho_id))
    return p


def projeto_decidido(trecho_id: str = TRECHO.trecho_id) -> list[PontoDecisao]:
    pontos = [
        ponto(Ponto.D1, trecho_id=trecho_id),
        ponto(Ponto.D2, criterio="novidade", trecho_id=trecho_id),
        ponto(Ponto.D3, criterio="atividade-A02", trecho_id=trecho_id),
        ponto(Ponto.D4, trecho_id=trecho_id),
        ponto(Ponto.D5, trecho_id=trecho_id),
    ]
    for p in pontos:
        p.aceitar(ANALISTA)
    return pontos


def test_nao_gera_dossie_com_ponto_pendente():
    pontos = projeto_decidido()
    pontos[2].reabrir(causa="teste")  # volta a estar pendente de decisao
    with pytest.raises(DossieIncompleto, match="PRJ-TESTE-D3"):
        gerar_dossie("PRJ-TESTE", pontos, TRECHOS, "v1", [], AGORA)


def test_dossie_traz_regra_evidencia_analista_e_data():
    texto = gerar_dossie(
        "PRJ-TESTE", projeto_decidido(), TRECHOS, "Norma fictícia v1", ["Nada"], AGORA
    )
    assert "Versão da norma utilizada: Norma fictícia v1" in texto
    assert "Emitido em: 08/10/2026 15:00" in texto
    assert "Analista: ANL-01" in texto
    assert "PRJ-TESTE-dossie#002" in texto
    assert "Estado anterior" in texto
    assert "## Analistas envolvidos" in texto


def test_referencia_inexistente_aparece_como_problema_no_dossie():
    pontos = projeto_decidido(trecho_id="PRJ-TESTE-dossie#999")
    texto = gerar_dossie("PRJ-TESTE", pontos, TRECHOS, "v1", [], AGORA)
    assert "não encontrada na base" in texto
    assert "PRJ-TESTE-dossie#999" in texto


def test_secao_de_nao_verificado_e_obrigatoria_no_texto():
    texto = gerar_dossie(
        "PRJ-TESTE",
        projeto_decidido(),
        TRECHOS,
        "v1",
        ["Entrevista tecnica nao conferida"],
        AGORA,
    )
    assert "## O que não foi verificado" in texto
    assert "Entrevista tecnica nao conferida" in texto


def test_alteracao_aparece_com_motivo_e_analista():
    d1 = ponto(Ponto.D1)
    d1.alterar("Com ressalvas", motivo=MOTIVO, analista="ANL-02")
    demais = projeto_decidido()[1:]
    pontos = [d1] + demais
    texto = gerar_dossie("PRJ-TESTE", pontos, TRECHOS, "v1", [], AGORA)
    assert "ANL-02 alterou a proposta de “atende” para" in texto
    assert f"Motivo registrado: {MOTIVO}" in texto
    assert "Analista: ANL-02" in texto
    assert MOTIVO in texto


def test_reabertura_aparece_no_dossie():
    pontos = projeto_decidido()
    pontos[2].reabrir(causa="teste")
    pontos[2].propor("atende", justificativa())
    pontos[2].aceitar(ANALISTA)
    texto = gerar_dossie("PRJ-TESTE", pontos, TRECHOS, "v1", [], AGORA)
    assert "Reaberto 1 vez(es)" in texto
