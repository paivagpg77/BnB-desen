"""
Interface do analista (Streamlit).

Fluxo: escolher o projeto, pedir a análise, conferir as verificações
automáticas e decidir cada ponto (D1 a D5). O dossiê só é gerado quando todos
os pontos têm decisão do analista.

Alterar ou rejeitar uma proposta abre uma discordância, que um segundo analista
revisa às cegas na área "Revisão cega". As confirmadas aparecem nos cartões como
precedentes internos, não normativos.

Uso:
    .venv/bin/streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src import apresentacao, ferramentas
from src.decisoes.maquina_estados import (
    MOTIVO_MIN_CARACTERES,
    DecisaoInvalida,
    Ponto,
    PontoDecisao,
    Status,
    decisao_final_pronta,
    proximo_ponto_pendente,
)
from src.discordancias import servico as discordancias
from src.discordancias.repositorio import DiscordanciaInvalida, RepositorioDiscordancias
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
from src.schemas.discordancia import (
    RegistroDiscordancia,
    ResultadoAnalista,
    StatusDiscordancia,
    TipoDiscordancia,
    padroes_candidatos,
)

SAIDA = Path(__file__).resolve().parent / "saida"
ANALISES = SAIDA / "analises"

ANALISE, REVISAO, PAINEL = "Análise do projeto", "Revisão cega", "Discordâncias e precedentes"
CONCORDO, DISCORDO = "Concordo com a proposta da IA", "Discordo da proposta da IA"


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
        tipo = st.selectbox(
            "Tipo de discordância, se alterar ou rejeitar",
            list(TipoDiscordancia),
            format_func=discordancias.ROTULO_TIPO.get,
        )
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
    if acao != "Aceitar":
        # Discordar da IA abre uma discordancia, que segue para a revisao cega.
        repositorio = RepositorioDiscordancias()
        repositorio.registrar(
            discordancias.abrir_discordancia(
                ponto, tipo, sessao["analise"], repositorio.proximo_id()
            )
        )
    st.rerun()


def mostrar_discordancia(registros: list[RegistroDiscordancia], ponto: PontoDecisao) -> None:
    """Situacao da discordancia que este analista abriu neste ponto, se houver."""
    do_ponto = [
        r for r in registros
        if r.decision_id == ponto.decision_id and r.analista_origem_pseudonimo == ponto.analista
    ]
    if do_ponto and ponto.status in (Status.ALTERADA, Status.REJEITADA):
        ultima = do_ponto[-1]
        st.caption(
            f"Discordância {ultima.discordancia_id} · "
            f"{discordancias.ROTULO_STATUS[ultima.status]}"
        )


def mostrar_precedentes(registros: list[RegistroDiscordancia], ponto: PontoDecisao) -> None:
    """Contexto para o analista. Nao altera a proposta, o estado nem a classificacao."""
    resumos = discordancias.precedentes_do_criterio(
        registros, discordancias.criterio_do_ponto(ponto)
    )
    if not resumos:
        return
    total = sum(r.quantidade_casos for r in resumos)
    with st.expander(f"Precedentes internos (não normativos): {total} caso(s)"):
        st.caption(resumos[0].aviso)
        for resumo in resumos:
            st.markdown(
                f"**{discordancias.ROTULO_TIPO[resumo.tipo]}** · {resumo.quantidade_casos} caso(s)"
            )
            for caso in resumo.casos:
                decidido = f" Valor decidido: {caso.valor_resultante}." if caso.valor_resultante else ""
                st.markdown(
                    f"- [{caso.projeto_origem}](?projeto={caso.projeto_origem}) · "
                    f"{caso.data:%d/%m/%Y} · {caso.motivo_resumido}{decidido}"
                )


def tela_revisao_cega(analista: str) -> None:
    st.header("Revisão cega")
    st.caption(
        "Você vê a proposta da IA e as evidências do caso. A decisão do primeiro "
        "analista só aparece depois que a sua for registrada."
    )
    repositorio = RepositorioDiscordancias()
    registros = repositorio.listar()

    concluida = st.session_state.pop("revisao_registrada", None)
    resolvida = next((r for r in registros if r.discordancia_id == concluida), None)
    if resolvida:
        primeira = (
            f"alterou para {resolvida.valor_analista}"
            if resolvida.valor_analista
            else "rejeitou a proposta"
        )
        st.success(
            f"Revisão de {resolvida.discordancia_id} registrada: "
            f"{discordancias.ROTULO_STATUS[resolvida.status]}. "
            f"{discordancias.DESFECHO[resolvida.status]}"
        )
        st.markdown(f"O primeiro analista {primeira}. Motivo registrado: {resolvida.motivo}")

    if len(analista) < discordancias.IDENTIFICACAO_MIN_CARACTERES:
        st.info("Informe sua identificação na barra lateral para revisar.")
        return
    fila = {r.discordancia_id: r for r in discordancias.fila_de_revisao(registros, analista)}
    if not fila:
        st.info("Nenhuma discordância aguardando a sua revisão.")
        return

    escolhida = st.selectbox(
        "Caso para revisar",
        list(fila),
        format_func=lambda i: (
            f"{i} · {fila[i].projeto_id} · {titulo(discordancias.ponto_da_discordancia(fila[i]))}"
        ),
    )
    registro = fila[escolhida]
    ponto = discordancias.ponto_da_discordancia(registro)
    try:
        corpus = ferramentas.corpus_do_projeto(registro.projeto_id)
    except ferramentas.ProjetoDesconhecido as erro:
        st.error(f"{erro} Sem as evidências do caso não há como revisar.")
        return

    st.subheader(f"{registro.projeto_id} · {titulo(ponto)}")
    st.markdown("**Parecer da IA**")
    mostrar_parecer(ponto)
    st.markdown("**O que sustenta o parecer**")
    mostrar_fontes({"corpus": corpus}, ponto.justificativa)

    with st.form(f"revisao-{registro.discordancia_id}"):
        escolha = st.radio("Sua decisão", [CONCORDO, DISCORDO], horizontal=True)
        outros = [o for o in opcoes_de_valor(ponto) or [] if o != ponto.valor_proposto]
        valor = st.selectbox("Valor que você daria, se discorda", outros) if outros else None
        motivo = st.text_area(f"Motivo (obrigatório, mínimo de {MOTIVO_MIN_CARACTERES} caracteres)")
        if not st.form_submit_button("Registrar revisão"):
            return
    if len(motivo.strip()) < MOTIVO_MIN_CARACTERES:
        st.error(f"O motivo precisa ter pelo menos {MOTIVO_MIN_CARACTERES} caracteres.")
        return
    try:
        repositorio.registrar_revisao(
            registro.discordancia_id,
            discordancias.nova_revisao(analista, escolha == CONCORDO, motivo, valor),
        )
    except (DiscordanciaInvalida, ValueError) as erro:
        st.error(str(erro))
        return
    st.session_state["revisao_registrada"] = registro.discordancia_id
    st.rerun()


def tela_discordancias() -> None:
    st.header("Discordâncias e precedentes internos")
    st.caption(
        "Precedentes internos são não normativos: não alteram proposta, estado nem "
        "classificação. Nenhuma regra ou prompt muda automaticamente; padrões "
        "recorrentes vão para o curador normativo."
    )
    registros = RepositorioDiscordancias().listar()
    numeros = discordancias.metricas(registros)
    colunas = st.columns(5)
    colunas[0].metric("Discordâncias registradas", numeros["total"])
    colunas[1].metric("Aguardando revisão cega", numeros["aguardando_revisao"])
    colunas[2].metric("Convergência contra a IA", numeros["convergentes"])
    colunas[3].metric("Não confirmadas", numeros["nao_confirmadas"])
    colunas[4].metric("Divergência entre analistas", numeros["divergentes"])
    if numeros["revisadas"]:
        st.caption(
            f"Convergência contra a IA em {numeros['taxa_convergencia']:.0%} das discordâncias. "
            f"O segundo analista decidiu como o primeiro em "
            f"{numeros['concordancia_entre_analistas']:.0%} das revisões cegas."
        )

    st.subheader("Fila do curador normativo")
    padroes = padroes_candidatos(registros)
    if not padroes:
        st.markdown("Nenhum padrão candidato até agora.")
    for _, tipo, casos in padroes:
        projetos = sorted({c.projeto_id for c in casos})
        st.warning(
            f"{titulo(discordancias.ponto_da_discordancia(casos[0]))} · "
            f"{discordancias.ROTULO_TIPO[tipo]}: convergência contra a IA em "
            f"{len(projetos)} projetos ({', '.join(projetos)}). Cabe ao curador dizer se "
            "a falha é de regra, de prompt ou de evidência."
        )

    st.subheader("Discordâncias revisadas")
    # As que aguardam revisao ficam de fora: mostra-las quebraria a revisao cega.
    revisadas = [r for r in registros if r.status != StatusDiscordancia.REGISTRADA]
    if not revisadas:
        st.markdown("Nenhuma discordância revisada até agora.")
        return
    st.dataframe(
        [
            {
                "Discordância": r.discordancia_id,
                "Projeto": r.projeto_id,
                "Ponto": titulo(discordancias.ponto_da_discordancia(r)),
                "Tipo": r.tipo.value,
                "Proposta da IA": r.valor_ia,
                "Primeiro analista": r.valor_analista or "rejeitou a proposta",
                "Segundo analista": (
                    "concordou com a IA"
                    if r.revisao.decisao == ResultadoAnalista.ACEITA_IA
                    else r.revisao.valor or "discordou da IA"
                ),
                "Situação": discordancias.ROTULO_STATUS[r.status],
                "Registrada em": f"{r.registrada_em:%d/%m/%Y}",
            }
            for r in revisadas
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
        modo = st.selectbox("Área de trabalho", [ANALISE, REVISAO, PAINEL], key="modo")
        if modo == ANALISE:
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

    if modo == REVISAO:
        tela_revisao_cega(analista)
        return
    if modo == PAINEL:
        tela_discordancias()
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
    mostrar_modelos(sessao["analise"])
    mostrar_verificacoes(sessao)

    pontos = sessao["pontos"]
    registros = RepositorioDiscordancias().listar()
    decididos = [p for p in pontos if p.decidido]
    if decididos:
        st.subheader("Pontos decididos")
        for p in decididos:
            with st.expander(f"{titulo(p)} · {p.valor_final}"):
                st.markdown(f"**Decisão:** {frase_decisao(p)}")
                mostrar_discordancia(registros, p)
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
        mostrar_discordancia(registros, atual)
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
    mostrar_precedentes(registros, atual)
    if len(analista) < discordancias.IDENTIFICACAO_MIN_CARACTERES:
        st.info(
            "Informe sua identificação na barra lateral, com pelo menos "
            f"{discordancias.IDENTIFICACAO_MIN_CARACTERES} caracteres, para registrar a decisão."
        )
        return
    formulario_decisao(sessao, atual, analista)


main()
