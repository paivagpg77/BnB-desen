from pathlib import Path

from src.documentos.modelos import TIPO_NORMA, TIPO_PROJETO, Trecho
from src.indexacao.bm25 import IndiceBM25
from src.ingestao.chunking import dividir
from src.ingestao.leitores import ler_documento
from src.recuperacao.buscador import Buscador
from src.verificacao.citacoes import (
    Citacao,
    ResultadoVerificacao,
    proposta_tem_base,
    verificar_citacao,
    verificar_todas,
)

FIXTURES = Path(__file__).resolve().parents[2] / "dados" / "fixtures"


def trechos_de_exemplo() -> list[Trecho]:
    norma = ler_documento(FIXTURES / "norma_exemplo.md", doc_id="norma-exemplo", tipo=TIPO_NORMA)
    projeto = ler_documento(
        FIXTURES / "projeto_exemplo" / "dossie.md",
        doc_id="PRJ-TESTE-dossie",
        tipo=TIPO_PROJETO,
        projeto_id="PRJ-TESTE",
    )
    return dividir(norma) + dividir(projeto)


def mapa(trechos: list[Trecho]) -> dict[str, Trecho]:
    return {t.trecho_id: t for t in trechos}


# ----- BM25 e buscador -----

def test_busca_encontra_trecho_com_termos_relevantes():
    indice = IndiceBM25(trechos_de_exemplo())
    resultados = indice.buscar("incerteza tecnica resultado", k=3)
    assert resultados
    assert "incerteza" in resultados[0][1].texto.lower()


def test_busca_sem_termos_uteis_retorna_vazio():
    indice = IndiceBM25(trechos_de_exemplo())
    assert indice.buscar("a de o que", k=3) == []


def test_buscador_separa_normas_de_projeto():
    buscador = Buscador(trechos_de_exemplo())
    normas = buscador.normas("idempotencia")
    assert normas == [] or all(t.tipo == TIPO_NORMA for _, t in normas)
    projeto = buscador.projeto("PRJ-TESTE", "idempotencia")
    assert projeto
    assert all(t.tipo == TIPO_PROJETO and t.projeto_id == "PRJ-TESTE" for _, t in projeto)


def test_buscador_nao_retorna_projeto_de_outro_id():
    buscador = Buscador(trechos_de_exemplo())
    assert buscador.projeto("PRJ-OUTRO", "idempotencia") == []


def test_acentos_nao_atrapalham_a_busca():
    indice = IndiceBM25(trechos_de_exemplo())
    sem_acento = indice.buscar("pesquisa original")
    com_acento = indice.buscar("pesquisa original")
    assert sem_acento == com_acento


# ----- verificacao de citacoes -----

def test_citacao_literal_presente_e_sustentada():
    trechos = mapa(trechos_de_exemplo())
    tid = next(t for t in trechos if t.startswith("norma-exemplo") and "Art. 2" in trechos[t].secao)
    texto_art2 = "desenvolvimento experimental"
    r = verificar_citacao(Citacao("definicao", tid, literal=texto_art2), trechos)
    assert r.resultado == ResultadoVerificacao.SUSTENTADA
    assert r.ok


def test_citacao_literal_inventada_e_barrada():
    trechos = mapa(trechos_de_exemplo())
    tid = next(t for t in trechos if t.startswith("norma-exemplo"))
    r = verificar_citacao(Citacao("x", tid, literal="texto que nao existe na norma"), trechos)
    assert r.resultado == ResultadoVerificacao.LITERAL_NAO_ENCONTRADA
    assert not r.ok


def test_trecho_inexistente_e_barrado():
    r = verificar_citacao(Citacao("x", "nao-existe#001"), mapa(trechos_de_exemplo()))
    assert r.resultado == ResultadoVerificacao.TRECHO_INEXISTENTE


def test_trecho_nao_recuperado_nesta_consulta_e_barrado():
    trechos = mapa(trechos_de_exemplo())
    tid = next(iter(trechos))
    r = verificar_citacao(
        Citacao("qualquer coisa", tid), trechos, recuperados={"outro#001"}
    )
    assert r.resultado == ResultadoVerificacao.TRECHO_NAO_RECUPERADO


def test_afirmacao_sem_relacao_com_o_trecho_nao_e_sustentada():
    trechos = mapa(trechos_de_exemplo())
    tid = next(t for t in trechos if t.startswith("norma-exemplo"))
    r = verificar_citacao(
        Citacao("cotacao de moedas estrangeiras e taxas de juros bancarios", tid), trechos
    )
    assert r.resultado == ResultadoVerificacao.NAO_SUSTENTADA


def test_afirmacao_parafraseada_com_cobertura_suficiente_e_sustentada():
    trechos = mapa(trechos_de_exemplo())
    tid = next(t for t in trechos if t.startswith("norma-exemplo") and "Art. 1" in trechos[t].secao)
    r = verificar_citacao(
        Citacao("pesquisa e a investigacao original planejada para novos conhecimentos", tid),
        trechos,
    )
    assert r.resultado == ResultadoVerificacao.SUSTENTADA


def test_proposta_sem_citacao_nao_tem_base():
    ok, motivo = proposta_tem_base([])
    assert not ok
    assert "Evidencia insuficiente" in motivo


def test_uma_citacao_falha_bloqueia_a_proposta_inteira():
    trechos = mapa(trechos_de_exemplo())
    tid = next(t for t in trechos if t.startswith("norma-exemplo"))
    resultados = verificar_todas(
        [
            Citacao("investigacao original planejada", tid),
            Citacao("texto inventado sem relacao alguma", tid, literal="inventado"),
        ],
        trechos,
    )
    ok, motivo = proposta_tem_base(resultados)
    assert not ok
    assert "literal_nao_encontrada" in motivo


def test_proposta_com_todas_citacoes_validas_tem_base():
    trechos = mapa(trechos_de_exemplo())
    tid = next(t for t in trechos if t.startswith("norma-exemplo") and "Art. 2" in trechos[t].secao)
    resultados = verificar_todas(
        [Citacao("desenvolvimento experimental", tid, literal="desenvolvimento experimental")],
        trechos,
    )
    ok, _ = proposta_tem_base(resultados)
    assert ok
