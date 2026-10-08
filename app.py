"""
Interface do analista (Streamlit).

Fluxo: escolher o projeto, pedir a análise, conferir as verificações
automáticas e decidir cada ponto (D1 a D5). O dossiê só é gerado quando todos
os pontos têm decisão do analista.

Uso:
    .venv/bin/streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src import apresentacao, ferramentas
from src.decisoes.maquina_estados import (
    DecisaoInvalida,
    Ponto,
    PontoDecisao,
    Status,
    decisao_final_pronta,
    proximo_ponto_pendente,
)
from src.dossie.gerador import gerar_dossie
from src.llm import cliente as llm
from src.llm.cliente import ErroLLM
from src.motor import orquestrador
from src.motor.fluxo import (
    criar_pontos,
    propor_classificacao,
    titulo_do_ponto,
    trechos_do_dossie,
)
from src.motor.linguagem import frase_da_decisao
from src.motor.regras import CLASSIFICACOES, ESTADOS, Criterio
from src.motor.schemas import AnaliseConferida
from src.pacote.carregador import PacoteInvalido

SAIDA = Path(__file__).resolve().parent / "saida"
ANALISES = SAIDA / "analises"


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


def abrir_sessao(projeto_id: str, corpus, analise: AnaliseConferida) -> None:
    st.session_state["sessao"] = {
        "projeto_id": projeto_id,
        "corpus": corpus,
        "analise": analise,
        "pontos": criar_pontos(analise),
    }


def analisar(projeto_id: str) -> None:
    corpus = ferramentas.corpus_do_projeto(projeto_id)
    analise = orquestrador.analisar_com_orquestracao(
        corpus.projeto, orquestrador.papeis_padrao(), corpus
    )
    ANALISES.mkdir(parents=True, exist_ok=True)
    (ANALISES / f"{projeto_id}.json").write_text(analise.model_dump_json(indent=2), encoding="utf-8")
    abrir_sessao(projeto_id, corpus, analise)


def abrir_analise_salva(projeto_id: str) -> None:
    """Reabre a ultima proposta do modelo, sem nova chamada. As decisoes recomecam."""
    analise = AnaliseConferida.model_validate_json(
        (ANALISES / f"{projeto_id}.json").read_text(encoding="utf-8")
    )
    abrir_sessao(projeto_id, ferramentas.corpus_do_projeto(projeto_id), analise)


def repropor(sessao: dict, ponto: PontoDecisao) -> None:
    """Nova proposta do modelo para um ponto rejeitado."""
    if ponto.ponto == Ponto.D5:
        propor_classificacao(sessao["pontos"], sessao["analise"])
        return
    nova = orquestrador.analisar_com_orquestracao(
        sessao["corpus"].projeto, orquestrador.papeis_padrao(), sessao["corpus"]
    )
    sessao["analise"] = nova
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
    with st.form(f"decisao-{ponto.decision_id}"):
        acao = st.radio("Sua decisão", ["Aceitar", "Alterar", "Rejeitar"], horizontal=True)
        opcoes = opcoes_de_valor(ponto)
        if opcoes:
            valor = st.selectbox("Valor final, se alterar", opcoes)
        else:
            valor = st.text_area("Valor final, se alterar")
        motivo = st.text_area("Motivo (obrigatório para alterar ou rejeitar, mínimo de 20 caracteres)")
        if not st.form_submit_button("Registrar decisão"):
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
    st.rerun()


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


def mostrar_verificacoes(sessao: dict) -> None:
    projeto = sessao["corpus"].projeto
    analise = sessao["analise"]
    conferencias = ferramentas.conferir_resultados(sessao["projeto_id"])
    resumo = apresentacao.resumo_da_conferencia(conferencias)
    descartadas = apresentacao.fontes_descartadas(sessao["corpus"], analise.fontes_descartadas)

    st.subheader("Verificações automáticas (sem IA)")
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

    try:
        projetos = ferramentas.listar_projetos()
    except PacoteInvalido as erro:
        st.error(f"{erro} Preencha LEI_DO_BEM_PACOTE no arquivo .env.")
        return

    with st.sidebar:
        analista = st.text_input("Analista (identificação)").strip()
        projeto_id = st.selectbox("Projeto para análise", [p["projeto_id"] for p in projetos])
        st.caption(
            f"{len(projetos)} caso(s) para análise. Os projetos históricos já "
            "classificados servem só de referência para o modelo."
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
            st.caption("Reabre a última proposta do modelo para este projeto, sem nova chamada.")

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
    mostrar_modelos(sessao["analise"])
    mostrar_verificacoes(sessao)

    pontos = sessao["pontos"]
    decididos = [p for p in pontos if p.decidido]
    if decididos:
        st.subheader("Pontos decididos")
        for p in decididos:
            with st.expander(f"{titulo(p)} · {p.valor_final}"):
                st.markdown(f"**Decisão:** {frase_decisao(p)}")
                mostrar_parecer(p)
                mostrar_fontes(sessao, p.justificativa)

    if decisao_final_pronta(pontos):
        mostrar_dossie(sessao)
        return

    atual = proximo_ponto_pendente(pontos)
    if atual.ponto == Ponto.D5 and atual.status in (Status.PROPOSTA, Status.REABERTA):
        propor_classificacao(pontos, sessao["analise"])

    st.subheader(f"Aguardando sua decisão: {titulo(atual)}")
    st.progress(len(decididos) / len(pontos), text=f"{len(decididos)} de {len(pontos)} pontos decididos")

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
    st.markdown("**O que sustenta o parecer**")
    mostrar_fontes(sessao, atual.justificativa)
    if not analista:
        st.info("Informe sua identificação na barra lateral para registrar a decisão.")
        return
    formulario_decisao(sessao, atual, analista)


main()
