"""
Motor de analise: recupera as evidencias, pede a proposta ao modelo e confere.

O modelo nunca tem a ultima palavra em nenhuma etapa:
1. so recebe trechos recuperados do projeto e a base de regras;
2. cada fonte citada e conferida contra o contexto que ele recebeu;
3. criterio sem fonte valida e rebaixado para o estado indeterminado;
4. a classificacao exibida vem da regra sobre os estados, nao do modelo;
5. tudo isso vira proposta para o analista confirmar, alterar ou rejeitar.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from src.documentos.modelos import Trecho
from src.llm.cliente import ClienteLLM, ErroLLM
from src.motor.regras import (
    ESTADOS,
    ROTULO_CRITERIO,
    Criterio,
    derivar_classificacao,
    estado_indeterminado,
)
from src.motor.schemas import AnaliseConferida, PropostaModelo
from src.pacote.carregador import PacoteInvalido, raiz_do_pacote
from src.pacote.modelos import ProjetoCarregado
from src.rag.biblioteca import buscar_orientacoes, exemplos_de_referencia
from src.rag.corpus import (
    ATIVIDADE,
    DEPOIMENTO,
    ID_REGRAS,
    TABELAS_COBERTAS,
    CorpusProjeto,
    carregar_regras,
    montar_corpus,
    recuperar_contexto,
)
from src.verificacao.recalculo import so_contagem_de_entrega

ARQUIVO_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "analise_projeto.md"
TENTATIVAS = 2

# Uma consulta por criterio, para a busca trazer o que cada um precisa ler.
CONSULTAS: dict[Criterio, str] = {
    Criterio.NOVIDADE: "referência anterior manual produto runbook já existia conhecido diferença",
    Criterio.CRIATIVIDADE: "mecanismo hipótese proposta regra algoritmo parâmetros configuração faixa",
    Criterio.INCERTEZA: "incerteza hipótese alternativa comparador falha resultado desfavorável investigação",
    Criterio.SISTEMATICIDADE: "protocolo critérios roteiros versões medições cenários método",
    Criterio.TRANSFERENCIA: "limite conclusão escopo pendência continuidade reprodução registro",
}


class RespostaInvalida(ErroLLM):
    """O modelo nao devolveu uma proposta no formato pedido."""


def versao_do_prompt() -> str:
    resumo = hashlib.sha256(ARQUIVO_PROMPT.read_bytes()).hexdigest()[:8]
    return f"{ARQUIVO_PROMPT.stem}@{resumo}"


def _bloco(trechos: list[Trecho], natureza: Optional[dict[str, str]] = None) -> str:
    partes = []
    for t in trechos:
        rotulo = f" ({natureza[t.trecho_id]})" if natureza and t.trecho_id in natureza else ""
        partes.append(f"[{t.trecho_id}]{rotulo}\n{t.texto}")
    return "\n\n".join(partes)


def _sinais(corpus: CorpusProjeto) -> str:
    projeto = corpus.projeto
    linhas = []
    falhas = [c for c in corpus.conferencias if not c.ok]
    if not corpus.conferencias:
        linhas.append("- Não há resultados consolidados para conferir.")
    elif falhas:
        for c in falhas:
            linhas.append(
                f"- {c.ensaio_id} ({c.versao}): resultado NÃO confere com as medições "
                f"({c.situacao.value}). {c.detalhe}"
            )
    else:
        linhas.append(
            f"- Os {len(corpus.conferencias)} resultados consolidados conferem com as "
            "medições. Isso valida a conta, não a elegibilidade."
        )
    if so_contagem_de_entrega(projeto):
        linhas.append(
            "- Todos os resultados são contagem de entrega: medem material "
            "disponibilizado, não desempenho do mecanismo."
        )
    if projeto.ausentes:
        linhas.append(
            "- Arquivos do inventário ausentes ou ilegíveis: "
            + ", ".join(sorted(set(projeto.ausentes)))
            + ". Não presuma o conteúdo deles."
        )
    versoes = sorted({r.versao for r in projeto.resultados})
    linhas.append(f"- Versões com resultado registrado: {', '.join(versoes) or 'nenhuma'}.")
    return "\n".join(linhas)


def montar_mensagem(
    corpus: CorpusProjeto,
    contexto: list[Trecho],
    regras: list[Trecho],
    orientacoes: Optional[list[Trecho]] = None,
    exemplos: Optional[list[Trecho]] = None,
) -> str:
    estados = "\n".join(
        f"- {c.value}: " + " | ".join(ESTADOS[c]) for c in Criterio
    )
    atividades = ", ".join(a.id_atividade for a in corpus.projeto.atividades)
    sem_material = "Nenhum trecho disponível neste ambiente."
    return (
        f"Projeto em análise: {corpus.projeto.projeto_id}\n\n"
        f"# REGRAS\n\n{_bloco(regras)}\n\n"
        f"# ORIENTAÇÕES DO DESAFIO\n\n{_bloco(orientacoes) if orientacoes else sem_material}\n\n"
        f"# EXEMPLOS DE REFERÊNCIA\n\n{_bloco(exemplos) if exemplos else sem_material}\n\n"
        f"# ESTADOS PERMITIDOS\n\n{estados}\n\n"
        f"# SINAIS\n\n{_sinais(corpus)}\n\n"
        f"# EVIDÊNCIAS\n\n{_bloco(contexto, corpus.natureza)}\n\n"
        f"Atividades a classificar: {atividades or 'nenhuma'}.\n"
        "Responda com o objeto JSON descrito nas instruções."
    )


def extrair_json(texto: str) -> dict:
    """Aceita o objeto puro ou cercado por texto e por cercas de codigo."""
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fim <= inicio:
        raise RespostaInvalida("A resposta do modelo não contém um objeto JSON.")
    try:
        dados = json.loads(texto[inicio : fim + 1])
    except json.JSONDecodeError as erro:
        raise RespostaInvalida(f"JSON inválido na resposta do modelo: {erro}") from erro
    if not isinstance(dados, dict):
        raise RespostaInvalida("A resposta do modelo não é um objeto JSON.")
    return dados


def _pedir_proposta(
    cliente: ClienteLLM, sistema: str, mensagem: str
) -> tuple[PropostaModelo, str]:
    correcao = ""
    ultimo_erro: Exception | None = None
    for _ in range(TENTATIVAS):
        resposta = cliente.completar(sistema, mensagem + correcao)
        try:
            return PropostaModelo.model_validate(extrair_json(resposta.texto)), resposta.modelo
        except (RespostaInvalida, ValidationError) as erro:
            ultimo_erro = erro
            correcao = (
                "\n\nSua resposta anterior foi recusada pela validação:\n"
                f"{str(erro)[:800]}\nCorrija e responda apenas com o objeto JSON."
            )
    raise RespostaInvalida(
        f"O modelo não devolveu uma proposta válida em {TENTATIVAS} tentativas: {ultimo_erro}"
    )


def conferir_proposta(
    proposta: PropostaModelo,
    corpus: CorpusProjeto,
    contexto: list[Trecho],
    regras: list[Trecho],
    modelo: str,
) -> AnaliseConferida:
    lidos = {t.trecho_id for t in contexto}
    lidos |= {t for t in TABELAS_COBERTAS if t in corpus.trechos}
    ids_regras = {t.trecho_id for t in regras}
    descartadas: dict[str, list[str]] = {}
    avisos: list[str] = []

    def filtrar(ponto: str, fontes: list[str]) -> list[str]:
        validas: list[str] = []
        # O modelo as vezes junta varios identificadores em um campo so.
        separadas = [p for f in fontes for p in re.split(r"\s*[;,|]\s*|\s+e\s+", f) if p.strip()]
        for fonte in separadas:
            trecho_id = corpus.normalizar(fonte)
            if trecho_id in lidos:
                if trecho_id not in validas:
                    validas.append(trecho_id)
            else:
                descartadas.setdefault(ponto, []).append(fonte)
        return validas

    proposta = proposta.model_copy(deep=True)
    proposta.entendimento.fontes = filtrar("entendimento", proposta.entendimento.fontes)

    for avaliacao in proposta.criterios:
        rotulo = ROTULO_CRITERIO[avaliacao.criterio]
        avaliacao.fontes = filtrar(avaliacao.criterio.value, avaliacao.fontes)
        if avaliacao.regra not in ids_regras:
            if avaliacao.regra:
                avisos.append(f"{rotulo}: a regra citada ({avaliacao.regra}) não existe na base.")
            avaliacao.regra = ""
        if avaliacao.estado not in ESTADOS[avaliacao.criterio]:
            avisos.append(
                f"{rotulo}: o modelo usou um estado fora do vocabulário "
                f"({avaliacao.estado}); proposta rebaixada."
            )
            avaliacao.estado = estado_indeterminado(avaliacao.criterio)
        elif not avaliacao.fontes:
            avisos.append(
                f"{rotulo}: nenhuma fonte citada pelo modelo existe no contexto; "
                "proposta rebaixada para o estado indeterminado."
            )
            avaliacao.estado = estado_indeterminado(avaliacao.criterio)

    conhecidas = {a.id_atividade for a in corpus.projeto.atividades}
    proposta.atividades = [a for a in proposta.atividades if a.id_atividade in conhecidas]

    divergencias = []
    for d in proposta.divergencias:
        depoimento = filtrar("divergencias", [d.fonte_depoimento])
        registro = filtrar("divergencias", [d.fonte_registro])
        if depoimento and registro:
            d.fonte_depoimento, d.fonte_registro = depoimento[0], registro[0]
            divergencias.append(d)
    if len(divergencias) < len(proposta.divergencias):
        avisos.append(
            f"{len(proposta.divergencias) - len(divergencias)} divergência(s) apontada(s) "
            "pelo modelo foram descartadas por citar fonte inexistente."
        )
    proposta.divergencias = divergencias

    for nome in ("favoraveis", "contrarias"):
        mantidos = []
        for apontamento in getattr(proposta, nome):
            apontamento.fontes = filtrar(nome, apontamento.fontes)
            if apontamento.fontes:
                mantidos.append(apontamento)
        setattr(proposta, nome, mantidos)

    derivada, regra = derivar_classificacao(
        {c.criterio: c.estado for c in proposta.criterios}
    )
    if derivada is None:
        avisos.append("A regra de classificação não cobre esta combinação de estados.")
    elif derivada != proposta.classificacao_sugerida:
        avisos.append(
            f"O modelo sugeriu '{proposta.classificacao_sugerida}', mas a regra sobre os "
            f"estados dos critérios indica '{derivada}'. Vale a regra; confira os critérios."
        )

    return AnaliseConferida(
        projeto_id=corpus.projeto.projeto_id,
        modelo=modelo,
        versao_prompt=versao_do_prompt(),
        versao_regras=ID_REGRAS,
        proposta=proposta,
        fontes_descartadas=descartadas,
        avisos=avisos,
        contexto=[t.trecho_id for t in contexto],
        classificacao_derivada=derivada,
        regra_classificacao=regra,
    )


def _raiz_disponivel(raiz: Optional[str | Path]) -> Optional[Path]:
    try:
        return raiz_do_pacote(raiz)
    except PacoteInvalido:
        return None


def preparar_analise(
    projeto: ProjetoCarregado,
    corpus: Optional[CorpusProjeto] = None,
    raiz: Optional[str | Path] = None,
    sem_depoimento: bool = False,
) -> dict:
    """
    Tudo o que antecede a chamada ao modelo: recuperacao das evidencias, das
    orientacoes e dos exemplos, e a mensagem pronta. Separado para que a
    latencia de cada etapa possa ser medida.

    sem_depoimento tira a entrevista e as atividades do contexto: e usado
    quando outro modelo cuida do confronto e da natureza das atividades.
    """
    corpus = corpus or montar_corpus(projeto)
    regras = carregar_regras()
    contexto = recuperar_contexto(corpus, CONSULTAS.values())
    if sem_depoimento:
        contexto = [
            t for t in contexto
            if corpus.natureza.get(t.trecho_id) not in (DEPOIMENTO, ATIVIDADE)
        ]
    pacote = _raiz_disponivel(raiz)
    orientacoes = buscar_orientacoes(pacote, com_nucleo=False) if pacote else []
    # O proprio projeto nunca entra como exemplo de si mesmo.
    exemplos = exemplos_de_referencia(pacote, excluir=projeto.projeto_id) if pacote else []
    return {
        "corpus": corpus,
        "regras": regras,
        "contexto": contexto,
        "orientacoes": orientacoes,
        "exemplos": exemplos,
        "sistema": ARQUIVO_PROMPT.read_text(encoding="utf-8"),
        "mensagem": montar_mensagem(corpus, contexto, regras, orientacoes, exemplos),
    }


def analisar_projeto(
    projeto: ProjetoCarregado,
    cliente: ClienteLLM,
    corpus: Optional[CorpusProjeto] = None,
    raiz: Optional[str | Path] = None,
) -> AnaliseConferida:
    preparo = preparar_analise(projeto, corpus, raiz)
    proposta, modelo = _pedir_proposta(cliente, preparo["sistema"], preparo["mensagem"])
    analise = conferir_proposta(
        proposta,
        preparo["corpus"],
        preparo["contexto"],
        preparo["regras"] + preparo["orientacoes"],
        modelo,
    )
    analise.orientacoes = [t.trecho_id for t in preparo["orientacoes"]]
    analise.exemplos = [t.trecho_id for t in preparo["exemplos"]]
    return analise
