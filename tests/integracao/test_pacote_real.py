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
