"""
Corpus de recuperacao (RAG) de um projeto e da base de regras.

Cada trecho usa o identificador do proprio pacote: ancora de secao
("evidencias/metodo.md#2"), identificador (PRJ21-S01, PRJ21-ATV03, PRJ21-OBS01)
ou nome de arquivo. Assim a fonte citada pelo modelo e a mesma que o analista
encontra na pasta do projeto.

O contexto enviado ao modelo tem duas partes: trechos obrigatorios (o nucleo
que toda analise precisa ler) e trechos recuperados por busca lexical, ate o
limite de tamanho. O modelo so pode citar o que esta no contexto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from src.documentos.modelos import TIPO_NORMA, TIPO_PROJETO, Trecho
from src.indexacao.bm25 import IndiceBM25
from src.ingestao.chunking import dividir
from src.ingestao.leitores import ler_documento
from src.pacote.modelos import Medicao, ProjetoCarregado, Resultado
from src.verificacao.recalculo import ConferenciaResultado, conferir_projeto

ARQUIVO_REGRAS = (
    Path(__file__).resolve().parents[2] / "dados" / "normas" / "criterios_analise.md"
)
ID_REGRAS = "regras-v1"

ORCAMENTO_PADRAO = 30000        # caracteres de evidencia do projeto no contexto
LIMITE_MEDICOES_POR_ENSAIO = 16

PRIMARIO = "registro primário"
DERIVADO = "derivado"
DEPOIMENTO = "depoimento de memória"
ESPECIFICACAO = "especificação"
REVISAO = "revisão técnica"
ATIVIDADE = "atividade (autodeclaração)"
INDICE = "índice"

# Secoes do metodo que toda analise le: referencia anterior, mecanismo,
# protocolo, parametros e limite da conclusao.
_SECOES_OBRIGATORIAS_METODO = ("1", "2", "3", "4", "6")


@dataclass
class CorpusProjeto:
    projeto: ProjetoCarregado
    trechos: dict[str, Trecho] = field(default_factory=dict)
    natureza: dict[str, str] = field(default_factory=dict)
    conferencias: list[ConferenciaResultado] = field(default_factory=list)
    indice: Optional[IndiceBM25] = None

    def normalizar(self, referencia: str) -> Optional[str]:
        """
        Converte a referencia citada no identificador de um trecho do corpus.
        Aceita "arquivo#ensaio" e o identificador da evidencia (EV) do arquivo.
        """
        ref = referencia.strip().strip("`")
        if ref in self.trechos:
            return ref
        _, separador, ancora = ref.partition("#")
        if separador and ancora in self.trechos:
            return ancora
        for evidencia in self.projeto.evidencias:
            if evidencia.id_evidencia == ref and evidencia.arquivo in self.trechos:
                return evidencia.arquivo
        return None


def _formatar(numero: Optional[float]) -> str:
    if numero is None:
        return "vazio"
    return str(int(numero)) if float(numero).is_integer() else str(numero)


def _linha_medicao(m: Medicao) -> str:
    if m.tipo == "contador":
        corpo = f"{_formatar(m.numerador)}/{_formatar(m.denominador)}"
    elif m.tipo == "histograma":
        corpo = f"valor {_formatar(m.valor)} com frequência {_formatar(m.peso)}"
    else:
        corpo = f"valor {_formatar(m.valor)}"
    return f"- {m.registro_id} | cenário {m.cenario} | {m.metrica}: {corpo} {m.unidade}"


def _texto_ensaio(
    ensaio_id: str,
    resultados: list[Resultado],
    medicoes: list[Medicao],
    conferencias: dict[tuple[str, str], ConferenciaResultado],
) -> str:
    linhas = [f"Ensaio {ensaio_id}"]
    for r in resultados:
        taxa = f"{r.taxa_percentual:.2f}%" if r.taxa_percentual is not None else "vazia"
        conferencia = conferencias.get((r.ensaio_id, r.versao))
        situacao = conferencia.situacao.value if conferencia else "não conferido"
        linhas.append(
            f"Resultado consolidado (derivado das medições): versão {r.versao}; "
            f"métrica: {r.metrica}; operação: {r.operacao}; valor: {_formatar(r.valor)} "
            f"{r.unidade}; base de cálculo: {_formatar(r.base_de_calculo)} "
            f"({r.descricao_base}); taxa: {taxa}; natureza: {r.natureza}; "
            f"conferência com medicoes.csv: {situacao}."
        )
    if not resultados:
        linhas.append("Sem linha correspondente em resultados.csv.")
    linhas.append(f"Medições primárias ({len(medicoes)} linhas):")
    linhas += [_linha_medicao(m) for m in medicoes[:LIMITE_MEDICOES_POR_ENSAIO]]
    if len(medicoes) > LIMITE_MEDICOES_POR_ENSAIO:
        linhas.append(
            f"- ... mais {len(medicoes) - LIMITE_MEDICOES_POR_ENSAIO} linhas em "
            "evidencias/medicoes.csv."
        )
    return "\n".join(linhas)


def montar_corpus(projeto: ProjetoCarregado) -> CorpusProjeto:
    corpus = CorpusProjeto(projeto=projeto, conferencias=conferir_projeto(projeto))

    def adicionar(trecho_id: str, secao: str, texto: str, natureza: str) -> None:
        if not texto.strip():
            return
        corpus.trechos[trecho_id] = Trecho(
            trecho_id=trecho_id,
            doc_id=projeto.projeto_id,
            tipo=TIPO_PROJETO,
            projeto_id=projeto.projeto_id,
            secao=secao,
            texto=texto.strip(),
        )
        corpus.natureza[trecho_id] = natureza

    for arquivo, secao, natureza in (
        ("dossie_projeto.pdf", "Dossiê do projeto", DERIVADO),
        ("registro_tecnico.pdf", "Registro técnico", DERIVADO),
    ):
        adicionar(arquivo, secao, projeto.textos.get(arquivo, ""), natureza)

    for secao in projeto.secoes:
        if secao.arquivo.endswith("metodo.md"):
            natureza = ESPECIFICACAO
        elif secao.arquivo.endswith("revisao_tecnica.md"):
            natureza = REVISAO
        else:
            natureza = DEPOIMENTO
        adicionar(secao.ancora, secao.titulo, f"{secao.titulo}\n{secao.texto}", natureza)

    if projeto.configuracao:
        parametros = projeto.configuracao.get("parametros", {})
        versoes = projeto.configuracao.get("versoes_registradas", [])
        adicionar(
            "evidencias/configuracao.json",
            "Configuração",
            f"Parâmetros: {parametros}\nVersões registradas: {', '.join(map(str, versoes))}",
            ESPECIFICACAO,
        )

    conferencias = {(c.ensaio_id, c.versao): c for c in corpus.conferencias}
    for ensaio_id in sorted(projeto.ensaios()):
        adicionar(
            ensaio_id,
            f"Ensaio {ensaio_id}",
            _texto_ensaio(
                ensaio_id,
                [r for r in projeto.resultados if r.ensaio_id == ensaio_id],
                [m for m in projeto.medicoes if m.ensaio_id == ensaio_id],
                conferencias,
            ),
            PRIMARIO,
        )

    for a in projeto.atividades:
        adicionar(
            a.id_atividade,
            f"Atividade {a.id_atividade}",
            f"Fase: {a.fase} (ciclo {a.ciclo}). Natureza informada pela equipe: "
            f"{a.natureza_informada_pela_equipe}.\nDescrição: {a.descricao}\n"
            f"Resultado ou saída: {a.resultado_ou_saida or 'vazio'}\n"
            f"Evidências relacionadas: {', '.join(a.evidencias_relacionadas) or 'nenhuma'}",
            ATIVIDADE,
        )
    for o in projeto.observacoes:
        adicionar(
            o.observacao_id,
            f"Observação {o.observacao_id}",
            f"Entrada: {o.entrada}\nReferência: {o.referencia}\n"
            f"Saída ou situação: {o.saida_ou_situacao}\nEscopo: {o.escopo}",
            PRIMARIO,
        )
    for e in projeto.entradas:
        adicionar(e.entrada_id, f"Entrada {e.entrada_id}", e.conteudo_json, PRIMARIO)
    for c in projeto.cronologia:
        adicionar(
            c.evento_id,
            f"Cronologia {c.evento_id}",
            f"{c.data} | versão {c.versao} | {c.evento} | estado: {c.estado} | fonte: {c.fonte}",
            PRIMARIO,
        )

    inventario = [
        f"- {e.id_evidencia} | {e.tipo} | {e.arquivo} | {e.observacao} | "
        f"{'arquivo entregue' if e.presente and e.arquivo not in projeto.ausentes else 'ARQUIVO AUSENTE OU ILEGÍVEL'}"
        for e in projeto.evidencias
    ]
    adicionar(
        "inventario_evidencias.csv",
        "Inventário de evidências",
        "Arquivo entregue não significa alegação comprovada.\n" + "\n".join(inventario),
        INDICE,
    )

    corpus.indice = IndiceBM25(corpus.trechos.values())
    return corpus


def _obrigatorios(corpus: CorpusProjeto) -> list[str]:
    ids = ["dossie_projeto.pdf"]
    ids += [f"evidencias/metodo.md#{n}" for n in _SECOES_OBRIGATORIAS_METODO]
    ids += [
        t for t, n in corpus.natureza.items()
        if n in (REVISAO, DEPOIMENTO) or t in corpus.projeto.ensaios()
    ]
    ids += [o.observacao_id for o in corpus.projeto.observacoes]
    ids.append("inventario_evidencias.csv")
    vistos: set[str] = set()
    return [i for i in ids if i in corpus.trechos and not (i in vistos or vistos.add(i))]


def recuperar_contexto(
    corpus: CorpusProjeto,
    consultas: Iterable[str],
    orcamento: int = ORCAMENTO_PADRAO,
    k: int = 8,
) -> list[Trecho]:
    """
    Trechos obrigatorios e, em seguida, os mais relevantes para as consultas,
    enquanto couberem no orcamento de caracteres.
    """
    escolhidos = _obrigatorios(corpus)
    usado = sum(len(corpus.trechos[i].texto) for i in escolhidos)

    candidatos: dict[str, float] = {}
    for consulta in consultas:
        for pontuacao, trecho in corpus.indice.buscar(consulta, k=k):
            if trecho.trecho_id not in escolhidos:
                candidatos[trecho.trecho_id] = max(
                    pontuacao, candidatos.get(trecho.trecho_id, 0.0)
                )
    for trecho_id, _ in sorted(candidatos.items(), key=lambda par: (-par[1], par[0])):
        tamanho = len(corpus.trechos[trecho_id].texto)
        if usado + tamanho > orcamento:
            continue
        escolhidos.append(trecho_id)
        usado += tamanho
    return [corpus.trechos[i] for i in escolhidos]


def carregar_regras(caminho: Path = ARQUIVO_REGRAS) -> list[Trecho]:
    """Base de regras dividida por secao, com identificador estavel."""
    documento = ler_documento(caminho, doc_id=ID_REGRAS, tipo=TIPO_NORMA, versao="v1")
    return dividir(documento)
