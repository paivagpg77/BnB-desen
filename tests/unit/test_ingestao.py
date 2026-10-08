from pathlib import Path

import pytest

from src.documentos.modelos import TIPO_NORMA, TIPO_PROJETO
from src.ingestao.chunking import dividir
from src.ingestao.leitores import FormatoNaoSuportado, ler_documento

FIXTURES = Path(__file__).resolve().parents[2] / "dados" / "fixtures"


def test_le_norma_markdown_e_mantem_origem_e_versao():
    doc = ler_documento(
        FIXTURES / "norma_exemplo.md",
        doc_id="norma-exemplo",
        tipo=TIPO_NORMA,
        versao="fictcia-v1",
    )
    assert doc.tipo == TIPO_NORMA
    assert doc.versao == "fictcia-v1"
    assert doc.origem == "norma_exemplo.md"
    assert "Art. 2" in doc.texto


def test_le_csv_transforma_cada_linha_em_secao():
    doc = ler_documento(
        FIXTURES / "projeto_exemplo" / "atividades.csv",
        doc_id="PRJ-TESTE-atividades",
        tipo=TIPO_PROJETO,
        projeto_id="PRJ-TESTE",
    )
    assert "## A02" in doc.texto
    assert "tipo_declarado: pesquisa" in doc.texto


def test_pdf_nao_suportado_avisa_claramente(tmp_path):
    arquivo = tmp_path / "x.pdf"
    arquivo.write_bytes(b"%PDF-1.4")
    with pytest.raises(FormatoNaoSuportado, match="PDF ainda nao"):
        ler_documento(arquivo, doc_id="x", tipo=TIPO_PROJETO)


def test_extensao_desconhecida_e_recusada(tmp_path):
    arquivo = tmp_path / "x.xyz"
    arquivo.write_text("abc", encoding="utf-8")
    with pytest.raises(FormatoNaoSuportado):
        ler_documento(arquivo, doc_id="x", tipo=TIPO_PROJETO)


def test_chunking_divide_por_artigo_com_ids_estaveis():
    doc = ler_documento(
        FIXTURES / "norma_exemplo.md", doc_id="norma-exemplo", tipo=TIPO_NORMA
    )
    trechos = dividir(doc)
    secoes = [t.secao for t in trechos]
    assert any(s.startswith("Art. 1") for s in secoes)
    assert any(s.startswith("Art. 2") for s in secoes)
    assert trechos[0].trecho_id == "norma-exemplo#001"
    assert all(t.trecho_id.startswith("norma-exemplo#") for t in trechos)


def test_chunking_preserva_metadados_do_documento():
    doc = ler_documento(
        FIXTURES / "projeto_exemplo" / "dossie.md",
        doc_id="PRJ-TESTE-dossie",
        tipo=TIPO_PROJETO,
        projeto_id="PRJ-TESTE",
        versao="v1",
    )
    trechos = dividir(doc)
    assert trechos, "o dossie de exemplo deve gerar trechos"
    assert all(t.projeto_id == "PRJ-TESTE" for t in trechos)
    assert all(t.tipo == TIPO_PROJETO for t in trechos)
    assert all(t.versao == "v1" for t in trechos)


def test_chunking_quebra_secao_longa_por_paragrafo():
    from src.documentos.modelos import Documento

    paragrafo = "Frase com varias palavras para ocupar espaco no texto. " * 10
    texto = "## Secao longa\n\n" + "\n\n".join([paragrafo] * 6)
    doc = Documento(doc_id="longo", tipo=TIPO_PROJETO, titulo="longo", texto=texto,
                    projeto_id="PRJ-X")
    trechos = dividir(doc, tamanho_maximo=600)
    assert len(trechos) > 1
    assert all(len(t.texto) <= 700 for t in trechos)  # tolera o titulo da secao
