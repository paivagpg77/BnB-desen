"""
Orquestracao de tres modelos, cada um com uma parte diferente do trabalho.

Nenhum modelo repete o que outro faz, e so o analista recebe o contexto
inteiro do projeto. Os outros dois recebem recortes pequenos:

- Analista: avalia os cinco criterios, o entendimento, as evidencias
  favoraveis e contrarias, as lacunas e a classificacao.
- Confronto: compara a entrevista com os registros (divergencias) e classifica
  as atividades. Recebe so entrevista, ensaios, metodo, observacoes,
  cronologia e atividades.
- Auditor: recebe as justificativas do analista e o texto das fontes citadas e
  diz se as fontes sustentam o que foi afirmado. Complementa a conferencia
  automatica, que so verifica se a fonte existe.

Analista e confronto rodam ao mesmo tempo; o auditor roda depois, sobre a
proposta ja conferida. Nenhum dos tres decide: tudo vira proposta para o
analista humano, e a classificacao continua vindo da regra sobre o que ele
confirmar.

Papeis padrao: Gemini como analista (contexto grande), Groq no confronto
(entrada curta, resposta rapida) e OpenRouter como auditor. Faltando a chave
de um provedor, os papeis sao redistribuidos; com um so provedor, o analista
faz tambem o confronto e nao ha auditoria.

Cada papel tem uma fila: o provedor titular e, atras dele, os outros com chave
no .env. Se o titular fica sem cota ou recusa a chamada, a mesma pergunta vai
para o seguinte, e a troca aparece como aviso para o analista.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from src.llm import cliente as llm
from src.llm.cliente import ClienteLLM, ErroLLM
from src.motor.analisador import (
    RespostaInvalida,
    _pedir_proposta,
    conferir_proposta,
    extrair_json,
    preparar_analise,
)
from src.motor.regras import ROTULO_CRITERIO, Criterio
from src.motor.schemas import (
    AnaliseConferida,
    Auditoria,
    AvaliacaoAtividade,
    Divergencia,
    Orquestracao,
    PapelExecutado,
)
from src.pacote.modelos import ProjetoCarregado
from src.rag.corpus import DEPOIMENTO, CorpusProjeto

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
ARQUIVO_PROMPT_CONFRONTO = PROMPTS / "confronto_depoimento.md"
ARQUIVO_PROMPT_AUDITORIA = PROMPTS / "auditoria_fontes.md"
# Protecao contra um trecho anormalmente longo; os trechos citados ficam bem
# abaixo disso e chegam inteiros ao auditor.
LIMITE_TEXTO_DA_FONTE = 4000

# Ordem de preferencia de provedor para cada papel.
PREFERENCIAS = {
    "analista": ("gemini", "openrouter", "groq"),
    "confronto": ("groq", "openrouter", "gemini"),
    "auditor": ("openrouter", "groq", "gemini"),
}
VEREDITOS = {
    "sustenta": "as fontes sustentam a justificativa",
    "sustenta_em_parte": "as fontes sustentam só parte da justificativa",
    "nao_sustenta": "as fontes não sustentam a justificativa",
}
# Dito ao analista quando outro modelo cuida das duas listas.
DISPENSA_DO_ANALISTA = (
    "\n\nNesta rodada, outro modelo confronta a entrevista com os registros e "
    "classifica as atividades. Devolva `divergencias` e `atividades` como listas vazias."
)


@dataclass
class Papeis:
    analista: ClienteLLM
    confronto: Optional[ClienteLLM] = None
    auditor: Optional[ClienteLLM] = None


def papeis_padrao(rodadas_de_espera: int = 0) -> Papeis:
    """
    Distribui os papeis entre os provedores com chave no .env, sem repetir o
    titular. Os demais provedores entram na fila de cada papel como reserva.
    `rodadas_de_espera` vale para lotes: com todos sem cota, espera a cota voltar.
    """
    disponiveis = {
        nome: clientes
        for nome in llm.PROVEDORES
        if (clientes := llm.clientes_do_provedor(nome))
    }
    if not disponiveis:
        raise ErroLLM(
            "Nenhuma chave de modelo no .env. Preencha GEMINI_API_KEY, "
            "GROQ_API_KEY ou OPENROUTER_API_KEY."
        )
    usados: set[str] = set()

    def escolher(papel: str) -> Optional[ClienteLLM]:
        nome = next(
            (n for n in PREFERENCIAS[papel] if n in disponiveis and n not in usados), None
        )
        if nome is None:
            return None
        usados.add(nome)
        reservas = [n for n in PREFERENCIAS[papel] if n in disponiveis and n != nome]
        fila = [cliente for n in [nome] + reservas for cliente in disponiveis[n]]
        return llm.ClienteComReserva(fila, rodadas_de_espera=rodadas_de_espera)

    return Papeis(
        analista=escolher("analista"),
        confronto=escolher("confronto"),
        auditor=escolher("auditor"),
    )


class _Medidor:
    """Repassa ao cliente e soma tempo e tokens das chamadas de um papel."""

    def __init__(self, cliente: ClienteLLM):
        self._cliente = cliente
        self.provedor = getattr(cliente, "provedor", "") or ""
        self.modelo = getattr(cliente, "modelo", "") or ""
        self.chamadas = 0
        self.segundos = 0.0
        self.tokens_entrada = 0
        self.tokens_saida = 0
        # Modelos da fila que deixaram de responder durante este papel.
        self.trocas: list[str] = []

    def completar(self, sistema, usuario, esquema=None):
        inicio = time.perf_counter()
        self.chamadas += 1
        trocas = getattr(self._cliente, "trocas", [])
        antes = len(trocas)
        try:
            resposta = self._cliente.completar(sistema, usuario, esquema)
        finally:
            self.segundos += time.perf_counter() - inicio
            self.trocas += trocas[antes:]
        self.provedor = resposta.provedor or self.provedor
        self.modelo = resposta.modelo or self.modelo
        self.tokens_entrada += int(resposta.uso.get("prompt_tokens") or 0)
        self.tokens_saida += int(resposta.uso.get("completion_tokens") or 0)
        return resposta

    def aviso_de_troca(self, papel: str) -> list[str]:
        """Diz ao analista que o papel foi feito por um modelo reserva."""
        if not self.trocas:
            return []
        falhas = "; ".join(dict.fromkeys(self.trocas))
        return [f"Papel de {papel}: {falhas}. Quem respondeu: {self.provedor} ({self.modelo})."]

    def registro(self, papel: str, erro: Optional[Exception] = None) -> PapelExecutado:
        return PapelExecutado(
            papel=papel,
            provedor=self.provedor,
            modelo=self.modelo,
            segundos=round(self.segundos, 1),
            chamadas=self.chamadas,
            tokens_entrada=self.tokens_entrada,
            tokens_saida=self.tokens_saida,
            concluido=erro is None,
            observacao=str(erro)[:200] if erro else "",
        )


class _Confronto(BaseModel):
    divergencias: list[Divergencia] = Field(default_factory=list)
    atividades: list[AvaliacaoAtividade] = Field(default_factory=list)


class _RespostaAuditoria(BaseModel):
    auditoria: list[Auditoria]


def _tentar(funcao, *argumentos):
    try:
        return funcao(*argumentos), None
    except ErroLLM as erro:
        return None, erro


def _bloco(corpus: CorpusProjeto, ids: list[str]) -> str:
    return "\n\n".join(
        f"[{i}] ({corpus.natureza.get(i, '')})\n{corpus.trechos[i].texto}"
        for i in ids
        if i in corpus.trechos
    )


def _partes_do_confronto(corpus: CorpusProjeto) -> tuple[list[str], list[str], list[str]]:
    projeto = corpus.projeto
    entrevista = [t for t, n in corpus.natureza.items() if n == DEPOIMENTO]
    registros = (
        sorted(projeto.ensaios())
        + [f"evidencias/metodo.md#{n}" for n in ("2", "3", "4")]
        + ["evidencias/observacoes.csv", "evidencias/cronologia.csv"]
    )
    atividades = [a.id_atividade for a in projeto.atividades]
    return entrevista, registros, atividades


def contexto_do_confronto(corpus: CorpusProjeto) -> list:
    """Trechos que o modelo do confronto recebe (e, por isso, pode citar)."""
    return [
        corpus.trechos[i]
        for parte in _partes_do_confronto(corpus)
        for i in parte
        if i in corpus.trechos
    ]


def mensagem_de_confronto(corpus: CorpusProjeto) -> str:
    """So o que o confronto precisa: entrevista, registros e atividades."""
    projeto = corpus.projeto
    entrevista, registros, atividades = _partes_do_confronto(corpus)
    return (
        f"Projeto {projeto.projeto_id}\n\n"
        f"# ENTREVISTA (depoimento de memória)\n\n{_bloco(corpus, entrevista) or 'Não entregue.'}\n\n"
        f"# REGISTROS\n\n{_bloco(corpus, registros)}\n\n"
        f"# ATIVIDADES\n\n{_bloco(corpus, atividades) or 'Nenhuma.'}\n\n"
        "Responda com o objeto JSON descrito nas instruções."
    )


def confrontar_depoimento(corpus: CorpusProjeto, cliente: ClienteLLM) -> _Confronto:
    sistema = ARQUIVO_PROMPT_CONFRONTO.read_text(encoding="utf-8")
    resposta = cliente.completar(sistema, mensagem_de_confronto(corpus))
    try:
        return _Confronto.model_validate(extrair_json(resposta.texto))
    except ValidationError as erro:
        raise RespostaInvalida(f"Confronto em formato inválido: {str(erro)[:300]}") from erro


def mensagem_de_auditoria(analise: AnaliseConferida, corpus: CorpusProjeto) -> str:
    """Justificativas por criterio e, uma vez so, o texto de cada fonte citada."""
    partes = [f"Projeto {analise.projeto_id}. Audite os cinco critérios abaixo."]
    citadas: list[str] = []
    for avaliacao in analise.proposta.criterios:
        fontes = [i for i in avaliacao.fontes if i in corpus.trechos]
        citadas += [i for i in fontes if i not in citadas]
        partes.append(
            f"## {avaliacao.criterio.value}\n"
            f"Estado proposto: {avaliacao.estado}\n"
            f"Justificativa: {avaliacao.justificativa}\n"
            "Fontes citadas: " + (", ".join(fontes) or "nenhuma fonte válida foi citada.")
        )
    textos = []
    for i in citadas:
        texto = corpus.trechos[i].texto
        if len(texto) > LIMITE_TEXTO_DA_FONTE:
            texto = texto[:LIMITE_TEXTO_DA_FONTE] + "\n[texto cortado neste ponto]"
        textos.append(f"[{i}] ({corpus.natureza.get(i, '')})\n{texto}")
    partes.append("# TEXTO DAS FONTES\n\n" + ("\n\n".join(textos) or "Nenhuma."))
    return "\n\n".join(partes)


def auditar_fontes(
    analise: AnaliseConferida, corpus: CorpusProjeto, cliente: ClienteLLM
) -> list[Auditoria]:
    sistema = ARQUIVO_PROMPT_AUDITORIA.read_text(encoding="utf-8")
    resposta = cliente.completar(sistema, mensagem_de_auditoria(analise, corpus))
    try:
        itens = _RespostaAuditoria.model_validate(extrair_json(resposta.texto)).auditoria
    except ValidationError as erro:
        raise RespostaInvalida(f"Auditoria em formato inválido: {str(erro)[:300]}") from erro
    # Um veredito por criterio; o que vier repetido e ignorado.
    por_criterio = {a.criterio: a for a in reversed(itens)}
    return [por_criterio[c] for c in Criterio if c in por_criterio]


def analisar_com_orquestracao(
    projeto: ProjetoCarregado,
    papeis: Papeis,
    corpus: Optional[CorpusProjeto] = None,
    raiz: Optional[str | Path] = None,
) -> AnaliseConferida:
    preparo = preparar_analise(projeto, corpus, raiz, sem_depoimento=bool(papeis.confronto))
    corpus = preparo["corpus"]
    regras = preparo["regras"] + preparo["orientacoes"]

    analista = _Medidor(papeis.analista)
    confronto = _Medidor(papeis.confronto) if papeis.confronto else None
    auditor = _Medidor(papeis.auditor) if papeis.auditor else None
    mensagem = preparo["mensagem"] + (DISPENSA_DO_ANALISTA if confronto else "")

    # Analista e confronto tem entradas independentes e rodam ao mesmo tempo.
    with ThreadPoolExecutor(max_workers=2) as executor:
        tarefa_analista = executor.submit(
            _tentar, _pedir_proposta, analista, preparo["sistema"], mensagem
        )
        tarefa_confronto = (
            executor.submit(_tentar, confrontar_depoimento, corpus, confronto)
            if confronto
            else None
        )
        resultado, erro_analista = tarefa_analista.result()
        achados, erro_confronto = tarefa_confronto.result() if tarefa_confronto else (None, None)

    if erro_analista is not None:
        raise erro_analista
    proposta, modelo = resultado
    executados = [analista.registro("analista")]
    avisos: list[str] = analista.aviso_de_troca("analista")

    # Se o modelo de um papel secundario falha, o do outro papel secundario
    # assume a tarefa: sao entradas pequenas, e perder a etapa custa mais.
    if confronto and achados is None and auditor:
        reserva = _Medidor(papeis.auditor)
        achados, erro_reserva = _tentar(confrontar_depoimento, corpus, reserva)
        executados.append(confronto.registro("confronto", erro_confronto))
        confronto, erro_confronto = reserva, erro_reserva
        if achados is not None:
            avisos.append(
                f"O modelo do confronto ({executados[-1].provedor}) não respondeu; "
                f"a tarefa foi feita por {reserva.provedor}."
            )

    if confronto:
        executados.append(confronto.registro("confronto", erro_confronto))
        if achados is not None:
            avisos += confronto.aviso_de_troca("confronto")
            proposta.divergencias = achados.divergencias
            proposta.atividades = achados.atividades
        else:
            avisos.append(
                f"O modelo do confronto ({confronto.provedor}) não respondeu: "
                f"{str(erro_confronto)[:160]} Divergências entre entrevista e registros "
                "e natureza das atividades não foram avaliadas nesta rodada."
            )

    # Uma fonte vale se foi lida por quem a citou: o analista ou o confronto.
    lidos = {t.trecho_id: t for t in preparo["contexto"]}
    if achados is not None:
        lidos.update({t.trecho_id: t for t in contexto_do_confronto(corpus)})
    analise = conferir_proposta(proposta, corpus, list(lidos.values()), regras, modelo)

    auditoria: list[Auditoria] = []
    if auditor:
        resultado, erro_auditor = _tentar(auditar_fontes, analise, corpus, auditor)
        executados.append(auditor.registro("auditor", erro_auditor))
        if erro_auditor is not None and papeis.confronto:
            reserva = _Medidor(papeis.confronto)
            resultado, erro_reserva = _tentar(auditar_fontes, analise, corpus, reserva)
            executados.append(reserva.registro("auditor", erro_reserva))
            if erro_reserva is None:
                avisos.append(
                    f"O modelo auditor ({auditor.provedor}) não respondeu; "
                    f"a auditoria foi feita por {reserva.provedor}."
                )
                auditor, erro_auditor = reserva, None
        if erro_auditor is not None:
            avisos.append(
                f"O modelo auditor ({auditor.provedor}) não respondeu: "
                f"{str(erro_auditor)[:160]} As fontes foram conferidas só quanto à existência."
            )
        else:
            avisos += auditor.aviso_de_troca("auditor")
            auditoria = resultado
            for item in auditoria:
                if item.veredito != "sustenta":
                    avisos.append(
                        f"{ROTULO_CRITERIO[item.criterio]}: segundo o modelo auditor, "
                        f"{VEREDITOS[item.veredito]}. {item.comentario}"
                    )

    analise.avisos = analise.avisos + avisos
    analise.orientacoes = [t.trecho_id for t in preparo["orientacoes"]]
    analise.exemplos = [t.trecho_id for t in preparo["exemplos"]]
    analise.orquestracao = Orquestracao(papeis=executados, auditoria=auditoria)
    return analise
