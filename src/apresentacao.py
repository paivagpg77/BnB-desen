"""
Textos de apresentacao das verificacoes e das fontes, sem depender da tela.

A interface so desenha: o que dizer sobre cada conferencia e cada fonte e
decidido aqui, para poder ser testado.
"""

from __future__ import annotations

from typing import Optional

from src.motor.regras import ROTULO_CRITERIO, Criterio
from src.rag.biblioteca import PREFIXO_HISTORICO
from src.rag.corpus import (
    ATIVIDADE,
    DEPOIMENTO,
    DERIVADO,
    ESPECIFICACAO,
    INDICE,
    PRIMARIO,
    REVISAO,
    CorpusProjeto,
)

# situacao -> (rotulo, cor do selo)
SITUACOES = {
    "confere": ("Confere", "green"),
    "transcricao_confere": ("Transcrição conferida", "blue"),
    "diverge": ("Diverge", "red"),
    "sem_medicoes": ("Sem medições", "orange"),
    "nao_recalculavel": ("Não recalculável", "orange"),
}

OPERACOES = {
    "contagem": "contagem",
    "media": "média",
    "mediana": "mediana",
    "diferenca_maior_menor": "diferença entre o maior e o menor",
    "percentil_95": "percentil 95",
    "valor_observado": "valor observado",
    "indicador_precalculado": "indicador já calculado",
}

# natureza da fonte -> (cor do selo, o que isso significa para o analista)
NATUREZAS = {
    PRIMARIO: ("green", "registro mais próximo do que foi medido"),
    ESPECIFICACAO: ("blue", "descreve o método e os parâmetros"),
    REVISAO: ("blue", "revisão técnica do material entregue"),
    DERIVADO: ("orange", "resume outros registros; não é confirmação independente"),
    DEPOIMENTO: ("violet", "memória da equipe; precisa ser confrontada com os registros"),
    ATIVIDADE: ("orange", "relato da equipe sobre o próprio trabalho"),
    INDICE: ("gray", "lista os arquivos entregues"),
}
REGRA = "regra da ferramenta"
ORIENTACAO = "orientação do desafio"


def numero(valor: Optional[float]) -> str:
    """Numero no padrao brasileiro, sem casas decimais desnecessarias."""
    if valor is None:
        return "vazio"
    if float(valor).is_integer():
        return f"{int(valor):,}".replace(",", ".")
    return f"{valor:,.4f}".rstrip("0").rstrip(".").replace(",", "§").replace(".", ",").replace("§", ".")


def leitura_do_resultado(valor: Optional[float], base: Optional[float], operacao: str, unidade: str) -> str:
    """'8 de 9 casos (88,9%)' para contagem; '120 ms' para as demais operacoes."""
    if valor is None:
        return "sem valor"
    if operacao == "contagem" and base:
        return f"{numero(valor)} de {numero(base)} {unidade} ({numero(round(100 * valor / base, 2))}%)"
    return f"{numero(valor)} {unidade}".strip()


def linha_da_conferencia(c: dict) -> dict:
    """Uma linha legivel da tabela de conferencia."""
    rotulo, _ = SITUACOES.get(c["situacao"], (c["situacao"], "gray"))
    registrado = leitura_do_resultado(c["valor_registrado"], c["base_registrada"], c["operacao"], c["unidade"])
    recalculado = leitura_do_resultado(c["valor_recalculado"], c["base_recalculada"], c["operacao"], c["unidade"])
    return {
        "Ensaio": c["ensaio_id"],
        "Versão": c["versao"],
        "O que foi medido": c["metrica"],
        "Como foi calculado": OPERACOES.get(c["operacao"], c["operacao"]),
        "Registrado em resultados.csv": registrado,
        "Recalculado das medições": recalculado,
        "Situação": rotulo,
        "Tipo": "desempenho" if c["natureza"] == "desempenho" else "entrega de material",
    }


def resumo_da_conferencia(conferencias: list[dict]) -> dict:
    conferem = sum(c["situacao"] in ("confere", "transcricao_confere") for c in conferencias)
    return {
        "total": len(conferencias),
        "conferem": conferem,
        "com_problema": len(conferencias) - conferem,
        "de_entrega": sum(c["natureza"] != "desempenho" for c in conferencias),
    }


def natureza_da_fonte(corpus: CorpusProjeto, trecho_id: str) -> tuple[str, str, str]:
    """(natureza, cor do selo, explicacao) de uma fonte citada."""
    natureza = corpus.natureza.get(trecho_id)
    if natureza:
        cor, explicacao = NATUREZAS.get(natureza, ("gray", ""))
        return natureza, cor, explicacao
    if trecho_id.startswith("regras-"):
        return REGRA, "gray", "critério aplicado, da base de regras versionada"
    return ORIENTACAO, "gray", "trecho dos guias ou do dicionário do desafio"


def agrupar_fontes(porque: list[dict]) -> list[tuple[str, list[str]]]:
    """Junta as fontes de uma mesma afirmacao, preservando a ordem."""
    grupos: dict[str, list[str]] = {}
    for item in porque:
        fontes = grupos.setdefault(item["afirmacao"], [])
        if item["trecho_id"] not in fontes:
            fontes.append(item["trecho_id"])
    return list(grupos.items())


def nome_do_ponto(chave: str) -> str:
    """Nome legivel do ponto em que uma fonte foi descartada."""
    try:
        return ROTULO_CRITERIO[Criterio(chave)]
    except ValueError:
        return {
            "entendimento": "Entendimento do projeto",
            "divergencias": "Divergências",
            "favoraveis": "Evidências favoráveis",
            "contrarias": "Evidências contrárias",
        }.get(chave, chave)


def fontes_descartadas(corpus: CorpusProjeto, descartadas: dict[str, list[str]]) -> list[dict]:
    """Cada fonte que o modelo citou e a conferencia recusou, com o motivo."""
    linhas = []
    for ponto, fontes in descartadas.items():
        for fonte in fontes:
            if fonte.startswith(PREFIXO_HISTORICO):
                motivo = "É de um parecer histórico usado como exemplo, não deste projeto."
            elif corpus.normalizar(fonte) is not None:
                motivo = "Existe no projeto, mas não estava entre os trechos enviados ao modelo."
            elif "#" not in fonte and "/" in fonte or fonte.endswith((".csv", ".md", ".pdf", ".json", ".xlsx")):
                motivo = "Cita um arquivo inteiro; a análise exige o trecho específico."
            else:
                motivo = "Não existe neste projeto."
            linhas.append({"Onde foi citada": nome_do_ponto(ponto), "Fonte citada": fonte, "Por que foi descartada": motivo})
    return linhas


def texto_em_blocos(texto: str) -> list[tuple[str, str]]:
    """
    Reorganiza o texto de uma fonte para leitura: ("titulo", ...), ("item", ...)
    ou ("paragrafo", ...). Linhas quebradas pela extracao do PDF voltam a formar
    um paragrafo; linha curta sem pontuacao final e tratada como titulo.
    """
    blocos: list[tuple[str, str]] = []
    paragrafo: list[str] = []

    def fechar() -> None:
        if paragrafo:
            blocos.append(("paragrafo", " ".join(paragrafo)))
            paragrafo.clear()

    linhas = [l.strip() for l in texto.splitlines()]
    for posicao, linha in enumerate(linhas):
        seguinte = next((l for l in linhas[posicao + 1 :] if l), "")
        if not linha:
            fechar()
        elif linha.startswith("- "):
            fechar()
            blocos.append(("item", linha[2:]))
        elif (
            not paragrafo
            and len(linha) <= 45
            and linha[-1] not in ".;:,?!)"
            # Linha seguinte em minuscula e continuacao da frase, nao corpo de um titulo.
            and not seguinte[:1].islower()
        ):
            blocos.append(("titulo", linha))
        else:
            paragrafo.append(linha)
            if linha[-1] in ".?!":
                fechar()
    fechar()
    return blocos
