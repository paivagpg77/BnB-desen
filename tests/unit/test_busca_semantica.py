"""Busca semântica e fusão com a lexical, com um modelo de embeddings falso."""

from pathlib import Path

import pytest

from src import ferramentas
from src.documentos.modelos import TIPO_PROJETO, Trecho
from src.indexacao import vetorial
from src.indexacao.bm25 import IndiceBM25
from src.indexacao.vetorial import ErroDeEmbeddings, IndiceVetorial, embeddings_padrao, fundir
from src.pacote.carregador import carregar_projeto
from src.rag.corpus import montar_corpus, recuperar_contexto
from src.texto.tokens import tokenizar

PACOTE = Path(__file__).resolve().parents[2] / "dados/fixtures/pacote_exemplo"
PRJ99 = PACOTE / "01_projetos/02_casos_para_analise/PRJ99"

# Cada eixo e um conceito; palavras diferentes do mesmo conceito caem no mesmo eixo.
CONCEITOS = (
    {"duplicada", "duplicadas", "repetida", "repetidas", "duas", "vezes"},
    {"etiqueta", "etiquetas", "rotulo", "rotulos"},
    {"janela", "intervalo"},
)


class EmbeddingsFalsos:
    nome = "falso/conceitos"

    def __init__(self):
        self.chamadas = 0

    def codificar(self, textos):
        self.chamadas += 1
        return [
            [float(sum(palavra in conceito for palavra in tokenizar(texto))) for conceito in CONCEITOS]
            for texto in textos
        ]


def _trecho(trecho_id, texto):
    return Trecho(
        trecho_id=trecho_id, doc_id="PRJ00", tipo=TIPO_PROJETO, projeto_id="PRJ00",
        secao=trecho_id, texto=texto,
    )


TRECHOS = [
    _trecho("T1", "As etiquetas eram lidas duas vezes pelo coletor."),
    _trecho("T2", "O relatório mensal foi entregue no prazo."),
    _trecho("T3", "A janela de descarte foi ajustada."),
]


def test_busca_semantica_encontra_o_que_a_lexical_nao_ve():
    consulta = "rótulos com leitura repetida"
    assert IndiceBM25(TRECHOS).buscar(consulta) == []
    encontrados = IndiceVetorial(TRECHOS, EmbeddingsFalsos()).buscar(consulta)
    assert [t.trecho_id for _, t in encontrados] == ["T1"]


def test_busca_semantica_respeita_filtro_e_consulta_vazia():
    indice = IndiceVetorial(TRECHOS, EmbeddingsFalsos())
    assert indice.buscar("   ") == []
    assert indice.buscar("rótulos", filtro=lambda t: t.trecho_id != "T1") == []


def test_fusao_prefere_o_trecho_bem_colocado_nas_duas_buscas():
    a, b, c = TRECHOS
    fundidos = fundir([[(9.0, a), (5.0, b)], [(0.9, b), (0.8, c)]], k=3)
    assert [t.trecho_id for _, t in fundidos] == ["T2", "T1", "T3"]
    assert len(fundir([[(9.0, a), (5.0, b)]], k=1)) == 1


def test_corpus_sem_embeddings_continua_lexical():
    corpus = montar_corpus(carregar_projeto(PRJ99))
    assert corpus.indice_vetorial is None
    assert corpus.buscar("etiquetas coletor", k=3) == corpus.indice.buscar("etiquetas coletor", k=3)


def test_corpus_com_embeddings_funde_as_duas_buscas():
    embeddings = EmbeddingsFalsos()
    corpus = montar_corpus(carregar_projeto(PRJ99), embeddings)
    assert len(corpus.indice_vetorial) == len(corpus.trechos)
    assert embeddings.chamadas == 1                     # os trechos sao codificados uma vez so

    consulta = "rótulos repetidos"                      # nenhuma palavra do projeto
    assert corpus.indice.buscar(consulta) == []
    assert corpus.buscar(consulta)
    # O nucleo obrigatorio e o orcamento valem do mesmo jeito.
    contexto = {t.trecho_id for t in recuperar_contexto(corpus, [consulta], orcamento=0)}
    assert "evidencias/metodo.md#1" in contexto
    assert contexto == {t.trecho_id for t in recuperar_contexto(montar_corpus(carregar_projeto(PRJ99)), [consulta], orcamento=0)}


def test_modelo_de_embeddings_vem_do_ambiente(monkeypatch):
    monkeypatch.delenv(vetorial.VARIAVEL_MODELO, raising=False)
    assert embeddings_padrao() is None
    monkeypatch.setenv(vetorial.VARIAVEL_MODELO, "  ")
    assert embeddings_padrao() is None
    monkeypatch.setenv(vetorial.VARIAVEL_MODELO, "algum/modelo")
    assert embeddings_padrao().nome == "algum/modelo"


def test_modelo_configurado_sem_a_biblioteca_explica_o_que_instalar(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", None)
    with pytest.raises(ErroDeEmbeddings, match="semantica"):
        vetorial.EmbeddingsLocais("algum/modelo").codificar(["texto"])


def test_ferramenta_de_busca_usa_o_modelo_configurado(monkeypatch):
    monkeypatch.setenv("LEI_DO_BEM_PACOTE", str(PACOTE))
    monkeypatch.setattr(ferramentas, "embeddings_padrao", EmbeddingsFalsos)
    ferramentas._corpus.cache_clear()
    try:
        achados = ferramentas.buscar_evidencias("PRJ99", "rótulos repetidos")
    finally:
        ferramentas._corpus.cache_clear()
    assert achados and all(a["pontuacao"] > 0 for a in achados)
