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

from src import ferramentas
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
from src.motor.analisador import analisar_projeto
from src.motor.fluxo import criar_pontos, propor_classificacao, trechos_do_dossie
from src.motor.regras import CLASSIFICACOES, ESTADOS, ROTULO_CRITERIO, Criterio
from src.pacote.carregador import PacoteInvalido

SAIDA = Path(__file__).resolve().parent / "saida"
TITULOS = {
    Ponto.D1: "D1 · Entendimento do projeto",
    Ponto.D2: "D2 · Critério",
    Ponto.D3: "D3 · Atividades: investigação ou rotina",
    Ponto.D4: "D4 · Evidências contrárias, divergências e lacunas",
    Ponto.D5: "D5 · Classificação final",
}


def titulo(ponto: PontoDecisao) -> str:
    if ponto.ponto == Ponto.D2:
        return f"D2 · {ROTULO_CRITERIO[Criterio(ponto.criterio)]}"
    return TITULOS[ponto.ponto]


def analisar(projeto_id: str) -> None:
    corpus = ferramentas.corpus_do_projeto(projeto_id)
    analise = analisar_projeto(corpus.projeto, llm.cliente_padrao(), corpus)
    st.session_state["sessao"] = {
        "projeto_id": projeto_id,
        "corpus": corpus,
        "analise": analise,
        "pontos": criar_pontos(analise),
    }


def repropor(sessao: dict, ponto: PontoDecisao) -> None:
    """Nova proposta do modelo para um ponto rejeitado."""
    if ponto.ponto == Ponto.D5:
        propor_classificacao(sessao["pontos"], sessao["analise"])
        return
    nova = analisar_projeto(sessao["corpus"].projeto, llm.cliente_padrao(), sessao["corpus"])
    sessao["analise"] = nova
    equivalente = next(p for p in criar_pontos(nova) if p.decision_id == ponto.decision_id)
    ponto.propor(equivalente.valor_proposto, equivalente.justificativa)


def mostrar_fontes(sessao: dict, justificativa: dict) -> None:
    trechos = trechos_do_dossie(sessao["corpus"])
    natureza = sessao["corpus"].natureza
    for item in justificativa.get("porque", []):
        trecho_id = item["trecho_id"]
        trecho = trechos.get(trecho_id)
        st.markdown(f"- {item['afirmacao']}")
        if trecho is None:
            st.error(f"Fonte não encontrada: {trecho_id}")
            continue
        rotulo = natureza.get(trecho_id, "regra da ferramenta")
        with st.expander(f"Fonte: {trecho_id} ({rotulo})"):
            st.text(trecho.texto)
    for rotulo, chave in (("Evidências contrárias", "evidencias_contrarias"), ("Lacunas", "lacunas")):
        if justificativa.get(chave):
            st.markdown(f"**{rotulo}**")
            for texto in justificativa[chave]:
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


def mostrar_verificacoes(sessao: dict) -> None:
    projeto = sessao["corpus"].projeto
    conferencias = ferramentas.conferir_resultados(sessao["projeto_id"])
    falhas = [c for c in conferencias if c["situacao"] not in ("confere", "transcricao_confere")]
    st.subheader("Verificações automáticas (sem IA)")
    if falhas:
        st.error(f"{len(falhas)} resultado(s) não conferem com as medições.")
    else:
        st.success(
            f"{len(conferencias)} resultado(s) conferem com as medições. "
            "Isso valida a conta, não a elegibilidade."
        )
    with st.expander("Detalhe da conferência"):
        st.dataframe(conferencias, hide_index=True)
    if projeto.ausentes:
        st.warning("Arquivos do inventário ausentes ou ilegíveis: " + ", ".join(sorted(set(projeto.ausentes))))
    for aviso in sessao["analise"].avisos:
        st.warning(aviso)
    descartadas = sessao["analise"].fontes_descartadas
    if descartadas:
        with st.expander("Fontes citadas pelo modelo e descartadas por não existirem"):
            st.json(descartadas)


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
        projeto_id = st.selectbox(
            "Projeto",
            [p["projeto_id"] for p in projetos],
            format_func=lambda pid: f"{pid} · {next(p['grupo'] for p in projetos if p['projeto_id'] == pid)}",
        )
        if st.button("Analisar projeto", type="primary"):
            try:
                with st.spinner("Lendo as evidências e pedindo a proposta ao modelo..."):
                    analisar(projeto_id)
            except ErroLLM as erro:
                st.error(str(erro))

    sessao = st.session_state.get("sessao")
    if not sessao:
        st.info("Escolha um projeto e clique em Analisar projeto.")
        return

    st.header(f"Projeto {sessao['projeto_id']}")
    st.caption(f"Proposta gerada por {sessao['analise'].modelo} · prompt {sessao['analise'].versao_prompt}")
    mostrar_verificacoes(sessao)

    pontos = sessao["pontos"]
    decididos = [p for p in pontos if p.decidido]
    if decididos:
        st.subheader("Pontos decididos")
        for p in decididos:
            with st.expander(f"{titulo(p)} · {p.valor_final} · {p.status.value} por {p.analista}"):
                st.markdown(f"Proposta da IA: **{p.valor_proposto}**")
                if p.motivo:
                    st.markdown(f"Motivo do analista: {p.motivo}")
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
        st.warning(f"Você rejeitou a proposta deste ponto. Motivo: {atual.motivo}")
        if st.button("Pedir nova proposta"):
            try:
                with st.spinner("Pedindo nova proposta ao modelo..."):
                    repropor(sessao, atual)
            except ErroLLM as erro:
                st.error(str(erro))
            else:
                st.rerun()
        return

    st.markdown(f"Proposta da IA: **{atual.valor_proposto}**")
    mostrar_fontes(sessao, atual.justificativa)
    if not analista:
        st.info("Informe sua identificação na barra lateral para registrar a decisão.")
        return
    formulario_decisao(sessao, atual, analista)


main()
