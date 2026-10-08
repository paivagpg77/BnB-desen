"""
Carregador do pacote de projetos do desafio.

Convencoes do pacote (LEIA_ME): CSV em UTF-8 com BOM, separador ponto e
virgula, ponto decimal. Campo vazio e ausencia de informacao, nunca zero.

atividades.xlsx nao e lido: o inventario declara atividades.csv como os mesmos
registros em formato aberto.
"""

from __future__ import annotations

import csv
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Optional

from src.config import carregar_env
from src.pacote.modelos import (
    Atividade,
    Entrada,
    Evidencia,
    EventoCronologia,
    Medicao,
    Observacao,
    ProjetoCarregado,
    Resultado,
    Secao,
)

VARIAVEL_PACOTE = "LEI_DO_BEM_PACOTE"

_CABECALHO_MD = re.compile(r"^##\s+(.*\S)\s*$")
_NUMERO_SECAO = re.compile(r"^(\d+)\.\s+(.*)$")
_PERGUNTA = re.compile(r"^\s*(\d+)\.\s+(.*\?)\s*$")


class PacoteInvalido(ValueError):
    pass


def raiz_do_pacote(caminho: Optional[str | Path] = None) -> Path:
    """Pasta raiz do pacote extraido. A massa fica fora do repositorio."""
    carregar_env()
    valor = caminho or os.environ.get(VARIAVEL_PACOTE)
    if not valor:
        raise PacoteInvalido(
            f"Informe a pasta do pacote ou defina {VARIAVEL_PACOTE} no arquivo .env."
        )
    raiz = Path(valor).expanduser()
    if not (raiz / "01_projetos").is_dir():
        raise PacoteInvalido(f"Pasta 01_projetos nao encontrada em {raiz}.")
    return raiz


def localizar_projetos(raiz: str | Path) -> dict[str, Path]:
    """Mapa projeto_id -> pasta, para historicos e casos para analise."""
    pastas = sorted(Path(raiz).glob("01_projetos/*/PRJ*"))
    return {p.name: p for p in pastas if p.is_dir()}


def ler_csv_pacote(caminho: Path) -> list[dict[str, str]]:
    with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
        return list(csv.DictReader(arquivo, delimiter=";"))


def numero(texto: Optional[str]) -> Optional[float]:
    """Converte campo numerico. Vazio ou 'null' vira None, nunca zero."""
    if texto is None:
        return None
    limpo = texto.strip()
    if not limpo or limpo.lower() == "null":
        return None
    return float(limpo)


def extrair_texto_pdf(caminho: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as erro:
        raise PacoteInvalido(
            "Leitura de PDF exige a biblioteca pypdf (pip install pypdf)."
        ) from erro
    leitor = PdfReader(str(caminho))
    linhas = [
        linha
        for pagina in leitor.pages
        for linha in (pagina.extract_text() or "").splitlines()
        # Rodape repetido e numero de pagina nao sao conteudo do documento.
        if not linha.strip().isdigit() and not linha.startswith("Massa inteiramente fictícia")
    ]
    return "\n".join(linhas)


def _slug(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")


def dividir_secoes_md(arquivo: str, texto: str) -> list[Secao]:
    """
    Uma secao por cabecalho "##". Cabecalho numerado ("## 2. Titulo") gera a
    ancora "arquivo#2", que e a forma usada nos pareceres historicos. Cabecalho
    sem numero gera "arquivo#titulo-em-slug".
    """
    secoes: list[Secao] = []
    titulo: Optional[str] = None
    linhas: list[str] = []

    def fechar() -> None:
        if titulo is None:
            return
        numerado = _NUMERO_SECAO.match(titulo)
        identificador = numerado.group(1) if numerado else _slug(titulo)
        secoes.append(
            Secao(
                ancora=f"{arquivo}#{identificador}",
                arquivo=arquivo,
                titulo=titulo,
                texto="\n".join(linhas).strip(),
            )
        )

    for linha in texto.splitlines():
        cabecalho = _CABECALHO_MD.match(linha)
        if cabecalho:
            fechar()
            titulo = cabecalho.group(1)
            linhas = []
        elif titulo is not None:
            linhas.append(linha)
    fechar()
    return secoes


def dividir_perguntas(arquivo: str, texto: str) -> list[Secao]:
    """Uma secao por pergunta numerada da entrevista: "arquivo#N"."""
    secoes: list[Secao] = []
    numero_atual: Optional[str] = None
    pergunta = ""
    linhas: list[str] = []

    def fechar() -> None:
        if numero_atual is None:
            return
        secoes.append(
            Secao(
                ancora=f"{arquivo}#{numero_atual}",
                arquivo=arquivo,
                titulo=pergunta,
                texto=" ".join(" ".join(linhas).split()),
            )
        )

    for linha in texto.splitlines():
        encontrada = _PERGUNTA.match(linha)
        if encontrada:
            fechar()
            numero_atual, pergunta = encontrada.group(1), encontrada.group(2)
            linhas = []
        elif numero_atual is not None:
            # O rodape "Condicao do registro" encerra a ultima resposta.
            if linha.strip().startswith(("Condição do registro", "Condicao do registro")):
                fechar()
                numero_atual = None
            else:
                linhas.append(linha)
    fechar()
    return secoes


def _evidencias(pasta: Path) -> list[Evidencia]:
    inventario = pasta / "inventario_evidencias.csv"
    if not inventario.is_file():
        raise PacoteInvalido(f"inventario_evidencias.csv nao encontrado em {pasta}.")
    return [
        Evidencia(
            id_evidencia=linha["id_evidencia"],
            tipo=linha["tipo"],
            arquivo=linha["arquivo"],
            conteudo_esperado=linha["conteudo_esperado"],
            status=linha["status"],
            observacao=linha["observacao"],
            presente=(pasta / linha["arquivo"]).is_file(),
        )
        for linha in ler_csv_pacote(inventario)
    ]


def _atividade(linha: dict[str, str]) -> Atividade:
    relacionadas = tuple(
        parte.strip() for parte in linha["evidencias_relacionadas"].split("|") if parte.strip()
    )
    return Atividade(
        id_atividade=linha["id_atividade"],
        ciclo=linha["ciclo"],
        fase=linha["fase"],
        natureza_informada_pela_equipe=linha["natureza_informada_pela_equipe"],
        descricao=linha["descricao"],
        resultado_ou_saida=linha["resultado_ou_saida"],
        evidencias_relacionadas=relacionadas,
        responsavel_por_funcao=linha["responsavel_por_funcao"],
    )


def _medicao(linha: dict[str, str]) -> Medicao:
    return Medicao(
        registro_id=linha["registro_id"],
        ensaio_id=linha["ensaio_id"],
        versao=linha["versao"],
        cenario=linha["cenario"],
        tipo=linha["tipo"],
        metrica=linha["metrica"],
        valor=numero(linha["valor"]),
        numerador=numero(linha["numerador"]),
        denominador=numero(linha["denominador"]),
        peso=numero(linha["peso"]),
        unidade=linha["unidade"],
    )


def _resultado(linha: dict[str, str]) -> Resultado:
    return Resultado(
        ensaio_id=linha["ensaio_id"],
        versao=linha["versao"],
        metrica=linha["metrica"],
        operacao=linha["operacao"],
        valor=numero(linha["valor"]),
        base_de_calculo=numero(linha["base_de_calculo"]),
        descricao_base=linha["descricao_base"],
        taxa_percentual=numero(linha["taxa_percentual"]),
        unidade=linha["unidade"],
        fonte=linha["fonte"],
        natureza=linha["natureza"],
    )


def carregar_projeto(pasta: str | Path) -> ProjetoCarregado:
    pasta = Path(pasta)
    if not pasta.is_dir():
        raise PacoteInvalido(f"Pasta de projeto nao encontrada: {pasta}.")

    evidencias = _evidencias(pasta)
    projeto = ProjetoCarregado(projeto_id=pasta.name, pasta=pasta, evidencias=evidencias)
    projeto.ausentes = [e.arquivo for e in evidencias if not e.presente]

    def linhas(arquivo: str) -> list[dict[str, str]]:
        caminho = pasta / arquivo
        if not caminho.is_file():
            return []
        projeto.textos[arquivo] = caminho.read_text(encoding="utf-8-sig")
        return ler_csv_pacote(caminho)

    projeto.textos["inventario_evidencias.csv"] = (
        pasta / "inventario_evidencias.csv"
    ).read_text(encoding="utf-8-sig")
    projeto.atividades = [_atividade(l) for l in linhas("atividades.csv")]
    projeto.medicoes = [_medicao(l) for l in linhas("evidencias/medicoes.csv")]
    projeto.resultados = [_resultado(l) for l in linhas("evidencias/resultados.csv")]
    projeto.cronologia = [
        EventoCronologia(**l) for l in linhas("evidencias/cronologia.csv")
    ]
    projeto.observacoes = [
        Observacao(**l) for l in linhas("evidencias/observacoes.csv")
    ]
    projeto.entradas = [Entrada(**l) for l in linhas("evidencias/entradas.csv")]

    configuracao = pasta / "evidencias/configuracao.json"
    if configuracao.is_file():
        bruto = configuracao.read_text(encoding="utf-8-sig")
        projeto.textos["evidencias/configuracao.json"] = bruto
        projeto.configuracao = json.loads(bruto)

    for arquivo in ("evidencias/metodo.md", "evidencias/revisao_tecnica.md"):
        caminho = pasta / arquivo
        if caminho.is_file():
            texto = caminho.read_text(encoding="utf-8-sig")
            projeto.textos[arquivo] = texto
            projeto.secoes += dividir_secoes_md(arquivo, texto)

    for evidencia in evidencias:
        if not evidencia.presente or not evidencia.arquivo.lower().endswith(".pdf"):
            continue
        try:
            texto = extrair_texto_pdf(pasta / evidencia.arquivo)
        except Exception:
            # PDF ilegivel conta como ausente: a analise nao pode presumir seu conteudo.
            projeto.ausentes.append(evidencia.arquivo)
            continue
        projeto.textos[evidencia.arquivo] = texto
        if evidencia.tipo == "Entrevista":
            projeto.secoes += dividir_perguntas(evidencia.arquivo, texto)

    return projeto
