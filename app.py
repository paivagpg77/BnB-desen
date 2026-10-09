"""
Interface do analista (Streamlit).

Fluxo: escolher o projeto, pedir a análise, conferir as verificações
automáticas e decidir cada ponto (D1 a D5). O dossiê só é gerado quando todos
os pontos têm decisão do analista.

Uso:
    .venv/bin/streamlit run app.py
"""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from src import apresentacao, ferramentas
from src.config import carregar_env
from src.decisoes import discordancias
from src.decisoes.maquina_estados import (
    DecisaoInvalida,
    Ponto,
    PontoDecisao,
    Status,
    decisao_final_pronta,
    proximo_ponto_pendente,
)
from src.decisoes.registro import RegistroDecisoes
from src.dossie.gerador import gerar_dossie
from src.llm import cliente as llm
from src.llm.cliente import ErroLLM
from src.motor import orquestrador
from src.motor.fluxo import (
    criar_pontos,
    propor_classificacao,
    rever_ponto,
    titulo_do_ponto,
    trechos_do_dossie,
)
from src.motor.linguagem import frase_da_decisao
from src.motor.regras import CLASSIFICACOES, ESTADOS, Criterio
from src.motor.schemas import AnaliseConferida
from src.pacote.carregador import PacoteInvalido, raiz_do_pacote
from src.schemas.discordancia import StatusDiscordancia, TipoDiscordancia

# LEI_DO_BEM_SAIDA troca a pasta onde ficam as analises, os logs e os dossies.
SAIDA = Path(os.environ.get("LEI_DO_BEM_SAIDA") or Path(__file__).resolve().parent / "saida")
ANALISES = SAIDA / "analises"
DECISOES = SAIDA / "decisoes"

TELA_ANALISE = "Análise do projeto"
TELA_REVISAO = "Discordâncias e revisão cega"


def repositorio() -> discordancias.RepositorioDiscordancias:
    return discordancias.RepositorioDiscordancias(SAIDA / "discordancias.jsonl")


def titulo(ponto: PontoDecisao) -> str:
    return titulo_do_ponto(ponto)


def frase_decisao(ponto: PontoDecisao) -> str:
    acao = {Status.ACEITA: "aceita", Status.ALTERADA: "alterada", Status.REJEITADA: "rejeitada"}
    return frase_da_decisao(
        acao.get(ponto.status, ponto.status.value),
        ponto.analista or "",
        ponto.valor_proposto,
        ponto.valor_final,
        ponto.motivo,
    )


def mostrar_parecer(ponto: PontoDecisao) -> None:
    parecer = ponto.justificativa.get("parecer")
    if parecer:
        st.markdown(f"> {parecer}")
    # Nos pontos de texto livre o valor repete o parecer; o rotulo so ajuda
    # onde ha um vocabulario fechado (criterios e classificacao).
    if ponto.ponto in (Ponto.D2, Ponto.D5):
        st.caption(f"Valor proposto pela IA: {ponto.valor_proposto}")
    auditoria = ponto.justificativa.get("auditoria")
    if auditoria:
        cor = {"sustenta": "green", "sustenta_em_parte": "orange", "nao_sustenta": "red"}
        st.markdown(f":{cor[auditoria['veredito']]}-badge[Auditoria] {auditoria['texto']}")


def abrir_sessao(projeto_id: str, corpus, analise: AnaliseConferida, nova: bool) -> None:
    """Analise nova comeca um trecho do log; analise salva retoma as decisoes dele."""
    registro = RegistroDecisoes(DECISOES, projeto_id)
    pontos = None if nova else registro.retomar()
    if pontos is None:
        pontos = criar_pontos(analise)
        registro.iniciar_analise(pontos)
    st.session_state["sessao"] = {
        "projeto_id": projeto_id,
        "corpus": corpus,
        "analise": analise,
        "pontos": pontos,
    }


def papeis() -> orquestrador.Papeis:
    # Com a fila toda sem cota, vale esperar uma vez a cota por minuto voltar.
    return orquestrador.papeis_padrao(rodadas_de_espera=1)


def salvar_analise(analise: AnaliseConferida) -> None:
    ANALISES.mkdir(parents=True, exist_ok=True)
    (ANALISES / f"{analise.projeto_id}.json").write_text(
        analise.model_dump_json(indent=2), encoding="utf-8"
    )


def analisar(projeto_id: str) -> None:
    corpus = ferramentas.corpus_do_projeto(projeto_id)
    analise = orquestrador.analisar_com_orquestracao(
        corpus.projeto, papeis(), corpus
    )
    salvar_analise(analise)
    abrir_sessao(projeto_id, corpus, analise, nova=True)


def abrir_analise_salva(projeto_id: str) -> None:
    """Reabre a ultima proposta do modelo e as decisoes ja registradas, sem nova chamada."""
    analise = AnaliseConferida.model_validate_json(
        (ANALISES / f"{projeto_id}.json").read_text(encoding="utf-8")
    )
    abrir_sessao(projeto_id, ferramentas.corpus_do_projeto(projeto_id), analise, nova=False)


def repropor(sessao: dict, ponto: PontoDecisao) -> None:
    """Nova proposta do modelo para um ponto rejeitado."""
    if ponto.ponto == Ponto.D5:
        propor_classificacao(sessao["pontos"], sessao["analise"])
        return
    nova = orquestrador.analisar_com_orquestracao(
        sessao["corpus"].projeto, papeis(), sessao["corpus"]
    )
    sessao["analise"] = nova
    salvar_analise(nova)
    equivalente = next(p for p in criar_pontos(nova) if p.decision_id == ponto.decision_id)
    ponto.propor(equivalente.valor_proposto, equivalente.justificativa)


def mostrar_fonte(sessao: dict, trechos: dict, trecho_id: str) -> None:
    trecho = trechos.get(trecho_id)
    if trecho is None:
        st.error(f"Fonte não encontrada: {trecho_id}")
        return
    natureza, cor, explicacao = apresentacao.natureza_da_fonte(sessao["corpus"], trecho_id)
    with st.expander(f":{cor}[{natureza.capitalize()}] · **{trecho.secao}** · `{trecho_id}`"):
        st.markdown(f":{cor}-badge[{natureza}] {explicacao.capitalize()}.")
        marcacao = {"titulo": "**{}**", "item": "- {}", "paragrafo": "{}"}
        st.markdown(
            "\n\n".join(
                marcacao[tipo].format(conteudo)
                for tipo, conteudo in apresentacao.texto_em_blocos(trecho.texto)
            ).replace("\n\n- ", "\n- ")
        )


def mostrar_fontes(sessao: dict, justificativa: dict) -> None:
    trechos = trechos_do_dossie(sessao["corpus"])
    grupos = apresentacao.agrupar_fontes(justificativa.get("porque", []))
    if not grupos:
        st.warning("Este ponto não tem nenhuma fonte verificada. Confira antes de decidir.")
    for afirmacao, fontes in grupos:
        with st.container(border=True):
            st.markdown(afirmacao)
            st.caption(f"{len(fontes)} fonte(s) conferida(s):")
            for trecho_id in fontes:
                mostrar_fonte(sessao, trechos, trecho_id)

    colunas = st.columns(2)
    for coluna, rotulo, chave, cor in (
        (colunas[0], "Evidências contrárias", "evidencias_contrarias", "red"),
        (colunas[1], "Lacunas", "lacunas", "orange"),
    ):
        itens = justificativa.get(chave) or []
        if itens:
            with coluna.container(border=True):
                st.markdown(f":{cor}-badge[{rotulo}: {len(itens)}]")
                for texto in itens:
                    st.markdown(f"- {texto}")
    if justificativa.get("como"):
        with st.expander("Como a proposta foi feita"):
            for passo in justificativa["como"]:
                st.markdown(f"- {passo}")


def opcoes_de_valor(ponto: PontoDecisao) -> list[str] | None:
    if ponto.ponto == Ponto.D2:
        return list(ESTADOS[Criterio(ponto.criterio)])
    if ponto.ponto == Ponto.D5:
        return list(CLASSIFICACOES)
    return None


def formulario_decisao(sessao: dict, ponto: PontoDecisao, analista: str) -> None:
    # Fora do formulario: a escolha define quais campos aparecem.
    chave_da_acao = f"acao-{ponto.decision_id}"
    acao = st.radio(
        "Sua decisão", ["Aceitar", "Alterar", "Rejeitar"], horizontal=True, key=chave_da_acao
    )
    valor = tipo = motivo = None
    with st.form(f"decisao-{ponto.decision_id}"):
        if acao == "Alterar":
            opcoes = opcoes_de_valor(ponto)
            if opcoes:
                valor = st.selectbox("Valor final", opcoes)
            else:
                valor = st.text_area("Valor final")
        if acao != "Aceitar":
            tipo = st.selectbox(
                "Por que discorda da proposta",
                list(TipoDiscordancia),
                format_func=discordancias.ROTULO_TIPO.get,
            )
            motivo = st.text_area("Motivo (obrigatório, mínimo de 20 caracteres)")
        if not st.form_submit_button("Registrar decisão", type="primary"):
            return
    try:
        if acao == "Aceitar":
            ponto.aceitar(analista)
        elif acao == "Alterar":
            ponto.alterar(valor, motivo, analista)
        else:
            ponto.rejeitar(motivo, analista)
    except DecisaoInvalida as erro:
        st.error(str(erro))
        return
    if acao != "Aceitar":
        # A discordancia fica na fila da revisao cega; nao muda a decisao deste caso.
        analise = sessao["analise"]
        repositorio().salvar(
            discordancias.abrir_discordancia(
                ponto,
                tipo,
                versao_norma=f"base de regras {analise.versao_regras}",
                versao_motor=f"prompt {analise.versao_prompt} / {analise.modelo}",
            )
        )
    # Se o ponto voltar a aguardar decisao, a escolha recomeca em Aceitar.
    del st.session_state[chave_da_acao]
    st.rerun()


def mostrar_precedentes(ponto: PontoDecisao) -> None:
    resumos = discordancias.precedentes_do_criterio(
        repositorio().todas(), ponto.criterio or ponto.ponto.value, ponto.projeto_id
    )
    if not resumos:
        return
    total = sum(r.quantidade_casos for r in resumos)
    with st.expander(f"Precedentes internos (não normativos) · {total} caso(s)"):
        st.caption(
            "Discordâncias confirmadas por dois analistas em outros projetos, neste mesmo "
            "ponto. São contexto: não são fundamento legal e não alteram a proposta atual."
        )
        for resumo in resumos:
            st.markdown(f"**{discordancias.ROTULO_TIPO[resumo.tipo]}** · {resumo.quantidade_casos} caso(s)")
            for caso in resumo.casos:
                resultado = f" Valor confirmado: {caso.valor_resultante}." if caso.valor_resultante else ""
                st.markdown(
                    f"- `{caso.projeto_origem}` em {caso.data:%d/%m/%Y}: {caso.motivo_resumido}{resultado}"
                )


def formulario_revisao(registro, analista: str) -> None:
    ponto = RegistroDecisoes(DECISOES, registro.projeto_id).proposta_vigente(
        registro.decision_id, registro.registrada_em
    )
    if ponto is None:
        st.error(f"A proposta de {registro.decision_id} não está no log de decisões.")
        return
    st.markdown(f"**Projeto {registro.projeto_id} · {titulo(ponto)}**")
    st.caption(
        "Você vê a proposta da IA e as fontes. A decisão do primeiro analista "
        "fica oculta até você registrar a sua."
    )
    mostrar_parecer(ponto)
    mostrar_fontes({"corpus": ferramentas.corpus_do_projeto(registro.projeto_id)}, ponto.justificativa)
    concordo = "Concordo com a proposta da IA"
    # Todas as opcoes do ponto menos a da IA: a lista nao revela a escolha do primeiro analista.
    opcoes = [o for o in opcoes_de_valor(ponto) or [] if o != ponto.valor_proposto]
    with st.form(f"revisao-{registro.discordancia_id}"):
        conclusao = st.radio("Sua conclusão", [concordo, "Discordo da proposta da IA"], horizontal=True)
        valor = None
        if opcoes:
            valor = st.selectbox(
                "Valor que você daria, se discordar (opcional)",
                opcoes,
                index=None,
                placeholder="Sem outro valor",
            )
        motivo = st.text_area("Motivo (obrigatório, mínimo de 20 caracteres)")
        if not st.form_submit_button("Registrar revisão"):
            return
    try:
        discordancias.revisar(registro, analista, conclusao == concordo, motivo, valor)
    except ValidationError:
        st.error("O motivo precisa ter pelo menos 20 caracteres.")
        return
    repositorio().salvar(registro)
    st.rerun()


def percentual(valor: float | None) -> str:
    return "—" if valor is None else f"{valor:.0%}"


def segundo_analista(registro) -> str:
    if registro.status == StatusDiscordancia.NAO_CONFIRMADA:
        return "concordou com a IA"
    return registro.revisao.valor or "discordou da IA"


def tela_revisao(analista: str) -> None:
    st.header(TELA_REVISAO)
    registros = repositorio().todas()
    numeros = discordancias.metricas(registros)
    colunas = st.columns(4)
    colunas[0].metric("Discordâncias registradas", numeros["total"])
    colunas[1].metric("Aguardando revisão cega", numeros["aguardando_revisao"])
    colunas[2].metric("Confirmadas contra a IA", numeros["confirmadas"])
    colunas[3].metric("Não confirmadas", numeros["nao_confirmadas"])
    colunas = st.columns(4)
    colunas[0].metric("Divergência entre analistas", numeros["divergentes"])
    colunas[1].metric("Taxa de convergência contra a IA", percentual(numeros["taxa_convergencia"]))
    colunas[2].metric("Concordância entre analistas", percentual(numeros["concordancia_entre_analistas"]))

    for criterio, tipo, projetos in discordancias.padroes_candidatos(registros):
        st.warning(
            f"Padrão candidato para o curador normativo: {apresentacao.nome_do_ponto(criterio)} · "
            f"{discordancias.ROTULO_TIPO[tipo]}, confirmado em {len(projetos)} projetos "
            f"({', '.join(projetos)}). Nenhuma regra ou prompt muda automaticamente."
        )

    st.subheader("Aguardando a sua revisão")
    if not analista:
        st.info("Informe sua identificação na barra lateral para revisar.")
    else:
        pendentes = discordancias.pendentes_para(registros, analista)
        suas = numeros["aguardando_revisao"] - len(pendentes)
        if suas:
            st.caption(f"{suas} discordância(s) aberta(s) por você aguardam outro analista.")
        if pendentes:
            st.caption(f"{len(pendentes)} na fila. A mais antiga aparece primeiro.")
            formulario_revisao(pendentes[0], analista)
        else:
            st.info("Nenhuma discordância de outro analista aguarda revisão.")

    # So as ja revistas: listar as pendentes mostraria a decisao do primeiro analista.
    revistas = [r for r in registros if r.status != StatusDiscordancia.REGISTRADA]
    if revistas:
        st.subheader("Discordâncias já revistas")
        st.dataframe(
            [
                {
                    "Projeto": r.projeto_id,
                    "Ponto": apresentacao.nome_do_ponto(r.criterio),
                    "Tipo": discordancias.ROTULO_TIPO[r.tipo],
                    "Proposta da IA": r.valor_ia,
                    "Primeiro analista": r.valor_analista or "rejeitou a proposta",
                    "Segundo analista": segundo_analista(r),
                    "Resultado": discordancias.ROTULO_STATUS[r.status],
                }
                for r in revistas
            ],
            hide_index=True,
            width="stretch",
        )


PAPEIS = {
    "analista": "Avalia os critérios e propõe a classificação",
    "confronto": "Confronta a entrevista com os registros e classifica as atividades",
    "auditor": "Confere se as fontes citadas sustentam as justificativas",
}


def mostrar_modelos(analise: AnaliseConferida) -> None:
    """Quem fez o que: um cartao por papel, com tempo e tokens."""
    if not analise.orquestracao:
        st.caption(f"Proposta gerada por {analise.modelo} · prompt {analise.versao_prompt}")
        return
    papeis = analise.orquestracao.papeis
    st.caption(f"Prompt {analise.versao_prompt} · {len(papeis)} modelo(s), um papel cada")
    for coluna, papel in zip(st.columns(len(papeis)), papeis):
        with coluna.container(border=True):
            selo = ":green-badge[respondeu]" if papel.concluido else ":red-badge[não respondeu]"
            st.markdown(f"**{papel.papel.capitalize()}** {selo}")
            st.caption(PAPEIS[papel.papel])
            st.markdown(f"`{papel.provedor or 'modelo'}` · {papel.modelo}")
            if papel.concluido:
                st.caption(
                    f"{papel.segundos} s · {apresentacao.numero(papel.tokens_entrada)} tokens de entrada · "
                    f"{apresentacao.numero(papel.tokens_saida)} de saída"
                )
            else:
                st.caption(papel.observacao)


def resumo_das_verificacoes(sessao: dict, conferencias: list[dict]) -> None:
    """Uma linha acima das abas: o analista ve a conferencia sem abrir a aba dela."""
    analise = sessao["analise"]
    resumo = apresentacao.resumo_da_conferencia(conferencias)
    selos = []
    if resumo["com_problema"]:
        selos.append(f":red-badge[{resumo['com_problema']} resultado(s) não conferem com as medições]")
    elif resumo["total"]:
        selos.append(f":green-badge[{resumo['conferem']} de {resumo['total']} resultados conferem]")
    if resumo["total"] and resumo["de_entrega"] == resumo["total"]:
        selos.append(":orange-badge[só contagem de entrega: não medem o desempenho]")
    descartadas = sum(len(fontes) for fontes in analise.fontes_descartadas.values())
    if descartadas:
        selos.append(f":gray-badge[{descartadas} fonte(s) do modelo descartada(s)]")
    avisos = len(analise.avisos) + bool(sessao["corpus"].projeto.ausentes)
    if avisos:
        selos.append(f":orange-badge[{avisos} aviso(s)]")
    if selos:
        st.markdown("Verificações automáticas: " + " ".join(selos) + " · detalhes na aba Verificações")


def mostrar_criterios_confirmados(pontos: list[PontoDecisao]) -> None:
    """Em D5, as decisoes dos criterios de que a classificacao deriva."""
    criterios = [p for p in pontos if p.ponto == Ponto.D2 and p.decidido]
    if not criterios:
        return
    with st.container(border=True):
        st.markdown("**Critérios que você confirmou**")
        for p in criterios:
            alterado = f" (a IA propôs {p.valor_proposto})" if p.status == Status.ALTERADA else ""
            st.markdown(f"- {apresentacao.nome_do_ponto(p.criterio)}: **{p.valor_final}**{alterado}")


def mostrar_verificacoes(sessao: dict, conferencias: list[dict]) -> None:
    projeto = sessao["corpus"].projeto
    analise = sessao["analise"]
    resumo = apresentacao.resumo_da_conferencia(conferencias)
    descartadas = apresentacao.fontes_descartadas(sessao["corpus"], analise.fontes_descartadas)

    st.caption("Conferências feitas por regra, sem IA.")
    colunas = st.columns(4)
    colunas[0].metric("Resultados conferidos", resumo["total"])
    colunas[1].metric("Conferem com as medições", resumo["conferem"])
    colunas[2].metric("Com problema", resumo["com_problema"])
    colunas[3].metric("Fontes do modelo descartadas", len(descartadas))

    if resumo["com_problema"]:
        st.error(f"{resumo['com_problema']} resultado(s) não conferem com as medições.")
    elif resumo["total"]:
        st.success(
            f"{resumo['conferem']} resultado(s) conferem com as medições. "
            "Isso valida a conta, não a elegibilidade."
        )
    if resumo["total"] and resumo["de_entrega"] == resumo["total"]:
        st.warning(
            "Todos os resultados são contagem de material entregue: não medem o "
            "desempenho do mecanismo."
        )

    with st.expander("Conferência dos resultados, ensaio por ensaio", expanded=bool(resumo["com_problema"])):
        st.caption(
            "Cada resultado de resultados.csv foi recalculado a partir das linhas "
            "de medicoes.csv do mesmo ensaio e da mesma versão."
        )
        for c in conferencias:
            linha = apresentacao.linha_da_conferencia(c)
            rotulo, cor = apresentacao.SITUACOES.get(c["situacao"], (c["situacao"], "gray"))
            with st.container(border=True):
                esquerda, direita = st.columns([3, 1])
                esquerda.markdown(
                    f"**{linha['O que foi medido']}** · `{linha['Ensaio']}` · versão `{linha['Versão']}`"
                )
                direita.markdown(f":{cor}-badge[{rotulo}]")
                registrado, recalculado, forma = st.columns(3)
                registrado.markdown(f"Registrado  \n**{linha['Registrado em resultados.csv']}**")
                recalculado.markdown(f"Recalculado  \n**{linha['Recalculado das medições']}**")
                forma.markdown(f"Cálculo  \n{linha['Como foi calculado']} · {linha['Tipo']}")
                if c["detalhe"]:
                    st.caption(c["detalhe"])

    with st.expander(f"Fontes citadas pelo modelo e descartadas ({len(descartadas)})"):
        if descartadas:
            st.caption(
                "O modelo citou estas fontes, mas a conferência não as aceitou. "
                "Elas não sustentam nenhum ponto da proposta."
            )
            st.dataframe(descartadas, hide_index=True, width="stretch")
        else:
            st.markdown("Todas as fontes citadas pelo modelo existem nos trechos que ele recebeu.")

    if projeto.ausentes:
        st.warning("Arquivos do inventário ausentes ou ilegíveis: " + ", ".join(sorted(set(projeto.ausentes))))
    for aviso in analise.avisos:
        st.warning(aviso)


def mostrar_dossie(sessao: dict) -> None:
    analise = sessao["analise"]
    projeto = sessao["corpus"].projeto
    nao_verificado = list(analise.avisos) + [
        f"Arquivo não lido: {arquivo}" for arquivo in sorted(set(projeto.ausentes))
    ]
    texto = gerar_dossie(
        projeto_id=sessao["projeto_id"],
        pontos=sessao["pontos"],
        trechos=trechos_do_dossie(sessao["corpus"]),
        versao_norma=f"base de regras {analise.versao_regras}",
        nao_verificado=nao_verificado,
    )
    SAIDA.mkdir(exist_ok=True)
    (SAIDA / f"dossie_{sessao['projeto_id']}.md").write_text(texto, encoding="utf-8")
    st.subheader("Dossiê")
    st.download_button(
        "Baixar dossiê (Markdown)", texto, file_name=f"dossie_{sessao['projeto_id']}.md"
    )
    st.markdown(texto)


def main() -> None:
    st.set_page_config(page_title="Lei do Bem · análise preliminar", layout="wide")
    st.title("Lei do Bem · apoio à análise preliminar")
    st.caption("A IA propõe; o analista decide. Nada avança sem a sua confirmação.")

    # Mudanca no .env vale na proxima interacao, sem reiniciar o app.
    carregar_env(forcar=True)
    try:
        projetos = ferramentas.listar_projetos()
    except PacoteInvalido as erro:
        st.error(f"{erro} Preencha LEI_DO_BEM_PACOTE no arquivo .env.")
        return

    with st.sidebar:
        analista = st.text_input("Analista (identificação)").strip()
        tela = st.selectbox("Tela", [TELA_ANALISE, TELA_REVISAO])
        # Escolher e analisar projeto so faz sentido na tela de analise.
        if tela == TELA_ANALISE:
            projeto_id = st.selectbox("Projeto para análise", [p["projeto_id"] for p in projetos])
            st.caption(
                f"{len(projetos)} caso(s) para análise no pacote `{raiz_do_pacote().name}`. "
                "Os projetos históricos já classificados servem só de referência para o modelo."
            )
            if st.button("Analisar projeto", type="primary"):
                try:
                    with st.spinner("Lendo as evidências e pedindo a proposta ao modelo..."):
                        analisar(projeto_id)
                except ErroLLM as erro:
                    st.error(str(erro))
            if (ANALISES / f"{projeto_id}.json").is_file():
                if st.button("Abrir análise salva"):
                    abrir_analise_salva(projeto_id)
                st.caption(
                    "Reabre a última proposta do modelo para este projeto e as decisões "
                    "já registradas, sem nova chamada."
                )

    if tela == TELA_REVISAO:
        tela_revisao(analista)
        return

    # Link direto para uma analise salva: .../?projeto=PRJ21
    pedido = str(st.query_params.get("projeto", "")).upper()
    if (
        "sessao" not in st.session_state
        and ferramentas.e_caso_para_analise(pedido)
        and (ANALISES / f"{pedido}.json").is_file()
    ):
        abrir_analise_salva(pedido)

    sessao = st.session_state.get("sessao")
    if not sessao:
        st.info("Escolha um projeto e clique em Analisar projeto.")
        return

    st.header(f"Projeto {sessao['projeto_id']}")
    pontos = sessao["pontos"]
    decididos = [p for p in pontos if p.decidido]
    pronto = decisao_final_pronta(pontos)
    st.progress(len(decididos) / len(pontos), text=f"{len(decididos)} de {len(pontos)} pontos decididos")

    conferencias = ferramentas.conferir_resultados(sessao["projeto_id"])
    resumo_das_verificacoes(sessao, conferencias)

    aba_decisao, aba_verificacoes, aba_decididos, aba_dossie = st.tabs(
        ["Decisão", "Verificações", f"Pontos decididos ({len(decididos)})", "Dossiê"],
        default="Dossiê" if pronto else None,
    )
    with aba_decisao:
        if pronto:
            st.success("Todos os pontos estão decididos. O dossiê está na aba Dossiê.")
        else:
            tela_decisao(sessao, analista)
    with aba_verificacoes:
        mostrar_verificacoes(sessao, conferencias)
        with st.expander("Como a proposta foi gerada"):
            mostrar_modelos(sessao["analise"])
    with aba_decididos:
        if not decididos:
            st.info("Nenhum ponto decidido ainda.")
        for p in decididos:
            with st.expander(f"{titulo(p)} · {p.valor_final}"):
                st.markdown(f"**Decisão:** {frase_decisao(p)}")
                mostrar_parecer(p)
                mostrar_fontes(sessao, p.justificativa)
                if analista and st.button("Rever este ponto", key=f"rever-{p.decision_id}"):
                    rever_ponto(pontos, p, analista)
                    st.rerun()
    with aba_dossie:
        if pronto:
            mostrar_dossie(sessao)
        else:
            st.info("O dossiê é gerado quando todos os pontos estiverem decididos.")


def tela_decisao(sessao: dict, analista: str) -> None:
    """O ponto que aguarda o analista: parecer, fontes, precedentes e a decisao."""
    pontos = sessao["pontos"]
    atual = proximo_ponto_pendente(pontos)
    if atual.ponto == Ponto.D5 and atual.status in (Status.PROPOSTA, Status.REABERTA):
        propor_classificacao(pontos, sessao["analise"])

    st.subheader(f"Aguardando sua decisão: {titulo(atual)}")

    if atual.status == Status.REJEITADA:
        st.warning(f"Você rejeitou a proposta deste ponto. Motivo registrado: {atual.motivo}")
        if st.button("Pedir nova proposta"):
            try:
                with st.spinner("Pedindo nova proposta ao modelo..."):
                    repropor(sessao, atual)
            except ErroLLM as erro:
                st.error(str(erro))
            else:
                st.rerun()
        return

    st.markdown("**Parecer da IA**")
    mostrar_parecer(atual)
    if atual.ponto == Ponto.D5:
        mostrar_criterios_confirmados(pontos)
    st.markdown("**O que sustenta o parecer**")
    mostrar_fontes(sessao, atual.justificativa)
    mostrar_precedentes(atual)
    if not analista:
        st.info("Informe sua identificação na barra lateral para registrar a decisão.")
        return
    formulario_decisao(sessao, atual, analista)


main()
