"""Da decisão do analista à revisão cega, ao precedente e à fila do curador."""

from pathlib import Path

import pytest

from src.decisoes.maquina_estados import Ponto
from src.discordancias import servico
from src.discordancias.repositorio import DiscordanciaInvalida, RepositorioDiscordancias
from src.motor.analisador import analisar_projeto
from src.motor.fluxo import criar_pontos, propor_classificacao
from src.motor.regras import COM_RESSALVAS, NAO_ELEGIVEL
from src.pacote.carregador import carregar_projeto
from src.rag.corpus import montar_corpus
from src.schemas.discordancia import (
    ClassificacaoPreliminar,
    StatusDiscordancia,
    TipoDiscordancia,
    padroes_candidatos,
)
from tests.unit.proposta_exemplo import ClienteFalso, proposta

PRJ99 = (
    Path(__file__).resolve().parents[2]
    / "dados/fixtures/pacote_exemplo/01_projetos/02_casos_para_analise/PRJ99"
)
MOTIVO = "O protocolo compara duas versões com critério prévio."
TIPO = TipoDiscordancia.EVIDENCIA_MAL_LIDA


@pytest.fixture
def analise():
    corpus = montar_corpus(carregar_projeto(PRJ99))
    return analisar_projeto(corpus.projeto, ClienteFalso(proposta()), corpus)


@pytest.fixture
def repositorio(tmp_path):
    return RepositorioDiscordancias(tmp_path / "discordancias" / "eventos.jsonl")


def _novidade(analise, projeto_id="PRJ99"):
    ponto = next(p for p in criar_pontos(analise) if p.criterio == "novidade")
    ponto.projeto_id = projeto_id
    return ponto


def _discordar(repositorio, analise, projeto_id="PRJ99", analista="ANL-01", tipo=TIPO):
    ponto = _novidade(analise, projeto_id)
    ponto.alterar("DEMONSTRADA NO RECORTE", MOTIVO, analista)
    return repositorio.registrar(
        servico.abrir_discordancia(ponto, tipo, analise, repositorio.proximo_id())
    )


def _revisar(repositorio, registro, concorda=False, valor="DEMONSTRADA NO RECORTE", analista="ANL-02"):
    return repositorio.registrar_revisao(
        registro.discordancia_id, servico.nova_revisao(analista, concorda, MOTIVO, valor)
    )


# ----- da decisao a discordancia -----

def test_alterar_abre_discordancia_com_a_proposta_e_a_decisao(repositorio, analise):
    registro = _discordar(repositorio, analise)
    assert registro.discordancia_id == "DSC-0001"
    assert registro.decision_id == "PRJ99-D2-novidade"
    assert registro.criterio == "novidade"
    assert (registro.valor_ia, registro.valor_analista) == ("NÃO DEMONSTRADA", "DEMONSTRADA NO RECORTE")
    assert registro.versao_motor == f"{analise.versao_prompt} / falso/modelo"
    assert registro.classificacao_ia is None            # o ponto nao e a classificacao
    assert registro.status == StatusDiscordancia.REGISTRADA


def test_rejeitar_abre_discordancia_sem_valor_do_analista(repositorio, analise):
    ponto = _novidade(analise)
    ponto.rejeitar(MOTIVO, "ANL-01")
    registro = servico.abrir_discordancia(ponto, TIPO, analise, "DSC-0001")
    assert registro.valor_analista is None


def test_aceitar_nao_e_discordancia(analise):
    ponto = _novidade(analise)
    ponto.aceitar("ANL-01")
    with pytest.raises(ValueError):
        servico.abrir_discordancia(ponto, TIPO, analise, "DSC-0001")


def test_discordancia_da_classificacao_guarda_as_classes(analise):
    pontos = criar_pontos(analise)
    for ponto in pontos[:-1]:
        ponto.aceitar("ANL-01")
    d5 = propor_classificacao(pontos, analise)
    d5.alterar(COM_RESSALVAS, MOTIVO, "ANL-01")
    registro = servico.abrir_discordancia(d5, TipoDiscordancia.DIVERGENCIA_DE_MERITO, analise, "DSC-0001")
    assert registro.criterio == "D5"
    assert registro.valor_ia == NAO_ELEGIVEL
    assert registro.classificacao_ia == ClassificacaoPreliminar.NAO_ELEGIVEL
    assert registro.classificacao_analista == ClassificacaoPreliminar.COM_RESSALVAS


# ----- revisao cega -----

def test_ponto_da_revisao_cega_nao_leva_a_decisao_do_primeiro(repositorio, analise):
    ponto = servico.ponto_da_discordancia(_discordar(repositorio, analise))
    assert (ponto.ponto, ponto.criterio) == (Ponto.D2, "novidade")
    assert ponto.valor_proposto == "NÃO DEMONSTRADA"
    assert ponto.justificativa["porque"]
    assert ponto.valor_final is None and ponto.motivo is None and ponto.analista is None


def test_fila_de_revisao_exclui_quem_abriu_e_o_que_ja_foi_revisado(repositorio, analise):
    registro = _discordar(repositorio, analise)
    assert servico.fila_de_revisao(repositorio.listar(), " anl-01 ") == []
    assert [r.discordancia_id for r in servico.fila_de_revisao(repositorio.listar(), "ANL-02")] == ["DSC-0001"]
    _revisar(repositorio, registro)
    assert servico.fila_de_revisao(repositorio.listar(), "ANL-02") == []


@pytest.mark.parametrize(
    "concorda, valor, esperado",
    [
        (False, "DEMONSTRADA NO RECORTE", StatusDiscordancia.CONVERGENCIA_CONTRA_IA),
        (False, "INDETERMINADA", StatusDiscordancia.DIVERGENCIA_ENTRE_ANALISTAS),
        (False, None, StatusDiscordancia.CONVERGENCIA_CONTRA_IA),
        (True, "INDETERMINADA", StatusDiscordancia.NAO_CONFIRMADA),
    ],
)
def test_resultado_da_revisao_cega(repositorio, analise, concorda, valor, esperado):
    resolvida = _revisar(repositorio, _discordar(repositorio, analise), concorda, valor)
    assert resolvida.status == esperado
    assert repositorio.listar()[0].status == esperado
    # A revisao nao mexe na decisao do caso.
    assert resolvida.valor_analista == "DEMONSTRADA NO RECORTE"


def test_revisao_exige_outro_analista_e_acontece_uma_vez_so(repositorio, analise):
    registro = _discordar(repositorio, analise)
    with pytest.raises(ValueError):
        _revisar(repositorio, registro, analista="ANL-01")
    assert repositorio.listar()[0].revisao is None
    _revisar(repositorio, registro)
    with pytest.raises(DiscordanciaInvalida):
        _revisar(repositorio, registro, analista="ANL-03")
    with pytest.raises(DiscordanciaInvalida):
        repositorio.registrar_revisao("DSC-9999", servico.nova_revisao("ANL-02", True, MOTIVO))


def test_log_so_recebe_anexos(repositorio, analise):
    registro = _discordar(repositorio, analise)
    antes = repositorio.caminho.read_text(encoding="utf-8")
    _revisar(repositorio, registro)
    depois = repositorio.caminho.read_text(encoding="utf-8")
    assert depois.startswith(antes)
    assert [e["evento"] for e in repositorio.eventos()] == [
        "discordancia_registrada", "revisao_registrada",
    ]
    with pytest.raises(DiscordanciaInvalida):
        repositorio.registrar(registro)


# ----- precedentes e curador -----

def test_so_discordancia_confirmada_vira_precedente(repositorio, analise):
    _revisar(repositorio, _discordar(repositorio, analise, "PRJ21"))
    _revisar(repositorio, _discordar(repositorio, analise, "PRJ22"), concorda=True)
    _discordar(repositorio, analise, "PRJ23")           # ainda sem revisao
    registros = repositorio.listar()

    (resumo,) = servico.precedentes_do_criterio(registros, "novidade")
    assert resumo.quantidade_casos == 1
    caso = resumo.casos[0]
    assert caso.projeto_origem == "PRJ21"
    assert caso.natureza == "interno_nao_normativo"
    assert caso.valor_resultante == "DEMONSTRADA NO RECORTE"
    assert "não alteram" in resumo.aviso
    assert servico.precedentes_do_criterio(registros, "criatividade") == []


def test_motivo_longo_e_resumido_no_precedente(repositorio, analise):
    ponto = _novidade(analise)
    ponto.alterar("DEMONSTRADA NO RECORTE", "Motivo extenso. " * 40, "ANL-01")
    registro = repositorio.registrar(servico.abrir_discordancia(ponto, TIPO, analise, "DSC-0001"))
    _revisar(repositorio, registro)
    (resumo,) = servico.precedentes_do_criterio(repositorio.listar(), "novidade")
    assert len(resumo.casos[0].motivo_resumido) <= 300


def test_padrao_candidato_exige_mesmo_criterio_e_tipo_em_tres_projetos(repositorio, analise):
    for projeto in ("PRJ21", "PRJ22"):
        _revisar(repositorio, _discordar(repositorio, analise, projeto))
    _revisar(
        repositorio,
        _discordar(repositorio, analise, "PRJ23", tipo=TipoDiscordancia.REGRA_MAL_APLICADA),
    )
    assert padroes_candidatos(repositorio.listar()) == []

    _revisar(repositorio, _discordar(repositorio, analise, "PRJ24"))
    ((criterio, tipo, casos),) = padroes_candidatos(repositorio.listar())
    assert (criterio, tipo) == ("novidade", TIPO)
    assert {c.projeto_id for c in casos} == {"PRJ21", "PRJ22", "PRJ24"}


def test_metricas_de_acompanhamento(repositorio, analise):
    assert servico.metricas([])["taxa_convergencia"] is None
    _revisar(repositorio, _discordar(repositorio, analise, "PRJ21"))
    _revisar(repositorio, _discordar(repositorio, analise, "PRJ22"), concorda=True)
    _revisar(repositorio, _discordar(repositorio, analise, "PRJ23"), valor="INDETERMINADA")
    _discordar(repositorio, analise, "PRJ24")
    numeros = servico.metricas(repositorio.listar())
    assert (numeros["total"], numeros["aguardando_revisao"], numeros["revisadas"]) == (4, 1, 3)
    assert (numeros["convergentes"], numeros["nao_confirmadas"], numeros["divergentes"]) == (1, 1, 1)
    assert numeros["taxa_convergencia"] == 0.25
    assert numeros["concordancia_entre_analistas"] == pytest.approx(1 / 3)
    assert numeros["por_criterio_e_tipo"] == {("novidade", TIPO): 4}
