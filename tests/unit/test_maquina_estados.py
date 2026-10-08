import pytest

from src.decisoes.maquina_estados import (
    DecisaoInvalida,
    Ponto,
    PontoDecisao,
    Status,
    TransicaoInvalida,
    decisao_final_pronta,
    pode_apresentar,
    proximo_ponto_pendente,
    reabrir_dependentes,
)

MOTIVO_OK = "A atividade A02 nao tem registro de hipotese inicial."
ANALISTA = "ANL-01"
OUTRO = "ANL-02"


def novo_ponto(ponto: Ponto, criterio: str | None = None, valor="atende") -> PontoDecisao:
    p = PontoDecisao(projeto_id="PRJ-TESTE", ponto=ponto, criterio=criterio)
    p.propor(valor)
    return p


# ----- transicoes basicas -----

def test_proposta_vai_para_aguardando_analista():
    p = novo_ponto(Ponto.D1)
    assert p.status == Status.AGUARDANDO_ANALISTA
    assert p.valor_proposto == "atende"


def test_aceitar_copia_proposta_e_registra_analista():
    p = novo_ponto(Ponto.D1)
    p.aceitar(ANALISTA)
    assert p.status == Status.ACEITA
    assert p.valor_final == "atende"
    assert p.analista == ANALISTA
    assert p.decidido


def test_aceitar_exige_analista():
    p = novo_ponto(Ponto.D1)
    with pytest.raises(DecisaoInvalida):
        p.aceitar("   ")


def test_alterar_exige_motivo_e_valor_diferente():
    p = novo_ponto(Ponto.D1)
    with pytest.raises(DecisaoInvalida):
        p.alterar("atende_parcialmente", motivo="curto", analista=ANALISTA)
    with pytest.raises(DecisaoInvalida):
        p.alterar("atende", motivo=MOTIVO_OK, analista=ANALISTA)  # igual: use aceitar
    p.alterar("atende_parcialmente", motivo=MOTIVO_OK, analista=ANALISTA)
    assert p.status == Status.ALTERADA
    assert p.valor_final == "atende_parcialmente"
    assert p.decidido


def test_rejeitar_exige_motivo_e_nao_fica_decidido():
    p = novo_ponto(Ponto.D2, criterio="novidade")
    with pytest.raises(DecisaoInvalida):
        p.rejeitar("nao", analista=ANALISTA)
    p.rejeitar(MOTIVO_OK, analista=ANALISTA)
    assert p.status == Status.REJEITADA
    assert not p.decidido


def test_rejeitada_pode_ser_refeita_pela_ia():
    p = novo_ponto(Ponto.D2, criterio="novidade")
    p.rejeitar(MOTIVO_OK, analista=ANALISTA)
    p.propor("atende_parcialmente")
    assert p.status == Status.AGUARDANDO_ANALISTA
    assert p.valor_proposto == "atende_parcialmente"
    assert p.motivo is None
    assert p.analista is None


def test_aceitar_sem_proposta_e_invalido():
    p = PontoDecisao(projeto_id="PRJ-TESTE", ponto=Ponto.D1)
    with pytest.raises(TransicaoInvalida):
        p.aceitar(ANALISTA)


def test_nao_aceita_acao_fora_de_estado():
    p = novo_ponto(Ponto.D1)
    p.aceitar(ANALISTA)
    with pytest.raises(TransicaoInvalida):
        p.rejeitar(MOTIVO_OK, analista=ANALISTA)


# ----- justificativa e log -----

def test_justificativa_fica_na_proposta_e_no_log():
    p = PontoDecisao(projeto_id="PRJ-TESTE", ponto=Ponto.D2, criterio="novidade")
    justificativa = {
        "porque": [{"afirmacao": "O resultado era novo", "trecho_id": "PRJ-TESTE-dossie#002"}],
        "como": ["Consultou 2 trechos do dossie"],
        "evidencias_contrarias": [],
        "lacunas": [],
    }
    p.propor("atende", justificativa=justificativa)
    assert p.justificativa["porque"][0]["trecho_id"] == "PRJ-TESTE-dossie#002"
    assert p.eventos[0]["justificativa"] == justificativa


def test_eventos_sao_registrados_em_ordem_com_analista():
    p = novo_ponto(Ponto.D1)
    p.alterar("atende_parcialmente", motivo=MOTIVO_OK, analista=ANALISTA)
    tipos = [e["evento"] for e in p.eventos]
    assert tipos == ["proposta_publicada", "decisao_analista"]
    ultimo = p.eventos[-1]
    assert ultimo["analista"] == ANALISTA
    assert ultimo["valor_proposto"] == "atende"
    assert ultimo["valor_final"] == "atende_parcialmente"


# ----- sequencia D1 a D5 -----

def projeto_completo() -> list[PontoDecisao]:
    return [
        novo_ponto(Ponto.D1),
        novo_ponto(Ponto.D2, criterio="novidade"),
        novo_ponto(Ponto.D3, criterio="atividade-A02"),
        novo_ponto(Ponto.D4),
        novo_ponto(Ponto.D5),
    ]


def aceitar_todos(pontos: list[PontoDecisao]) -> None:
    for p in pontos:
        p.aceitar(ANALISTA)


def test_proximo_ponto_pendente_segue_a_ordem():
    pontos = projeto_completo()
    assert proximo_ponto_pendente(pontos).ponto == Ponto.D1
    pontos[0].aceitar(ANALISTA)
    assert proximo_ponto_pendente(pontos).ponto == Ponto.D2


def test_nao_apresenta_ponto_sem_anteriores_decididos():
    pontos = projeto_completo()
    assert pode_apresentar(pontos, Ponto.D1)
    assert not pode_apresentar(pontos, Ponto.D2)
    pontos[0].aceitar(ANALISTA)
    assert pode_apresentar(pontos, Ponto.D2)
    assert not pode_apresentar(pontos, Ponto.D3)


def test_decisao_final_so_quando_todos_decididos():
    pontos = projeto_completo()
    assert not decisao_final_pronta(pontos)
    aceitar_todos(pontos)
    assert decisao_final_pronta(pontos)


# ----- reabertura por dependencia -----

def test_mudar_d3_reabre_d2_e_cascata_ate_d5():
    pontos = projeto_completo()
    aceitar_todos(pontos)

    d3 = next(p for p in pontos if p.ponto == Ponto.D3)
    reabertos = reabrir_dependentes(pontos, d3)

    reabertos_ids = {p.ponto for p in reabertos}
    assert Ponto.D2 in reabertos_ids
    assert Ponto.D4 in reabertos_ids
    assert Ponto.D5 in reabertos_ids
    assert Ponto.D1 not in reabertos_ids
    assert Ponto.D3 not in reabertos_ids  # a origem nao e reaberta
    assert not decisao_final_pronta(pontos)


def test_reabertura_nao_mexe_em_pontos_nao_decididos():
    pontos = projeto_completo()
    pontos[0].aceitar(ANALISTA)
    pontos[1].aceitar(ANALISTA)  # D2 decidido
    d3 = pontos[2]               # D3 pendente, serve de origem para o teste
    reabertos = reabrir_dependentes(pontos, d3)
    assert [p.ponto for p in reabertos] == [Ponto.D2]
    assert pontos[1].status == Status.REABERTA
    # D4 nao decidido nao e reaberto, continua aguardando o analista
    assert pontos[3].status == Status.AGUARDANDO_ANALISTA


def test_ponto_reaberto_volta_a_ser_proposto_e_registra_causa():
    pontos = projeto_completo()
    aceitar_todos(pontos)
    d4 = pontos[3]
    reabrir_dependentes(pontos, d4)
    d5 = pontos[4]
    assert d5.status == Status.REABERTA
    assert d5.eventos[-1]["evento"] == "ponto_reaberto"
    assert d5.eventos[-1]["causa"] == d4.decision_id

    d5.propor("Com ressalvas")
    d5.aceitar(OUTRO)
    assert d5.decidido
    assert d5.analista == OUTRO
