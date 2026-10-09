"""
Testes contra a massa do hackathon. A massa e confidencial e fica fora do
repositorio: estes testes so rodam com LEI_DO_BEM_PACOTE apontando para a pasta
extraida do pacote.
"""

import os

import pytest

from src.pacote.carregador import carregar_projeto, localizar_projetos, raiz_do_pacote
from src.pacote.historicos import carregar_historicos
from src.verificacao.recalculo import conferir_projeto
from src.verificacao.referencias import resolver_referencia

pytestmark = pytest.mark.skipif(
    not os.environ.get("LEI_DO_BEM_PACOTE"),
    reason="defina LEI_DO_BEM_PACOTE para rodar contra a massa do hackathon",
)


@pytest.fixture(scope="module")
def raiz():
    return raiz_do_pacote()


@pytest.fixture(scope="module")
def projetos(raiz):
    return {pid: carregar_projeto(pasta) for pid, pasta in localizar_projetos(raiz).items()}


def test_carrega_os_quarenta_projetos_sem_arquivo_ausente(projetos):
    assert len(projetos) == 40
    for projeto in projetos.values():
        assert projeto.ausentes == [], projeto.projeto_id
        assert len(projeto.evidencias) == 14
        assert len(projeto.atividades) == 8
        assert projeto.medicoes and projeto.resultados


def test_entrevista_tem_sete_respostas_enderecaveis(projetos):
    for projeto in projetos.values():
        perguntas = [
            s for s in projeto.secoes
            if s.arquivo == "transcricao_entrevista_tecnica.pdf"
        ]
        assert len(perguntas) == 7, projeto.projeto_id
        assert all(s.texto for s in perguntas), projeto.projeto_id


def test_todo_resultado_confere_com_as_medicoes(projetos):
    falhas = [
        (c.ensaio_id, c.situacao.value, c.detalhe)
        for projeto in projetos.values()
        for c in conferir_projeto(projeto)
        if not c.ok
    ]
    assert falhas == []


def test_fontes_dos_pareceres_historicos_resolvem(raiz, projetos):
    historicos = carregar_historicos(raiz)
    assert len(historicos) == 20
    falhas = []
    for projeto_id, parecer in historicos.items():
        fontes = list(parecer.fontes_decisivas) + [c.fonte for c in parecer.criterios]
        for fonte in fontes:
            resolvida = resolver_referencia(projetos[projeto_id], fonte)
            if not resolvida.existe:
                falhas.append((projeto_id, fonte, resolvida.detalhe))
    assert falhas == []


def test_regra_de_classificacao_reproduz_os_vinte_historicos(raiz):
    from src.motor.regras import ROTULO_CRITERIO, derivar_classificacao

    por_rotulo = {rotulo: criterio for criterio, rotulo in ROTULO_CRITERIO.items()}
    erros = []
    for projeto_id, parecer in carregar_historicos(raiz).items():
        estados = {por_rotulo[c.criterio]: c.estado for c in parecer.criterios}
        derivada, _ = derivar_classificacao(estados)
        if derivada != parecer.classificacao:
            erros.append((projeto_id, parecer.classificacao, derivada))
    assert erros == []


def test_corpus_cobre_as_fontes_dos_historicos_e_cabe_no_contexto(raiz, projetos):
    from src.motor.analisador import CONSULTAS
    from src.rag.corpus import ORCAMENTO_PADRAO, montar_corpus, recuperar_contexto

    historicos = carregar_historicos(raiz)
    for projeto_id, projeto in projetos.items():
        corpus = montar_corpus(projeto)
        contexto = recuperar_contexto(corpus, CONSULTAS.values())
        lidos = {t.trecho_id for t in contexto}
        # O nucleo obrigatorio nao pode passar muito do orcamento em nenhum projeto.
        assert sum(len(t.texto) for t in contexto) < 2 * ORCAMENTO_PADRAO, projeto_id
        assert {"dossie_projeto.pdf", "evidencias/metodo.md#1", "evidencias/metodo.md#2"} <= lidos
        assert len([t for t in lidos if t.startswith("transcricao_entrevista_tecnica.pdf#")]) == 7
        for criterio in historicos[projeto_id].criterios if projeto_id in historicos else ():
            if "#" in criterio.fonte:
                assert corpus.normalizar(criterio.fonte) in lidos, (projeto_id, criterio.fonte)
