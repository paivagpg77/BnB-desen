"""
Ferramentas de consulta ao pacote de projetos.

Funcoes puras, somente de leitura, que devolvem dados simples. O servidor MCP
as expoe para qualquer agente; o motor e a interface usam as mesmas funcoes,
de modo que todos leem as evidencias pelo mesmo caminho.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.pacote.carregador import carregar_projeto, localizar_projetos, raiz_do_pacote
from src.pacote.historicos import ARQUIVO_HISTORICOS, carregar_historicos
from src.rag.corpus import CorpusProjeto, carregar_regras, montar_corpus
from src.verificacao.recalculo import so_contagem_de_entrega
from src.verificacao.referencias import resolver_referencia
from src.indexacao.bm25 import IndiceBM25


class ProjetoDesconhecido(ValueError):
    pass


@lru_cache(maxsize=64)
def _corpus(raiz: str, projeto_id: str) -> CorpusProjeto:
    pastas = localizar_projetos(raiz)
    if projeto_id not in pastas:
        raise ProjetoDesconhecido(f"Projeto {projeto_id} não existe no pacote.")
    return montar_corpus(carregar_projeto(pastas[projeto_id]))


def corpus_do_projeto(projeto_id: str) -> CorpusProjeto:
    return _corpus(str(raiz_do_pacote()), projeto_id.strip().upper())


def listar_projetos() -> list[dict]:
    """Projetos do pacote, com o grupo (histórico ou caso para análise)."""
    return [
        {
            "projeto_id": projeto_id,
            "grupo": "histórico" if "01_historico" in pasta.parts else "caso para análise",
        }
        for projeto_id, pasta in localizar_projetos(raiz_do_pacote()).items()
    ]


def resumo_do_projeto(projeto_id: str) -> dict:
    """Inventário, versões, ensaios e arquivos ausentes de um projeto."""
    corpus = corpus_do_projeto(projeto_id)
    projeto = corpus.projeto
    return {
        "projeto_id": projeto.projeto_id,
        "evidencias": [
            {"id": e.id_evidencia, "tipo": e.tipo, "arquivo": e.arquivo, "entregue": e.presente}
            for e in projeto.evidencias
        ],
        "arquivos_ausentes": sorted(set(projeto.ausentes)),
        "atividades": [a.id_atividade for a in projeto.atividades],
        "ensaios": sorted(projeto.ensaios()),
        "versoes": sorted({r.versao for r in projeto.resultados}),
        "so_contagem_de_entrega": so_contagem_de_entrega(projeto),
        "trechos_disponiveis": len(corpus.trechos),
    }


def buscar_evidencias(projeto_id: str, consulta: str, k: int = 5) -> list[dict]:
    """Busca lexical nos trechos do projeto. Devolve identificador, natureza e texto."""
    corpus = corpus_do_projeto(projeto_id)
    return [
        {
            "trecho_id": trecho.trecho_id,
            "natureza": corpus.natureza.get(trecho.trecho_id, ""),
            "secao": trecho.secao,
            "pontuacao": round(pontuacao, 3),
            "texto": trecho.texto,
        }
        for pontuacao, trecho in corpus.indice.buscar(consulta, k=max(1, min(k, 20)))
    ]


def ler_referencia(projeto_id: str, referencia: str) -> dict:
    """Texto de uma fonte citada (identificador, arquivo ou âncora), se existir."""
    corpus = corpus_do_projeto(projeto_id)
    resolvida = resolver_referencia(corpus.projeto, referencia)
    trecho_id = corpus.normalizar(referencia)
    trecho = corpus.trechos.get(trecho_id) if trecho_id else None
    return {
        "referencia": referencia,
        "existe": resolvida.existe,
        "tipo": resolvida.tipo.value,
        "detalhe": resolvida.detalhe,
        "trecho_id": trecho_id,
        "natureza": corpus.natureza.get(trecho_id, "") if trecho_id else "",
        "texto": trecho.texto if trecho else "",
    }


def conferir_resultados(projeto_id: str) -> list[dict]:
    """Recalcula cada resultado consolidado a partir das medições primárias."""
    return [
        {
            "ensaio_id": c.ensaio_id,
            "versao": c.versao,
            "operacao": c.operacao,
            "natureza": c.natureza,
            "situacao": c.situacao.value,
            "valor_registrado": c.valor_registrado,
            "valor_recalculado": c.valor_recalculado,
            "base_registrada": c.base_registrada,
            "base_recalculada": c.base_recalculada,
            "detalhe": c.detalhe,
        }
        for c in corpus_do_projeto(projeto_id).conferencias
    ]


def buscar_regras(consulta: str, k: int = 3) -> list[dict]:
    """Busca na base de regras da ferramenta (critérios, classes, evidências)."""
    indice = IndiceBM25(carregar_regras())
    return [
        {"regra_id": t.trecho_id, "secao": t.secao, "pontuacao": round(p, 3), "texto": t.texto}
        for p, t in indice.buscar(consulta, k=max(1, min(k, 10)))
    ]


def parecer_historico(projeto_id: str) -> dict:
    """
    Parecer de referência de um projeto histórico (PRJ01 a PRJ20). Serve para
    calibrar o nível de fundamentação, não para classificar outro projeto por
    semelhança.
    """
    raiz = raiz_do_pacote()
    if not (Path(raiz) / ARQUIVO_HISTORICOS).is_file():
        raise ProjetoDesconhecido("Arquivo de históricos não encontrado no pacote.")
    parecer = carregar_historicos(raiz).get(projeto_id.strip().upper())
    if parecer is None:
        raise ProjetoDesconhecido(f"{projeto_id} não é um projeto histórico classificado.")
    return {
        "projeto_id": parecer.projeto_id,
        "titulo": parecer.titulo,
        "classificacao": parecer.classificacao,
        "justificativa": parecer.justificativa,
        "limite": parecer.limite,
        "divergencia_depoimento": parecer.divergencia_depoimento,
        "criterios": [
            {"criterio": c.criterio, "estado": c.estado, "justificativa": c.justificativa, "fonte": c.fonte}
            for c in parecer.criterios
        ],
    }
