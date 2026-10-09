"""
Classifica em lote os casos para analise (PRJ21 a PRJ40), com andamento.

Para cada projeto, guarda a analise conferida completa em saida/analises/ e
uma linha de resumo com a classificacao sugerida pelo proprio modelo, a
classificacao derivada pela regra e se as duas concordam. Projeto ja analisado
e pulado, entao a rodada pode ser retomada depois de um limite de uso.

Sao propostas para o analista, nao decisoes.

Uso:
    .venv/bin/python scripts/classificar_lote.py
    .venv/bin/python scripts/classificar_lote.py --projetos PRJ21 PRJ22 --refazer
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src import ferramentas  # noqa: E402
from src.llm.cliente import ErroLLM, LimiteDeUso  # noqa: E402
from src.motor.orquestrador import analisar_com_orquestracao, papeis_padrao  # noqa: E402
from src.motor.schemas import AnaliseConferida  # noqa: E402

PASTA = RAIZ / "saida" / "analises"
ARQUIVO_LOTE = RAIZ / "saida" / "classificacao_lote.json"


def carregar_lote(arquivo: Path) -> dict[str, dict]:
    """Resumo de cada projeto nas rodadas anteriores."""
    if not arquivo.is_file():
        return {}
    return {l["projeto_id"]: l for l in json.loads(arquivo.read_text(encoding="utf-8"))}


def juntar(anteriores: dict[str, dict], linhas: list[dict]) -> list[dict]:
    """
    Resumo do lote inteiro: a rodada atualiza os projetos que tocou e mantem os
    demais. Projeto so relido do disco nao perde o tempo medido na analise.
    """
    resultado = dict(anteriores)
    for linha in linhas:
        antes = anteriores.get(linha["projeto_id"], {})
        if linha["segundos"] is None:
            linha = {**linha, "segundos": antes.get("segundos")}
        resultado[linha["projeto_id"]] = linha
    return [resultado[i] for i in sorted(resultado)]


def resumo(analise: AnaliseConferida, segundos: float | None) -> dict:
    proposta = analise.proposta
    return {
        "projeto_id": analise.projeto_id,
        "classificacao_do_modelo": proposta.classificacao_sugerida,
        "classificacao_pela_regra": analise.classificacao_derivada,
        "concordam": proposta.classificacao_sugerida == analise.classificacao_derivada,
        "estados": {c.criterio.value: c.estado for c in proposta.criterios},
        "divergencias": len(proposta.divergencias),
        "lacunas": len(proposta.lacunas),
        "fontes_descartadas": sum(len(f) for f in analise.fontes_descartadas.values()),
        "avisos": analise.avisos,
        "segundos": segundos,
        "modelo": analise.modelo,
        "prompt": analise.versao_prompt,
    }


def main() -> int:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    argumentos.add_argument("--projetos", nargs="*", help="ids a classificar (padrao: todos os casos)")
    argumentos.add_argument("--refazer", action="store_true", help="analisa de novo o que ja foi salvo")
    opcoes = argumentos.parse_args()

    todos = [p["projeto_id"] for p in ferramentas.listar_projetos()]
    ids = [p.upper() for p in opcoes.projetos] if opcoes.projetos else todos
    try:
        # Em lote, com todos os modelos sem cota, espera a cota voltar antes de desistir.
        papeis = papeis_padrao(rodadas_de_espera=3)
    except ErroLLM as erro:
        print(erro)
        return 1
    PASTA.mkdir(parents=True, exist_ok=True)

    linhas = []
    for posicao, projeto_id in enumerate(ids, start=1):
        arquivo = PASTA / f"{projeto_id}.json"
        prefixo = f"[{posicao}/{len(ids)}] {projeto_id}"
        if arquivo.is_file() and not opcoes.refazer:
            analise = AnaliseConferida.model_validate_json(arquivo.read_text(encoding="utf-8"))
            linhas.append(resumo(analise, None))
            print(f"{prefixo}: já analisado ({analise.proposta.classificacao_sugerida})", flush=True)
            continue
        corpus = ferramentas.corpus_do_projeto(projeto_id)
        inicio = time.perf_counter()
        try:
            analise = analisar_com_orquestracao(corpus.projeto, papeis, corpus)
        except LimiteDeUso as erro:
            print(f"{prefixo}: {erro} Rodada interrompida; rode de novo para continuar.", flush=True)
            break
        except ErroLLM as erro:
            print(f"{prefixo}: ERRO {type(erro).__name__}: {str(erro)[:200]}", flush=True)
            continue
        segundos = round(time.perf_counter() - inicio, 1)
        arquivo.write_text(analise.model_dump_json(indent=2), encoding="utf-8")
        linha = resumo(analise, segundos)
        linhas.append(linha)
        print(
            f"{prefixo}: modelo={linha['classificacao_do_modelo']} | "
            f"regra={linha['classificacao_pela_regra']} | "
            f"{'concordam' if linha['concordam'] else 'DIVERGEM'} | {segundos}s",
            flush=True,
        )

    ARQUIVO_LOTE.write_text(
        json.dumps(juntar(carregar_lote(ARQUIVO_LOTE), linhas), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    concordam = sum(l["concordam"] for l in linhas)
    print(f"\n{len(linhas)} de {len(ids)} projeto(s) classificados; modelo e regra concordam em {concordam}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
