import dataclasses
import shutil
from pathlib import Path

import pytest

from src.pacote.carregador import (
    PacoteInvalido,
    carregar_projeto,
    dividir_perguntas,
    localizar_projetos,
    numero,
    raiz_do_pacote,
)
from src.verificacao.recalculo import (
    Situacao,
    conferir_projeto,
    conferir_resultado,
    so_contagem_de_entrega,
)
from src.verificacao.referencias import TipoReferencia, resolver_referencia

PACOTE = Path(__file__).resolve().parents[2] / "dados" / "fixtures" / "pacote_exemplo"
PRJ99 = PACOTE / "01_projetos" / "02_casos_para_analise" / "PRJ99"


@pytest.fixture
def projeto():
    return carregar_projeto(PRJ99)


# ----- carregador -----

def test_localiza_projetos_pela_estrutura_do_pacote():
    assert localizar_projetos(PACOTE) == {"PRJ99": PRJ99}


def test_raiz_do_pacote_exige_pasta_de_projetos(tmp_path, monkeypatch):
    monkeypatch.delenv("LEI_DO_BEM_PACOTE", raising=False)
    with pytest.raises(PacoteInvalido, match="LEI_DO_BEM_PACOTE"):
        raiz_do_pacote()
    with pytest.raises(PacoteInvalido, match="01_projetos"):
        raiz_do_pacote(tmp_path)
    assert raiz_do_pacote(PACOTE) == PACOTE


def test_le_csv_com_bom_e_ponto_e_virgula(projeto):
    assert projeto.projeto_id == "PRJ99"
    assert [a.id_atividade for a in projeto.atividades] == ["PRJ99-ATV01", "PRJ99-ATV02"]
    # Campo entre aspas com ponto e virgula interno nao quebra a linha.
    assert projeto.atividades[1].descricao.startswith("Arquivar leituras por versão")
    assert projeto.atividades[1].evidencias_relacionadas == ("PRJ99-EV08", "PRJ99-EV09")


def test_campo_vazio_e_none_e_nunca_zero(projeto):
    assert numero("") is None
    assert numero("null") is None
    assert numero("0") == 0.0
    contador = projeto.medicoes[0]
    assert contador.valor is None
    assert (contador.numerador, contador.denominador) == (18.0, 20.0)
    media = next(r for r in projeto.resultados if r.operacao == "media")
    assert media.taxa_percentual is None


def test_arquivo_inventariado_e_nao_entregue_fica_como_ausente(projeto):
    assert sorted(projeto.ausentes) == [
        "dossie_projeto.pdf",
        "transcricao_entrevista_tecnica.pdf",
    ]
    dossie = next(e for e in projeto.evidencias if e.id_evidencia == "PRJ99-EV01")
    assert dossie.status == "Localizada"
    assert dossie.presente is False


def test_secoes_do_metodo_usam_a_ancora_do_pacote(projeto):
    secao = projeto.secao("evidencias/metodo.md#2")
    assert secao.titulo == "2. Mecanismo e hipótese"
    assert "janela de descarte" in secao.texto
    assert projeto.secao("evidencias/revisao_tecnica.md#material-recebido") is not None


def test_entrevista_e_dividida_por_pergunta():
    texto = (
        "PRJ99 | Entrevista técnica\n"
        " 1. Qual situação motivou o trabalho?\n"
        " Etiquetas lidas\n duas vezes.\n\n"
        " 2. Como ficou a conclusão da rodada?\n"
        " Mantivemos a janela inicial.\n\n"
        " Condição do registro\n"
        " Depoimento de memória.\n"
    )
    secoes = dividir_perguntas("transcricao_entrevista_tecnica.pdf", texto)
    assert [s.ancora for s in secoes] == [
        "transcricao_entrevista_tecnica.pdf#1",
        "transcricao_entrevista_tecnica.pdf#2",
    ]
    assert secoes[0].texto == "Etiquetas lidas duas vezes."
    assert secoes[1].texto == "Mantivemos a janela inicial."


def test_pasta_sem_inventario_e_recusada(tmp_path):
    with pytest.raises(PacoteInvalido, match="inventario_evidencias.csv"):
        carregar_projeto(tmp_path)


# ----- recalculo -----

def test_todos_os_resultados_do_exemplo_conferem(projeto):
    conferencias = {c.ensaio_id: c for c in conferir_projeto(projeto)}
    assert all(c.ok for c in conferencias.values())
    assert conferencias["PRJ99-S01"].valor_recalculado == 33.0
    assert conferencias["PRJ99-S01"].base_recalculada == 40.0
    assert conferencias["PRJ99-S02"].valor_recalculado == 6.0
    # Posto teto(0,95 x 20) = 19, alcancado apenas na classe de 120 ms.
    assert conferencias["PRJ99-S03"].valor_recalculado == 120.0
    assert conferencias["PRJ99-S05"].situacao == Situacao.TRANSCRICAO_CONFERE


def test_valor_adulterado_em_resultados_e_apontado(projeto):
    original = next(r for r in projeto.resultados if r.ensaio_id == "PRJ99-S01")
    adulterado = dataclasses.replace(original, valor=36.0, taxa_percentual=90.0)
    conferencia = conferir_resultado(adulterado, projeto.medicoes)
    assert conferencia.situacao == Situacao.DIVERGE
    assert "recalculado 33.0" in conferencia.detalhe
    assert "taxa" in conferencia.detalhe


def test_resultado_sem_linhas_de_medicao_nao_e_presumido(projeto):
    original = projeto.resultados[0]
    orfao = dataclasses.replace(original, versao="filtro-v9")
    assert conferir_resultado(orfao, projeto.medicoes).situacao == Situacao.SEM_MEDICOES


def test_contagem_de_entrega_nao_pode_ter_taxa(projeto):
    entrega = next(r for r in projeto.resultados if r.natureza == "entrega")
    assert conferir_resultado(entrega, projeto.medicoes).ok
    com_taxa = dataclasses.replace(entrega, taxa_percentual=100.0)
    assert conferir_resultado(com_taxa, projeto.medicoes).situacao == Situacao.DIVERGE


def test_sinal_de_so_contagem_de_entrega(projeto):
    assert so_contagem_de_entrega(projeto) is False
    projeto.resultados = [r for r in projeto.resultados if r.natureza == "entrega"]
    assert so_contagem_de_entrega(projeto) is True


# ----- referencias -----

@pytest.mark.parametrize(
    "referencia, tipo",
    [
        ("PRJ99-EV08", TipoReferencia.EVIDENCIA),
        ("PRJ99-ATV02", TipoReferencia.ATIVIDADE),
        ("PRJ99-S03", TipoReferencia.ENSAIO),
        ("PRJ99-S01-M002", TipoReferencia.MEDICAO),
        ("PRJ99-OBS01", TipoReferencia.OBSERVACAO),
        ("PRJ99-IN001", TipoReferencia.ENTRADA),
        ("PRJ99-CR02", TipoReferencia.CRONOLOGIA),
        ("evidencias/medicoes.csv", TipoReferencia.ARQUIVO),
        ("evidencias/metodo.md#1", TipoReferencia.SECAO),
        ("evidencias/medicoes.csv#PRJ99-S01", TipoReferencia.ENSAIO),
    ],
)
def test_referencias_validas_resolvem(projeto, referencia, tipo):
    resolvida = resolver_referencia(projeto, referencia)
    assert resolvida.existe, resolvida.detalhe
    assert resolvida.tipo == tipo


@pytest.mark.parametrize(
    "referencia",
    [
        "PRJ99-EV77",                       # identificador inventado
        "PRJ21-EV08",                       # de outro projeto
        "evidencias/metodo.md#9",           # secao que nao existe
        "evidencias/logs.csv",              # arquivo nao entregue
        "PRJ99-EV01",                       # inventariado, mas o PDF nao esta na pasta
        "dossie_projeto.pdf",
        "",
    ],
)
def test_referencias_sem_base_nao_resolvem(projeto, referencia):
    assert resolver_referencia(projeto, referencia).existe is False


def test_pdf_ilegivel_conta_como_ausente(tmp_path):
    copia = tmp_path / "PRJ99"
    shutil.copytree(PRJ99, copia)
    (copia / "dossie_projeto.pdf").write_bytes(b"isto nao e um pdf")
    projeto = carregar_projeto(copia)
    assert "dossie_projeto.pdf" in projeto.ausentes
    assert "dossie_projeto.pdf" not in projeto.textos
    assert resolver_referencia(projeto, "PRJ99-EV01").existe is False


def test_caminho_relativo_do_pacote_vale_a_partir_da_raiz_do_projeto(monkeypatch, tmp_path):
    from src.pacote.carregador import raiz_do_pacote

    monkeypatch.setenv("LEI_DO_BEM_PACOTE", "dados/fixtures/pacote_exemplo")
    monkeypatch.chdir(tmp_path)
    assert (raiz_do_pacote() / "01_projetos").is_dir()
