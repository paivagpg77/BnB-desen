from pathlib import Path

import pytest

from src.decisoes.maquina_estados import Ponto, decisao_final_pronta, proximo_ponto_pendente
from src.dossie.gerador import gerar_dossie
from src.motor.analisador import (
    RespostaInvalida,
    analisar_projeto,
    extrair_json,
    versao_do_prompt,
)
from src.motor.fluxo import criar_pontos, propor_classificacao, trechos_do_dossie
from src.motor.regras import (
    COM_RESSALVAS,
    ELEGIVEL,
    EVIDENCIA_INSUFICIENTE,
    NAO_ELEGIVEL,
    Criterio,
    derivar_classificacao,
)
from src.pacote.carregador import carregar_projeto
from src.rag.corpus import carregar_regras, montar_corpus, recuperar_contexto
from tests.unit.proposta_exemplo import REGRA_NOVIDADE, ClienteFalso, proposta

PRJ99 = (
    Path(__file__).resolve().parents[2]
    / "dados/fixtures/pacote_exemplo/01_projetos/02_casos_para_analise/PRJ99"
)
ANALISTA = "ANL-01"
MOTIVO = "O protocolo compara duas versões com critério prévio."


@pytest.fixture
def corpus():
    return montar_corpus(carregar_projeto(PRJ99))


# ----- regra de classificacao -----

def _estados(novidade, criatividade, incerteza, sistematicidade, transferencia):
    return dict(zip(Criterio, (novidade, criatividade, incerteza, sistematicidade, transferencia)))


@pytest.mark.parametrize(
    "estados, esperado",
    [
        (("DEMONSTRADA NO RECORTE", "DEMONSTRADA NO RECORTE", "INVESTIGADA",
          "DOCUMENTADA", "DOCUMENTADA NO ESCOPO"), ELEGIVEL),
        (("DEMONSTRADA NO RECORTE", "DEMONSTRADA NO RECORTE", "INVESTIGADA",
          "DOCUMENTADA", "DOCUMENTADA COM LIMITE"), COM_RESSALVAS),
        (("NÃO DEMONSTRADA", "NÃO DEMONSTRADA", "NÃO CARACTERIZADA",
          "DOCUMENTADA COMO ACEITE", "DOCUMENTADA PARA A CONFIGURAÇÃO"), NAO_ELEGIVEL),
        (("INDETERMINADA", "INDETERMINADA", "ALEGADA, NÃO VERIFICÁVEL",
          "PARCIAL", "INSUFICIENTE PARA O NÚCLEO ALEGADO"), EVIDENCIA_INSUFICIENTE),
        # Um criterio do nucleo sem verificacao basta para faltar evidencia.
        (("DEMONSTRADA NO RECORTE", "DEMONSTRADA NO RECORTE", "ALEGADA, NÃO VERIFICÁVEL",
          "DOCUMENTADA", "DOCUMENTADA NO ESCOPO"), EVIDENCIA_INSUFICIENTE),
        # Combinacao mista: a ferramenta nao sugere classe.
        (("DEMONSTRADA NO RECORTE", "NÃO DEMONSTRADA", "INVESTIGADA",
          "DOCUMENTADA", "DOCUMENTADA NO ESCOPO"), None),
        (("DEMONSTRADA NO RECORTE", "DEMONSTRADA NO RECORTE", "INVESTIGADA",
          "PARCIAL", "DOCUMENTADA NO ESCOPO"), None),
    ],
)
def test_classificacao_derivada_dos_estados(estados, esperado):
    assert derivar_classificacao(_estados(*estados))[0] == esperado


def test_estado_desconhecido_nao_gera_classificacao():
    estados = _estados("ÓTIMA", "DEMONSTRADA NO RECORTE", "INVESTIGADA", "DOCUMENTADA", "DOCUMENTADA NO ESCOPO")
    classificacao, regra = derivar_classificacao(estados)
    assert classificacao is None
    assert "Novidade" in regra


# ----- corpus e recuperacao -----

def test_corpus_usa_identificadores_do_pacote(corpus):
    for trecho_id in ("evidencias/metodo.md#2", "PRJ99-S03", "PRJ99-ATV02", "PRJ99-OBS01",
                      "PRJ99-CR01", "PRJ99-IN001", "inventario_evidencias.csv"):
        assert trecho_id in corpus.trechos
    assert "dossie_projeto.pdf" not in corpus.trechos
    assert corpus.natureza["PRJ99-S01"] == "registro primário"
    assert "18/20" in corpus.trechos["PRJ99-S01"].texto
    assert "conferência com medicoes.csv: confere" in corpus.trechos["PRJ99-S01"].texto


def test_normaliza_formas_alternativas_de_citar(corpus):
    assert corpus.normalizar("evidencias/medicoes.csv#PRJ99-S01") == "PRJ99-S01"
    assert corpus.normalizar("`evidencias/metodo.md#1`") == "evidencias/metodo.md#1"
    assert corpus.normalizar("PRJ99-EV77") is None
    assert corpus.normalizar("PRJ99-EV01") is None      # PDF nao entregue


def test_contexto_tem_o_nucleo_e_respeita_o_orcamento(corpus):
    completo = {t.trecho_id for t in recuperar_contexto(corpus, ["etiquetas coletor"])}
    assert {"evidencias/metodo.md#1", "evidencias/metodo.md#2", "PRJ99-S01", "PRJ99-OBS01"} <= completo
    assert "PRJ99-ATV01" in completo                    # veio da busca
    apertado = {t.trecho_id for t in recuperar_contexto(corpus, ["etiquetas coletor"], orcamento=0)}
    assert "PRJ99-ATV01" not in apertado                # busca nao cabe; nucleo permanece
    assert "evidencias/metodo.md#1" in apertado


def test_base_de_regras_tem_secao_por_criterio():
    regras = {t.secao: t.trecho_id for t in carregar_regras()}
    assert regras["Novidade"] == REGRA_NOVIDADE
    assert {"Incerteza tecnológica", "Classificações", "Tratamento das evidências"} <= set(regras)


# ----- analise -----

def test_analise_confere_fontes_e_deriva_a_classificacao(corpus):
    cliente = ClienteFalso(proposta())
    analise = analisar_projeto(corpus.projeto, cliente, corpus)

    assert analise.modelo == "falso/modelo"
    assert analise.versao_prompt == versao_do_prompt()
    assert analise.classificacao_derivada == NAO_ELEGIVEL
    assert analise.proposta.criterio(Criterio.NOVIDADE).estado == "NÃO DEMONSTRADA"
    assert analise.proposta.criterio(Criterio.NOVIDADE).regra == REGRA_NOVIDADE
    # "arquivo#ensaio" vira o identificador do ensaio.
    assert analise.proposta.criterio(Criterio.SISTEMATICIDADE).fontes == ["PRJ99-S01"]
    # Fonte inventada sai; a valida permanece.
    assert analise.proposta.criterio(Criterio.INCERTEZA).fontes == ["evidencias/metodo.md#2"]
    assert analise.fontes_descartadas["incerteza"] == ["PRJ99-EV77"]
    # Apontamento sem fonte valida e atividade inexistente sao descartados.
    assert [a.texto for a in analise.proposta.contrarias] == ["A referência anterior já fazia o descarte."]
    assert [a.id_atividade for a in analise.proposta.atividades] == ["PRJ99-ATV01", "PRJ99-ATV02"]


def test_mensagem_leva_regras_sinais_e_evidencias_identificadas(corpus):
    cliente = ClienteFalso(proposta())
    analisar_projeto(corpus.projeto, cliente, corpus)
    sistema, usuario = cliente.chamadas[0]
    assert "Você propõe; o analista decide" in sistema
    assert f"[{REGRA_NOVIDADE}]" in usuario
    assert "[evidencias/metodo.md#2] (especificação)" in usuario
    assert "[PRJ99-S01] (registro primário)" in usuario
    assert "Arquivos do inventário ausentes" in usuario
    assert "INVESTIGADA | NÃO CARACTERIZADA | ALEGADA, NÃO VERIFICÁVEL" in usuario


def test_criterio_sem_fonte_valida_e_rebaixado(corpus):
    dados = proposta()
    dados["criterios"][0].update(estado="DEMONSTRADA NO RECORTE", fontes=["PRJ21-EV08"])
    analise = analisar_projeto(corpus.projeto, ClienteFalso(dados), corpus)
    assert analise.proposta.criterio(Criterio.NOVIDADE).estado == "INDETERMINADA"
    assert analise.classificacao_derivada == EVIDENCIA_INSUFICIENTE
    assert any("Novidade" in a and "rebaixada" in a for a in analise.avisos)
    assert any("Vale a regra" in a for a in analise.avisos)


def test_estado_fora_do_vocabulario_e_rebaixado(corpus):
    dados = proposta()
    dados["criterios"][2]["estado"] = "provavelmente sim"
    analise = analisar_projeto(corpus.projeto, ClienteFalso(dados), corpus)
    assert analise.proposta.criterio(Criterio.INCERTEZA).estado == "ALEGADA, NÃO VERIFICÁVEL"


def test_divergencia_so_e_mantida_com_as_duas_fontes(corpus):
    dados = proposta(divergencias=[
        {"depoimento": "Mantivemos a janela inicial.", "fonte_depoimento": "transcricao_entrevista_tecnica.pdf#6",
         "registro": "A janela foi ajustada.", "fonte_registro": "evidencias/metodo.md#2",
         "prevalece": "o registro"},
        {"depoimento": "Trinta e três leituras corretas.", "fonte_depoimento": "evidencias/revisao_tecnica.md#material-recebido",
         "registro": "33/40 em filtro-v1.", "fonte_registro": "PRJ99-S01", "prevalece": "o registro"},
    ])
    analise = analisar_projeto(corpus.projeto, ClienteFalso(dados), corpus)
    # A entrevista nao foi entregue no exemplo: a primeira divergencia nao tem base.
    assert [d.fonte_registro for d in analise.proposta.divergencias] == ["PRJ99-S01"]
    assert any("divergência(s)" in a for a in analise.avisos)


def test_resposta_invalida_e_repetida_uma_vez_com_o_erro(corpus):
    cliente = ClienteFalso("desculpe, não consegui", proposta())
    analise = analisar_projeto(corpus.projeto, cliente, corpus)
    assert analise.classificacao_derivada == NAO_ELEGIVEL
    assert len(cliente.chamadas) == 2
    assert "recusada pela validação" in cliente.chamadas[1][1]


def test_duas_respostas_invalidas_viram_erro(corpus):
    faltando = proposta()
    faltando["criterios"] = faltando["criterios"][:4]
    cliente = ClienteFalso(faltando)
    with pytest.raises(RespostaInvalida, match="2 tentativas"):
        analisar_projeto(corpus.projeto, cliente, corpus)


def test_extrai_json_cercado_por_texto():
    assert extrair_json('Segue:\n```json\n{"a": 1}\n```\nfim') == {"a": 1}
    with pytest.raises(RespostaInvalida):
        extrair_json("sem objeto")


# ----- fluxo de decisao -----

def test_fluxo_completo_ate_o_dossie(corpus):
    analise = analisar_projeto(corpus.projeto, ClienteFalso(proposta()), corpus)
    pontos = criar_pontos(analise)
    assert [p.decision_id for p in pontos] == [
        "PRJ99-D1", "PRJ99-D2-novidade", "PRJ99-D2-criatividade", "PRJ99-D2-incerteza",
        "PRJ99-D2-sistematicidade", "PRJ99-D2-transferencia", "PRJ99-D3", "PRJ99-D4", "PRJ99-D5",
    ]
    # D5 nao e proposto antes dos criterios serem decididos.
    assert pontos[-1].valor_proposto is None

    while (atual := proximo_ponto_pendente(pontos)).ponto != Ponto.D5:
        atual.aceitar(ANALISTA)
    d5 = propor_classificacao(pontos, analise)
    assert d5.valor_proposto == NAO_ELEGIVEL
    assert "R2" in " ".join(d5.justificativa["como"])
    d5.aceitar(ANALISTA)
    assert decisao_final_pronta(pontos)

    dossie = gerar_dossie(
        projeto_id="PRJ99", pontos=pontos, trechos=trechos_do_dossie(corpus),
        versao_norma="base de regras regras-v1", nao_verificado=analise.avisos,
    )
    assert "nao encontrada na base" not in dossie
    assert "`evidencias/metodo.md#1`" in dossie
    assert f"`{REGRA_NOVIDADE}`" in dossie
    assert "falso/modelo" in dossie
    assert "- Analista: ANL-01" in dossie


def test_classificacao_segue_o_que_o_analista_decidiu_e_nao_o_modelo(corpus):
    analise = analisar_projeto(corpus.projeto, ClienteFalso(proposta()), corpus)
    pontos = criar_pontos(analise)
    finais = {
        "novidade": "DEMONSTRADA NO RECORTE", "criatividade": "DEMONSTRADA NO RECORTE",
        "incerteza": "INVESTIGADA", "sistematicidade": "DOCUMENTADA",
        "transferencia": "DOCUMENTADA COM LIMITE",
    }
    while (atual := proximo_ponto_pendente(pontos)).ponto != Ponto.D5:
        if atual.ponto == Ponto.D2:
            atual.alterar(finais[atual.criterio], MOTIVO, ANALISTA)
        else:
            atual.aceitar(ANALISTA)
    d5 = propor_classificacao(pontos, analise)
    assert analise.proposta.classificacao_sugerida == NAO_ELEGIVEL
    assert d5.valor_proposto == COM_RESSALVAS


def test_combinacao_sem_regra_propoe_o_status_padrao_com_aviso(corpus):
    analise = analisar_projeto(corpus.projeto, ClienteFalso(proposta()), corpus)
    pontos = criar_pontos(analise)
    while (atual := proximo_ponto_pendente(pontos)).ponto != Ponto.D5:
        if atual.criterio == "novidade":
            atual.alterar("DEMONSTRADA NO RECORTE", MOTIVO, ANALISTA)
        else:
            atual.aceitar(ANALISTA)
    d5 = propor_classificacao(pontos, analise)
    assert d5.valor_proposto == EVIDENCIA_INSUFICIENTE
    assert any("Sem regra aplicável" in l for l in d5.justificativa["lacunas"])
