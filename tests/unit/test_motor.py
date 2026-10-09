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

PACOTE = Path(__file__).resolve().parents[2] / "dados/fixtures/pacote_exemplo"
PRJ99 = PACOTE / "01_projetos/02_casos_para_analise/PRJ99"
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


# ----- biblioteca de referencia -----

def test_orientacoes_trazem_o_nucleo_do_guia():
    from src.rag.biblioteca import buscar_orientacoes

    secoes = [t.secao for t in buscar_orientacoes(PACOTE)]
    assert secoes[0].endswith("· Critérios de análise")
    assert any(s.endswith("· Elegível") for s in secoes)


def test_um_exemplo_por_classificacao_sem_o_proprio_projeto():
    from src.rag.biblioteca import exemplos_de_referencia

    assert [t.trecho_id for t in exemplos_de_referencia(PACOTE)] == [
        "historico:PRJ97", "historico:PRJ96",
    ]
    assert [t.trecho_id for t in exemplos_de_referencia(PACOTE, excluir="PRJ97")] == [
        "historico:PRJ98", "historico:PRJ96",
    ]


def test_analise_leva_orientacoes_e_exemplos_mas_nao_aceita_fonte_de_exemplo(corpus):
    from src.rag.biblioteca import buscar_orientacoes

    # O nucleo do guia nao vai no prompt: a base de regras ja cobre esse conteudo.
    recuperadas = [t.trecho_id for t in buscar_orientacoes(PACOTE, com_nucleo=False)]
    orientacao = recuperadas[0]
    assert "guia-participante#002" not in recuperadas

    dados = proposta()
    dados["criterios"][0]["fontes"] = ["historico:PRJ96", "evidencias/metodo.md#1"]
    dados["criterios"][1]["regra"] = orientacao
    cliente = ClienteFalso(dados)
    analise = analisar_projeto(corpus.projeto, cliente, corpus, raiz=PACOTE)

    usuario = cliente.chamadas[0][1]
    assert "# ORIENTAÇÕES DO DESAFIO" in usuario and f"[{orientacao}]" in usuario
    assert "# EXEMPLOS DE REFERÊNCIA" in usuario and "[historico:PRJ97]" in usuario
    assert analise.exemplos == ["historico:PRJ97", "historico:PRJ96"]
    # Orientacao do desafio pode ser citada como regra; fonte de exemplo, nunca.
    assert analise.proposta.criterio(Criterio.CRIATIVIDADE).regra == orientacao
    assert analise.proposta.criterio(Criterio.NOVIDADE).fontes == ["evidencias/metodo.md#1"]
    assert analise.fontes_descartadas["novidade"] == ["historico:PRJ96"]
    como = " ".join(criar_pontos(analise)[0].justificativa["como"])
    assert "PRJ97, PRJ96" in como and "semelhança" in como


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


def test_criterios_sem_o_campo_criterio_sao_aceitos_pela_ordem(corpus):
    dados = proposta()
    for avaliacao in dados["criterios"]:
        del avaliacao["criterio"]
    cliente = ClienteFalso(dados)
    analise = analisar_projeto(corpus.projeto, cliente, corpus)
    assert len(cliente.chamadas) == 1
    assert analise.proposta.criterio(Criterio.INCERTEZA).estado == "NÃO CARACTERIZADA"


def test_criterios_como_objeto_sao_aceitos_pela_chave(corpus):
    dados = proposta()
    dados["criterios"] = {c.pop("criterio"): c for c in reversed(dados["criterios"])}
    analise = analisar_projeto(corpus.projeto, ClienteFalso(dados), corpus)
    assert analise.proposta.criterio(Criterio.TRANSFERENCIA).estado == "DOCUMENTADA PARA A CONFIGURAÇÃO"


def test_varias_fontes_no_mesmo_campo_sao_separadas(corpus):
    dados = proposta()
    dados["criterios"][0]["fontes"] = ["evidencias/metodo.md#1; PRJ99-S01", "PRJ99-OBS01 e PRJ99-EV77"]
    analise = analisar_projeto(corpus.projeto, ClienteFalso(dados), corpus)
    assert analise.proposta.criterio(Criterio.NOVIDADE).fontes == [
        "evidencias/metodo.md#1", "PRJ99-S01", "PRJ99-OBS01",
    ]
    assert analise.fontes_descartadas["novidade"] == ["PRJ99-EV77"]


def test_apresentacao_da_conferencia_e_das_fontes(corpus):
    from src import apresentacao as ap
    from src.verificacao.recalculo import conferir_projeto

    assert ap.numero(240000) == "240.000" and ap.numero(0.82) == "0,82" and ap.numero(None) == "vazio"
    assert ap.leitura_do_resultado(96, 240000, "contagem", "casos") == "96 de 240.000 casos (0,04%)"
    assert ap.leitura_do_resultado(120, 20, "percentil_95", "ms") == "120 ms"
    assert ap.natureza_da_fonte(corpus, "PRJ99-S01")[:2] == ("registro primário", "green")
    assert ap.natureza_da_fonte(corpus, "regras-v1#002")[0] == "regra da ferramenta"
    assert ap.agrupar_fontes([
        {"afirmacao": "A", "trecho_id": "x"}, {"afirmacao": "B", "trecho_id": "y"},
        {"afirmacao": "A", "trecho_id": "z"}, {"afirmacao": "A", "trecho_id": "x"},
    ]) == [("A", ["x", "z"]), ("B", ["y"])]
    motivos = {l["Fonte citada"]: l["Por que foi descartada"] for l in ap.fontes_descartadas(corpus, {
        "novidade": ["evidencias/entradas.csv", "PRJ99-EV77", "historico:PRJ96", "PRJ99-CR02"],
    })}
    assert motivos["evidencias/entradas.csv"].startswith("Cita um arquivo inteiro")
    assert motivos["PRJ99-EV77"] == "Não existe neste projeto."
    assert motivos["historico:PRJ96"].startswith("É de um parecer histórico")
    assert motivos["PRJ99-CR02"].startswith("Existe no projeto")
    assert ap.nome_do_ponto("incerteza") == "Incerteza tecnológica"
    assert ap.texto_em_blocos(
        "Contexto\nUm serviço lento consumia as\nconexões dos demais.\n- item um\nLimite\nSem cobertura."
    ) == [
        ("titulo", "Contexto"), ("paragrafo", "Um serviço lento consumia as conexões dos demais."),
        ("item", "item um"), ("titulo", "Limite"), ("paragrafo", "Sem cobertura."),
    ]


def test_arquivo_tabular_inteiro_pode_ser_citado(corpus):
    dados = proposta()
    dados["criterios"][3]["fontes"] = ["evidencias/medicoes.csv", "evidencias/resultados.csv"]
    analise = analisar_projeto(corpus.projeto, ClienteFalso(dados), corpus)
    assert analise.proposta.criterio(Criterio.SISTEMATICIDADE).fontes == [
        "evidencias/medicoes.csv", "evidencias/resultados.csv",
    ]
    assert "sistematicidade" not in analise.fontes_descartadas
    assert "33 casos" in corpus.trechos["evidencias/resultados.csv"].texto


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
    assert "não encontrada na base" not in dossie
    assert "`evidencias/metodo.md#1`" in dossie
    assert f"`{REGRA_NOVIDADE}`" in dossie
    assert "falso/modelo" in dossie
    assert "- Analista: ANL-01" in dossie


def test_cada_ponto_tem_parecer_em_frase_com_o_motivo(corpus):
    analise = analisar_projeto(corpus.projeto, ClienteFalso(proposta()), corpus)
    pontos = {p.decision_id: p for p in criar_pontos(analise)}
    parecer = lambda chave: pontos[chave].justificativa["parecer"]  # noqa: E731

    assert parecer("PRJ99-D2-novidade") == (
        "A novidade não está demonstrada, porque o coletor já oferecia o descarte por janela."
    )
    assert parecer("PRJ99-D2-sistematicidade").startswith(
        "O trabalho está documentado como aceite, não como investigação, porque quarenta leituras"
    )
    assert parecer("PRJ99-D1").startswith("Etiquetas eram lidas duas vezes pelo coletor. Antes do projeto:")
    assert parecer("PRJ99-D3") == "1 atividade de rotina (PRJ99-ATV02). 1 atividade de apoio (PRJ99-ATV01)."
    assert "1 evidência contrária" in parecer("PRJ99-D4") and "1 lacuna" in parecer("PRJ99-D4")
    assert pontos["PRJ99-D2-novidade"].justificativa["titulo"] == "D2 · Novidade"

    lista = list(pontos.values())
    while (atual := proximo_ponto_pendente(lista)).ponto != Ponto.D5:
        atual.aceitar(ANALISTA)
    d5 = propor_classificacao(lista, analise)
    assert d5.justificativa["parecer"].startswith(
        "Não elegível, porque novidade, criatividade e incerteza tecnológica têm conclusão negativa"
    )
    assert "Critérios confirmados: a novidade não está demonstrada;" in d5.justificativa["parecer"]
    # O modelo chegou a mesma classe, entao a justificativa dele acompanha.
    assert d5.justificativa["parecer"].endswith("O trabalho ajustou um parâmetro de recurso existente.")


def test_motivo_mantem_siglas_e_palavras_do_analista():
    from src.motor.linguagem import com_motivo, frase_da_decisao

    assert com_motivo("Elegível", "GW-7 já descreve o recurso.") == "Elegível, porque GW-7 já descreve o recurso."
    assert com_motivo("Elegível", "A equipe testou.") == "Elegível, porque a equipe testou."
    assert com_motivo("Elegível", "") == "Elegível."
    frase = frase_da_decisao("alterada", "ANL-02", "INVESTIGADA", "NÃO CARACTERIZADA", "Maria conferiu o runbook.")
    assert frase == (
        "ANL-02 alterou a proposta de “INVESTIGADA” para “NÃO CARACTERIZADA”. "
        "Motivo registrado: Maria conferiu o runbook."
    )


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
    # O modelo sugeriu outra classe: a justificativa dele nao entra no parecer.
    assert d5.justificativa["parecer"].startswith("Com ressalvas, porque há pesquisa e desenvolvimento")
    assert "ajustou um parâmetro" not in d5.justificativa["parecer"]


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
