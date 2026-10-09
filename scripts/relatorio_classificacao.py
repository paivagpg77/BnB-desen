"""
Relatorio da classificacao dos casos para analise (PRJ21 a PRJ40).

Le as analises ja salvas em saida/analises/ e escreve, por projeto, a
classificacao proposta, a justificativa de cada criterio e as fontes que a
sustentam, com o trecho citado. Nao chama modelo: rode antes
scripts/classificar_lote.py.

Sao propostas para o analista, nao decisoes.

Uso:
    .venv/bin/python scripts/relatorio_classificacao.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src import apresentacao, ferramentas  # noqa: E402
from src.motor.fluxo import NATUREZAS, VEREDITOS, trechos_do_dossie  # noqa: E402
from src.motor.regras import ROTULO_CRITERIO, Criterio  # noqa: E402
from src.motor.schemas import AnaliseConferida  # noqa: E402

PASTA = RAIZ / "saida" / "analises"
ARQUIVO = RAIZ / "saida" / "classificacao_casos.md"
LIMITE_DO_TRECHO = 320


def _trecho(texto: str) -> str:
    limpo = " ".join(texto.split())
    return limpo if len(limpo) <= LIMITE_DO_TRECHO else limpo[:LIMITE_DO_TRECHO].rstrip() + "…"


def _fontes(ids: list[str], corpus, trechos: dict) -> list[str]:
    linhas = []
    for trecho_id in dict.fromkeys(ids):
        trecho = trechos.get(trecho_id)
        if trecho is None:
            linhas.append(f"  - `{trecho_id}`: não encontrada")
            continue
        natureza, _, _ = apresentacao.natureza_da_fonte(corpus, trecho_id)
        linhas.append(f"  - `{trecho_id}` ({natureza}; {trecho.secao}): \"{_trecho(trecho.texto)}\"")
    return linhas or ["  - Nenhuma fonte válida."]


def secao_do_projeto(analise: AnaliseConferida) -> list[str]:
    corpus = ferramentas.corpus_do_projeto(analise.projeto_id)
    trechos = trechos_do_dossie(corpus)
    proposta = analise.proposta
    classe = analise.classificacao_derivada or "Sem regra aplicável"
    auditoria = {a.criterio: a for a in (analise.orquestracao.auditoria if analise.orquestracao else [])}

    linhas = [
        f"## {analise.projeto_id} · {classe}",
        "",
        f"- **Classificação pela regra:** {classe}. {analise.regra_classificacao}",
        f"- **Classificação sugerida pelo modelo, sozinho:** {proposta.classificacao_sugerida}",
        f"- **Justificativa:** {proposta.justificativa}",
    ]
    for rotulo, texto in (
        ("Recorte sustentado", proposta.recorte_sustentado),
        ("Limitação", proposta.limitacao),
        ("Evidência necessária", proposta.evidencia_necessaria),
        ("Elo ausente", proposta.elo_ausente),
    ):
        if texto:
            linhas.append(f"- **{rotulo}:** {texto}")

    entendimento = proposta.entendimento
    linhas += [
        "",
        "### Entendimento do projeto",
        "",
        f"- Problema: {entendimento.problema}",
        f"- Estado anterior: {entendimento.estado_anterior}",
        f"- Trabalho realizado: {entendimento.trabalho_realizado}",
        "- Fontes:",
        *_fontes(entendimento.fontes, corpus, trechos),
        "",
        "### Critérios",
    ]
    for criterio in Criterio:
        avaliacao = proposta.criterio(criterio)
        linhas += [
            "",
            f"**{ROTULO_CRITERIO[criterio]}: {avaliacao.estado}**",
            "",
            f"- Justificativa: {avaliacao.justificativa}",
        ]
        if criterio in auditoria:
            item = auditoria[criterio]
            comentario = f" {item.comentario}" if item.comentario else ""
            linhas.append(f"- Auditoria por outro modelo: {VEREDITOS[item.veredito]}.{comentario}")
        linhas += [
            "- Fontes:",
            *_fontes(avaliacao.fontes + ([avaliacao.regra] if avaliacao.regra else []), corpus, trechos),
        ]

    for titulo, itens in (("Evidências favoráveis", proposta.favoraveis), ("Evidências contrárias", proposta.contrarias)):
        if itens:
            linhas += ["", f"### {titulo}", ""]
            for item in itens:
                linhas += [f"- {item.texto}", *_fontes(item.fontes, corpus, trechos)]
    if proposta.divergencias:
        linhas += ["", "### Divergências entre a entrevista e os registros", ""]
        for d in proposta.divergencias:
            linhas += [
                f"- A entrevista afirma: \"{d.depoimento}\" (`{d.fonte_depoimento}`). "
                f"O registro mostra: \"{d.registro}\" (`{d.fonte_registro}`). Prevalece: {d.prevalece}",
            ]
    if proposta.atividades:
        linhas += ["", "### Atividades", ""]
        linhas += [
            f"- `{a.id_atividade}`: {NATUREZAS[a.natureza]}. {a.justificativa}".rstrip()
            for a in proposta.atividades
        ]
    if proposta.lacunas or proposta.evidencias_a_solicitar:
        linhas += ["", "### Lacunas e evidências a solicitar", ""]
        linhas += [f"- Lacuna: {texto}" for texto in proposta.lacunas]
        linhas += [f"- Solicitar: {texto}" for texto in proposta.evidencias_a_solicitar]

    descartadas = sum(len(f) for f in analise.fontes_descartadas.values())
    papeis = analise.orquestracao.papeis if analise.orquestracao else []
    linhas += ["", "### Como a proposta foi feita", ""]
    linhas += [
        f"- {p.papel.capitalize()}: {p.provedor} ({p.modelo})" + ("" if p.concluido else ", não respondeu")
        for p in papeis
    ] or [f"- Modelo: {analise.modelo}"]
    linhas.append(
        f"- Prompt {analise.versao_prompt}, base de regras {analise.versao_regras}. "
        f"Fontes citadas pelo modelo e descartadas na conferência: {descartadas}."
    )
    linhas += [f"- Aviso: {aviso}" for aviso in analise.avisos]
    return linhas + [""]


def main() -> int:
    ids = [p["projeto_id"] for p in ferramentas.listar_projetos()]
    analises = [
        AnaliseConferida.model_validate_json((PASTA / f"{i}.json").read_text(encoding="utf-8"))
        for i in ids
        if (PASTA / f"{i}.json").is_file()
    ]
    if not analises:
        print("Nenhuma análise salva. Rode scripts/classificar_lote.py antes.")
        return 1

    contagem = Counter(a.classificacao_derivada or "Sem regra aplicável" for a in analises)
    linhas = [
        "# Classificação preliminar dos casos para análise",
        "",
        "Propostas da ferramenta para os casos do pacote. Cada classificação vem da regra "
        "aplicada aos estados dos cinco critérios; as fontes citadas foram conferidas contra "
        "os arquivos do projeto. **São propostas: a decisão é do analista.**",
        "",
        f"{len(analises)} de {len(ids)} caso(s) analisado(s): "
        + ", ".join(f"{n} {classe}" for classe, n in contagem.most_common())
        + ".",
        "",
        "| Projeto | Classificação pela regra | Sugerida pelo modelo | "
        + " | ".join(ROTULO_CRITERIO[c] for c in Criterio)
        + " |",
        "|---|---|---|" + "---|" * len(Criterio),
    ]
    for a in analises:
        estados = " | ".join(a.proposta.criterio(c).estado.capitalize() for c in Criterio)
        linhas.append(
            f"| {a.projeto_id} | {a.classificacao_derivada or 'Sem regra aplicável'} | "
            f"{a.proposta.classificacao_sugerida} | {estados} |"
        )
    faltam = [i for i in ids if i not in {a.projeto_id for a in analises}]
    if faltam:
        linhas += ["", "Ainda sem análise: " + ", ".join(faltam) + "."]
    linhas.append("")
    for analise in analises:
        linhas += secao_do_projeto(analise)

    ARQUIVO.write_text("\n".join(linhas), encoding="utf-8")
    print(f"{len(analises)} caso(s) em {ARQUIVO.relative_to(RAIZ)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
