"""Log das decisoes em disco, reabertura de pontos e discordancias."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.decisoes import discordancias
from src.decisoes.maquina_estados import Ponto, Status, proximo_ponto_pendente
from src.decisoes.registro import RegistroDecisoes
from src.motor.analisador import analisar_projeto
from src.motor.fluxo import criar_pontos, propor_classificacao, rever_ponto
from src.motor.regras import NAO_ELEGIVEL
from src.pacote.carregador import carregar_projeto
from src.rag.corpus import montar_corpus
from src.schemas.discordancia import ClassificacaoPreliminar, StatusDiscordancia, TipoDiscordancia
from tests.unit.proposta_exemplo import ClienteFalso, proposta

PACOTE = Path(__file__).resolve().parents[2] / "dados/fixtures/pacote_exemplo"
PRJ99 = PACOTE / "01_projetos/02_casos_para_analise/PRJ99"
MOTIVO = "O protocolo compara duas versões com critério prévio."


@pytest.fixture
def analise():
    corpus = montar_corpus(carregar_projeto(PRJ99))
    return analisar_projeto(corpus.projeto, ClienteFalso(proposta()), corpus)


def _ponto(pontos, decision_id):
    return next(p for p in pontos if p.decision_id == decision_id)


def _decidir_ate_d5(pontos):
    while (atual := proximo_ponto_pendente(pontos)).ponto != Ponto.D5:
        atual.aceitar("ANL-01")


# ----- log das decisoes -----

def test_decisoes_sao_retomadas_do_arquivo(analise, tmp_path):
    pontos = criar_pontos(analise)
    RegistroDecisoes(tmp_path, "PRJ99").iniciar_analise(pontos)
    pontos[0].aceitar("ANL-01")
    pontos[1].alterar("INDETERMINADA", MOTIVO, "ANL-01")
    pontos[2].rejeitar(MOTIVO, "ANL-01")

    retomados = RegistroDecisoes(tmp_path, "PRJ99").retomar()
    assert [p.decision_id for p in retomados] == [p.decision_id for p in pontos]
    for original, retomado in zip(pontos, retomados):
        assert retomado.status == original.status
        assert retomado.valor_proposto == original.valor_proposto
        assert retomado.valor_final == original.valor_final
        assert retomado.motivo == original.motivo
        assert retomado.analista == original.analista
        assert retomado.justificativa == original.justificativa
        assert retomado.eventos == original.eventos
    assert proximo_ponto_pendente(retomados).decision_id == "PRJ99-D2-criatividade"


def test_decisao_depois_de_retomar_continua_no_mesmo_arquivo(analise, tmp_path):
    RegistroDecisoes(tmp_path, "PRJ99").iniciar_analise(criar_pontos(analise))
    RegistroDecisoes(tmp_path, "PRJ99").retomar()[0].aceitar("ANL-01")
    assert RegistroDecisoes(tmp_path, "PRJ99").retomar()[0].status == Status.ACEITA


def test_nova_analise_nao_apaga_o_historico(analise, tmp_path):
    registro = RegistroDecisoes(tmp_path, "PRJ99")
    primeira = criar_pontos(analise)
    registro.iniciar_analise(primeira)
    primeira[0].aceitar("ANL-01")
    registro.iniciar_analise(criar_pontos(analise))

    assert registro.retomar()[0].status == Status.AGUARDANDO_ANALISTA
    decisoes = [e for e in registro.historico() if e["evento"] == "decisao_analista"]
    assert len(decisoes) == 1


def test_sem_log_nao_ha_o_que_retomar(tmp_path):
    assert RegistroDecisoes(tmp_path, "PRJ99").retomar() is None


def test_proposta_vigente_nao_traz_a_decisao_do_analista(analise, tmp_path):
    pontos = criar_pontos(analise)
    registro = RegistroDecisoes(tmp_path, "PRJ99")
    registro.iniciar_analise(pontos)
    pontos[0].aceitar("ANL-01")
    pontos[1].alterar("INDETERMINADA", MOTIVO, "ANL-01")

    visto = registro.proposta_vigente("PRJ99-D2-novidade", datetime.now(timezone.utc))
    assert visto.valor_proposto == "NÃO DEMONSTRADA"
    assert visto.justificativa == pontos[1].justificativa
    assert visto.valor_final is None and visto.motivo is None and visto.analista is None
    assert visto.eventos == []


# ----- reabertura -----

def test_rever_um_criterio_reabre_o_que_depende_dele(analise):
    pontos = criar_pontos(analise)
    _decidir_ate_d5(pontos)
    propor_classificacao(pontos, analise).aceitar("ANL-01")

    novidade = _ponto(pontos, "PRJ99-D2-novidade")
    reabertos = rever_ponto(pontos, novidade, "ANL-02")
    assert [p.decision_id for p in reabertos] == ["PRJ99-D2-novidade", "PRJ99-D4", "PRJ99-D5"]
    # A proposta da IA volta a aguardar decisao; D5 espera os criterios.
    assert novidade.status == Status.AGUARDANDO_ANALISTA
    assert novidade.valor_final is None
    assert _ponto(pontos, "PRJ99-D5").status == Status.REABERTA
    assert _ponto(pontos, "PRJ99-D1").decidido
    assert novidade.eventos[-2]["causa"] == "revisão pedida por ANL-02"

    novidade.alterar("INDETERMINADA", MOTIVO, "ANL-02")
    _ponto(pontos, "PRJ99-D4").aceitar("ANL-02")
    d5 = propor_classificacao(pontos, analise)
    assert d5.valor_proposto != NAO_ELEGIVEL


# ----- discordancias -----

def _discordancia(analise, projeto="PRJ99", analista="ANL-01", tipo=TipoDiscordancia.EVIDENCIA_MAL_LIDA):
    pontos = criar_pontos(analise)
    novidade = pontos[1]
    novidade.projeto_id = projeto
    novidade.alterar("INDETERMINADA", MOTIVO, analista)
    return discordancias.abrir_discordancia(novidade, tipo, "base de regras regras-v1", "prompt v1 / falso")


def test_alteracao_vira_discordancia_com_pseudonimo(analise):
    registro = _discordancia(analise)
    assert registro.decision_id == "PRJ99-D2-novidade"
    assert registro.criterio == "novidade"
    assert registro.valor_ia == "NÃO DEMONSTRADA"
    assert registro.valor_analista == "INDETERMINADA"
    assert registro.classificacao_ia is None
    assert registro.status == StatusDiscordancia.REGISTRADA
    assert "ANL-01" not in registro.model_dump_json()
    assert registro.analista_origem_pseudonimo == discordancias.pseudonimo(" anl-01 ")


def test_ponto_aceito_nao_gera_discordancia(analise):
    pontos = criar_pontos(analise)
    pontos[0].aceitar("ANL-01")
    with pytest.raises(ValueError):
        discordancias.abrir_discordancia(pontos[0], TipoDiscordancia.EVIDENCIA_AUSENTE, "n", "m")


def test_discordancia_da_classificacao_guarda_a_classe(analise):
    pontos = criar_pontos(analise)
    _decidir_ate_d5(pontos)
    d5 = propor_classificacao(pontos, analise)
    d5.alterar("Com ressalvas", MOTIVO, "ANL-01")
    registro = discordancias.abrir_discordancia(d5, TipoDiscordancia.DIVERGENCIA_DE_MERITO, "n", "m")
    assert registro.criterio == "D5"
    assert registro.classificacao_ia == ClassificacaoPreliminar.NAO_ELEGIVEL
    assert registro.classificacao_analista == ClassificacaoPreliminar.COM_RESSALVAS


def test_quem_abriu_nao_revisa_a_propria_discordancia(analise):
    registros = [_discordancia(analise)]
    assert discordancias.pendentes_para(registros, "ANL-01") == []
    assert discordancias.pendentes_para(registros, "ANL-02") == registros
    with pytest.raises(ValueError):
        discordancias.revisar(registros[0], "ANL-01", False, MOTIVO)


def test_revisao_e_gravada_sem_reescrever_o_arquivo(analise, tmp_path):
    repositorio = discordancias.RepositorioDiscordancias(tmp_path / "discordancias.jsonl")
    registro = _discordancia(analise)
    repositorio.salvar(registro)
    repositorio.salvar(discordancias.revisar(registro, "ANL-02", False, MOTIVO))

    assert len(repositorio.caminho.read_text(encoding="utf-8").splitlines()) == 2
    (salvo,) = repositorio.todas()
    assert salvo.status == StatusDiscordancia.CONVERGENCIA_CONTRA_IA
    assert discordancias.pendentes_para([salvo], "ANL-03") == []
    assert discordancias.metricas([salvo]) == {
        "total": 1, "aguardando_revisao": 0, "confirmadas": 1, "nao_confirmadas": 0,
    }


def test_precedente_so_de_discordancia_confirmada_em_outro_projeto(analise):
    confirmada = discordancias.revisar(_discordancia(analise, "PRJ21"), "ANL-02", False, MOTIVO)
    nao_confirmada = discordancias.revisar(_discordancia(analise, "PRJ22"), "ANL-02", True, MOTIVO)
    pendente = _discordancia(analise, "PRJ23")
    registros = [confirmada, nao_confirmada, pendente]

    (resumo,) = discordancias.precedentes_do_criterio(registros, "novidade", "PRJ99")
    assert resumo.quantidade_casos == 1
    assert resumo.casos[0].projeto_origem == "PRJ21"
    assert resumo.casos[0].natureza == "interno_nao_normativo"
    assert resumo.casos[0].valor_resultante == "INDETERMINADA"
    assert discordancias.precedentes_do_criterio(registros, "novidade", "PRJ21") == []
    assert discordancias.precedentes_do_criterio(registros, "incerteza", "PRJ99") == []


def test_padrao_candidato_exige_mesmo_criterio_e_tipo_em_tres_projetos(analise):
    def confirmada(projeto, tipo=TipoDiscordancia.EVIDENCIA_MAL_LIDA):
        return discordancias.revisar(_discordancia(analise, projeto, tipo=tipo), "ANL-02", False, MOTIVO)

    dois = [confirmada("PRJ21"), confirmada("PRJ22")]
    outro_tipo = confirmada("PRJ23", TipoDiscordancia.REGRA_MAL_APLICADA)
    assert discordancias.padroes_candidatos(dois + [outro_tipo]) == []
    assert discordancias.padroes_candidatos(dois + [confirmada("PRJ23")]) == [
        ("novidade", TipoDiscordancia.EVIDENCIA_MAL_LIDA, ["PRJ21", "PRJ22", "PRJ23"])
    ]
