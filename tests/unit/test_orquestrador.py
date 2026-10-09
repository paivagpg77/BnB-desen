import json
from pathlib import Path

import pytest

from src.llm import cliente as llm
from src.llm.cliente import ErroLLM, LimiteDeUso, RespostaLLM
from src.motor import orquestrador
from src.motor.fluxo import criar_pontos
from src.motor.analisador import preparar_analise
from src.motor.orquestrador import (
    Papeis,
    analisar_com_orquestracao,
    mensagem_de_confronto,
    papeis_padrao,
)
from src.motor.regras import NAO_ELEGIVEL, Criterio
from src.pacote.carregador import carregar_projeto
from src.rag.corpus import montar_corpus
from tests.unit.proposta_exemplo import proposta

PRJ99 = (
    Path(__file__).resolve().parents[2]
    / "dados/fixtures/pacote_exemplo/01_projetos/02_casos_para_analise/PRJ99"
)

CONFRONTO = {
    "divergencias": [
        {"depoimento": "Trinta e cinco leituras corretas.",
         "fonte_depoimento": "evidencias/revisao_tecnica.md#material-recebido",
         "registro": "33 de 40 em filtro-v1.", "fonte_registro": "PRJ99-S01",
         "prevalece": "o registro, por ser primário"},
    ],
    "atividades": [
        {"id_atividade": "PRJ99-ATV01", "natureza": "apoio", "justificativa": "Caracteriza o problema."},
        {"id_atividade": "PRJ99-ATV02", "natureza": "rotina", "justificativa": "Arquiva medições."},
    ],
}
AUDITORIA = {
    "auditoria": [
        {"criterio": "novidade", "veredito": "sustenta", "comentario": "A seção 1 descreve o descarte por janela."},
        {"criterio": "criatividade", "veredito": "sustenta", "comentario": "Confere com a seção 2."},
        {"criterio": "incerteza", "veredito": "sustenta_em_parte",
         "comentario": "A seção 2 não fala em hipótese; só no ajuste da janela."},
        {"criterio": "sistematicidade", "veredito": "sustenta", "comentario": "Confere."},
        {"criterio": "transferencia", "veredito": "sustenta", "comentario": "Confere."},
    ]
}


class Modelo:
    """Modelo falso de um provedor: devolve a resposta dada e conta tokens."""

    def __init__(self, provedor, resposta):
        self.provedor = provedor
        self.modelo = f"{provedor}/falso"
        self._resposta = resposta
        self.chamadas: list[tuple[str, str]] = []

    def completar(self, sistema, usuario, esquema=None):
        self.chamadas.append((sistema, usuario))
        if isinstance(self._resposta, Exception):
            raise self._resposta
        return RespostaLLM(
            texto=json.dumps(self._resposta, ensure_ascii=False),
            modelo=self.modelo,
            uso={"prompt_tokens": len(usuario) // 4, "completion_tokens": 50},
            provedor=self.provedor,
        )


@pytest.fixture
def corpus():
    return montar_corpus(carregar_projeto(PRJ99))


def analista_sem_listas():
    return proposta(divergencias=[], atividades=[])


def test_cada_modelo_recebe_so_a_sua_parte(corpus):
    gemini = Modelo("gemini", analista_sem_listas())
    groq = Modelo("groq", CONFRONTO)
    openrouter = Modelo("openrouter", AUDITORIA)
    analise = analisar_com_orquestracao(
        corpus.projeto, Papeis(analista=gemini, confronto=groq, auditor=openrouter), corpus
    )

    do_analista, do_confronto, do_auditor = (m.chamadas[0][1] for m in (gemini, groq, openrouter))
    # O analista e dispensado do confronto e nao recebe as atividades.
    assert "Devolva `divergencias` e `atividades` como listas vazias" in do_analista
    assert "[PRJ99-ATV01]" not in do_analista
    # O confronto recebe so entrevista, registros e atividades: nada de regras ou exemplos.
    assert "[PRJ99-ATV01]" in do_confronto and "[PRJ99-S01]" in do_confronto
    assert "# REGRAS" not in do_confronto and "regras-v1" not in do_confronto
    assert len(do_confronto) < len(do_analista) / 2
    # O auditor recebe as justificativas e o texto das fontes citadas.
    assert "Justificativa: O coletor já oferecia o descarte por janela." in do_auditor
    assert "[evidencias/metodo.md#1]" in do_auditor
    assert len(do_auditor) < len(do_analista) / 2

    assert [(p.papel, p.provedor, p.concluido) for p in analise.orquestracao.papeis] == [
        ("analista", "gemini", True), ("confronto", "groq", True), ("auditor", "openrouter", True),
    ]
    assert all(p.tokens_entrada > 0 and p.chamadas == 1 for p in analise.orquestracao.papeis)
    assert analise.modelo == "gemini/falso"
    assert analise.classificacao_derivada == NAO_ELEGIVEL


def test_auditor_recebe_cada_fonte_citada_inteira_e_uma_vez_so(corpus):
    openrouter = Modelo("openrouter", AUDITORIA)
    analise = analisar_com_orquestracao(
        corpus.projeto,
        Papeis(analista=Modelo("gemini", analista_sem_listas()), auditor=openrouter),
        corpus,
    )
    do_auditor = openrouter.chamadas[0][1]
    citadas = {f for c in analise.proposta.criterios for f in c.fontes}
    assert citadas
    for fonte in citadas:
        # Fonte cortada ou omitida faria o auditor acusar falta do que ele nao leu.
        assert do_auditor.count(f"[{fonte}] (") == 1
        assert corpus.trechos[fonte].texto in do_auditor
    assert "texto cortado" not in do_auditor


def test_resultado_do_confronto_entra_na_proposta_e_e_conferido(corpus):
    achados = json.loads(json.dumps(CONFRONTO))
    achados["divergencias"].append(
        {"depoimento": "x", "fonte_depoimento": "PRJ99-EV77", "registro": "y",
         "fonte_registro": "PRJ99-S01", "prevalece": "o registro"}
    )
    analise = analisar_com_orquestracao(
        corpus.projeto,
        Papeis(analista=Modelo("gemini", analista_sem_listas()), confronto=Modelo("groq", achados)),
        corpus,
    )
    assert [d.fonte_registro for d in analise.proposta.divergencias] == ["PRJ99-S01"]
    assert [a.id_atividade for a in analise.proposta.atividades] == ["PRJ99-ATV01", "PRJ99-ATV02"]
    # A divergencia com fonte inventada cai na mesma conferencia das demais fontes.
    assert analise.fontes_descartadas["divergencias"] == ["PRJ99-EV77"]


def test_auditoria_vira_alerta_no_criterio_e_nao_muda_o_estado(corpus):
    analise = analisar_com_orquestracao(
        corpus.projeto,
        Papeis(analista=Modelo("gemini", analista_sem_listas()), auditor=Modelo("openrouter", AUDITORIA)),
        corpus,
    )
    assert analise.proposta.criterio(Criterio.INCERTEZA).estado == "NÃO CARACTERIZADA"
    assert any(a.startswith("Incerteza tecnológica: segundo o modelo auditor") for a in analise.avisos)
    pontos = {p.decision_id: p for p in criar_pontos(analise)}
    auditoria = pontos["PRJ99-D2-incerteza"].justificativa["auditoria"]
    assert auditoria["veredito"] == "sustenta_em_parte"
    assert auditoria["texto"].startswith(
        "Auditoria das fontes: as fontes citadas sustentam só parte da justificativa, porque a seção 2"
    )
    assert "analista: gemini (gemini/falso); auditor: openrouter" in " ".join(
        pontos["PRJ99-D1"].justificativa["como"]
    )


def test_papel_secundario_que_falha_e_assumido_pelo_outro_modelo(corpus):
    class DoisPapeis(Modelo):
        """Responde ao confronto ou a auditoria conforme o prompt recebido."""

        def completar(self, sistema, usuario, esquema=None):
            self._resposta = AUDITORIA if "Você audita" in sistema else CONFRONTO
            return super().completar(sistema, usuario, esquema)

    groq = DoisPapeis("groq", None)
    analise = analisar_com_orquestracao(
        corpus.projeto,
        Papeis(
            analista=Modelo("gemini", analista_sem_listas()),
            confronto=groq,
            auditor=Modelo("openrouter", LimiteDeUso("limite atingido")),
        ),
        corpus,
    )
    assert [(p.papel, p.provedor, p.concluido) for p in analise.orquestracao.papeis] == [
        ("analista", "gemini", True), ("confronto", "groq", True),
        ("auditor", "openrouter", False), ("auditor", "groq", True),
    ]
    assert len(analise.orquestracao.auditoria) == 5
    assert any("a auditoria foi feita por groq" in a for a in analise.avisos)

    # E o inverso: o confronto falha e o auditor assume.
    openrouter = DoisPapeis("openrouter", None)
    analise = analisar_com_orquestracao(
        corpus.projeto,
        Papeis(
            analista=Modelo("gemini", analista_sem_listas()),
            confronto=Modelo("groq", LimiteDeUso("limite atingido")),
            auditor=openrouter,
        ),
        corpus,
    )
    assert [a.id_atividade for a in analise.proposta.atividades] == ["PRJ99-ATV01", "PRJ99-ATV02"]
    assert any("a tarefa foi feita por openrouter" in a for a in analise.avisos)


def test_identificador_entre_colchetes_e_aceito(corpus):
    assert corpus.normalizar("[PRJ99-S01]") == "PRJ99-S01"
    assert corpus.normalizar("[evidencias/metodo.md#2]") == "evidencias/metodo.md#2"


def test_falha_do_confronto_ou_do_auditor_nao_derruba_a_analise(corpus):
    analise = analisar_com_orquestracao(
        corpus.projeto,
        Papeis(
            analista=Modelo("gemini", analista_sem_listas()),
            confronto=Modelo("groq", LimiteDeUso("limite atingido")),
            auditor=Modelo("openrouter", ErroLLM("fora do ar")),
        ),
        corpus,
    )
    assert analise.classificacao_derivada == NAO_ELEGIVEL
    # Cada papel secundario tentou o proprio modelo e depois o do outro papel.
    assert [(p.papel, p.provedor, p.concluido) for p in analise.orquestracao.papeis] == [
        ("analista", "gemini", True),
        ("confronto", "groq", False), ("confronto", "openrouter", False),
        ("auditor", "openrouter", False), ("auditor", "groq", False),
    ]
    assert any("modelo do confronto (openrouter) não respondeu" in a for a in analise.avisos)
    assert any("auditor (openrouter) não respondeu" in a for a in analise.avisos)
    assert analise.orquestracao.auditoria == []


def test_falha_do_analista_interrompe(corpus):
    with pytest.raises(ErroLLM, match="fora do ar"):
        analisar_com_orquestracao(
            corpus.projeto,
            Papeis(analista=Modelo("gemini", ErroLLM("fora do ar")), confronto=Modelo("groq", CONFRONTO)),
            corpus,
        )


def test_com_um_so_modelo_o_analista_faz_tudo(corpus):
    unico = Modelo("openrouter", proposta())
    analise = analisar_com_orquestracao(corpus.projeto, Papeis(analista=unico), corpus)
    assert "Devolva `divergencias`" not in unico.chamadas[0][1]
    assert [a.id_atividade for a in analise.proposta.atividades] == ["PRJ99-ATV01", "PRJ99-ATV02"]
    assert [p.papel for p in analise.orquestracao.papeis] == ["analista"]


@pytest.mark.parametrize(
    "chaves, esperado",
    [
        ({"GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"}, ("gemini", "groq", "openrouter")),
        ({"OPENROUTER_API_KEY"}, ("openrouter", None, None)),
        # Sozinho, o provedor com limite de tamanho repete de papel em chamadas menores.
        ({"GROQ_API_KEY"}, ("groq", "groq", "groq")),
        ({"GROQ_API_KEY", "OPENROUTER_API_KEY"}, ("openrouter", "groq", None)),
        ({"GEMINI_API_KEY", "OPENROUTER_API_KEY"}, ("gemini", "openrouter", None)),
    ],
)
def test_papeis_sao_distribuidos_conforme_as_chaves(monkeypatch, chaves, esperado):
    for provedor in llm.PROVEDORES.values():
        monkeypatch.delenv(provedor.variavel_chave, raising=False)
    for chave in chaves:
        monkeypatch.setenv(chave, "k")
    papeis = papeis_padrao()
    nomes = tuple(getattr(c, "provedor", None) for c in (papeis.analista, papeis.confronto, papeis.auditor))
    assert nomes == esperado


def test_sem_nenhuma_chave_o_erro_diz_o_que_preencher(monkeypatch):
    for provedor in llm.PROVEDORES.values():
        monkeypatch.delenv(provedor.variavel_chave, raising=False)
    with pytest.raises(ErroLLM, match="GEMINI_API_KEY"):
        papeis_padrao()


def test_mensagem_de_confronto_sem_entrevista_avisa(corpus):
    assert "# ENTREVISTA (depoimento de memória)\n\nNão entregue." in mensagem_de_confronto(corpus)
    assert orquestrador.PREFERENCIAS["analista"][0] == "gemini"


def test_cada_papel_tem_os_outros_provedores_como_reserva(monkeypatch):
    for provedor in llm.PROVEDORES.values():
        monkeypatch.setenv(provedor.variavel_chave, "k")
        monkeypatch.setenv(provedor.variavel_modelo, f"{provedor.nome}-m")
    papeis = papeis_padrao()
    filas = {
        papel: [c.provedor for c in getattr(papeis, papel)._clientes]
        for papel in ("analista", "confronto", "auditor")
    }
    assert filas == {
        "analista": ["gemini", "openrouter", "groq"],
        "confronto": ["groq", "openrouter", "gemini"],
        "auditor": ["openrouter", "groq", "gemini"],
    }


def test_analista_sem_cota_e_substituido_e_o_analista_humano_e_avisado(corpus):
    gemini = Modelo("gemini", llm.LimiteDeUso("429"))
    reserva = Modelo("openrouter", proposta())
    fila = llm.ClienteComReserva([gemini, reserva], fora_da_fila={})
    analise = analisar_com_orquestracao(corpus.projeto, Papeis(analista=fila), corpus)

    (papel,) = analise.orquestracao.papeis
    assert (papel.papel, papel.provedor, papel.concluido) == ("analista", "openrouter", True)
    assert analise.modelo == "openrouter/falso"
    assert (
        "Papel de analista: gemini (gemini/falso) está sem cota. "
        "Quem respondeu: openrouter (openrouter/falso)."
    ) in analise.avisos


def test_modelo_com_limite_de_tamanho_faz_o_papel_de_analista_com_mensagem_reduzida(corpus):
    pacote = PRJ99.parents[2]
    inteira = preparar_analise(corpus.projeto, corpus, pacote)
    reduzida = preparar_analise(corpus.projeto, corpus, pacote, reduzida=True)
    limite = len(reduzida["sistema"]) + len(reduzida["mensagem"]) + 10
    assert len(inteira["mensagem"]) > len(reduzida["mensagem"]) + 10

    class Pequeno(Modelo):
        limite_caracteres = limite

    groq = Pequeno("groq", proposta())
    fila = llm.ClienteComReserva([Modelo("gemini", llm.LimiteDeUso("429")), groq], fora_da_fila={})
    analise = analisar_com_orquestracao(corpus.projeto, Papeis(analista=fila), corpus, pacote)

    sistema, mensagem = groq.chamadas[0]
    assert len(sistema) + len(mensagem) <= limite
    assert sistema == reduzida["sistema"] != inteira["sistema"]
    assert "Nenhum trecho disponível neste ambiente." in mensagem      # sem orientações nem exemplos
    assert "evidencias/metodo.md#1" in mensagem                         # evidência obrigatória continua
    assert analise.orquestracao.papeis[0].provedor == "groq"
    assert analise.orientacoes == [] and analise.exemplos == []
    assert any("recebeu a mensagem reduzida" in a for a in analise.avisos)


def test_rodada_pode_ser_restrita_a_alguns_provedores(monkeypatch):
    for provedor in llm.PROVEDORES.values():
        monkeypatch.setenv(provedor.variavel_chave, "k")
    monkeypatch.setenv("LEI_DO_BEM_PROVEDORES", "groq")
    papeis = papeis_padrao()
    assert [c.provedor for c in papeis.analista._clientes] == ["groq"] * len(papeis.analista._clientes)
    assert (papeis.confronto.provedor, papeis.auditor.provedor) == ("groq", "groq")
