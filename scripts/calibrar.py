"""
Regressao do motor contra os projetos historicos (PRJ01 a PRJ20).

Compara, por projeto, a classificacao derivada e o estado de cada criterio com
o parecer de referencia. Cada projeto custa uma chamada ao modelo; com modelo
gratuito, use --limite para caber na cota diaria.

Uso:
    .venv/bin/python scripts/calibrar.py --limite 5
    .venv/bin/python scripts/calibrar.py --projetos PRJ01 PRJ08
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src import ferramentas  # noqa: E402
from src.llm.cliente import ErroLLM, LimiteDeUso  # noqa: E402
from src.motor.orquestrador import analisar_com_orquestracao, papeis_padrao  # noqa: E402
from src.motor.regras import ROTULO_CRITERIO  # noqa: E402
from src.pacote.carregador import raiz_do_pacote  # noqa: E402
from src.pacote.historicos import carregar_historicos  # noqa: E402


def main() -> int:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    argumentos.add_argument("--projetos", nargs="*", help="ids a avaliar (padrao: todos os historicos)")
    argumentos.add_argument("--limite", type=int, help="numero maximo de projetos nesta rodada")
    opcoes = argumentos.parse_args()

    historicos = carregar_historicos(raiz_do_pacote())
    ids = [p.upper() for p in opcoes.projetos] if opcoes.projetos else sorted(historicos)
    ids = ids[: opcoes.limite] if opcoes.limite else ids
    try:
        papeis = papeis_padrao()
    except ErroLLM as erro:
        print(erro)
        return 1
    por_rotulo = {rotulo: criterio for criterio, rotulo in ROTULO_CRITERIO.items()}

    linhas = []
    for projeto_id in ids:
        parecer = historicos[projeto_id]
        corpus = ferramentas.corpus_do_projeto(projeto_id)
        try:
            analise = analisar_com_orquestracao(corpus.projeto, papeis, corpus)
        except LimiteDeUso as erro:
            print(f"{projeto_id}: {erro} Rodada interrompida.")
            break
        except ErroLLM as erro:
            print(f"{projeto_id}: ERRO {erro}")
            linhas.append({"projeto_id": projeto_id, "erro": str(erro)})
            continue
        criterios_iguais = sum(
            analise.proposta.criterio(por_rotulo[c.criterio]).estado == c.estado
            for c in parecer.criterios
        )
        linha = {
            "projeto_id": projeto_id,
            "referencia": parecer.classificacao,
            "derivada": analise.classificacao_derivada,
            "sugerida_pelo_modelo": analise.proposta.classificacao_sugerida,
            "acertou": analise.classificacao_derivada == parecer.classificacao,
            "modelo_acertou": analise.proposta.classificacao_sugerida == parecer.classificacao,
            "criterios_iguais": criterios_iguais,
            "divergencia_esperada": bool(parecer.divergencia_depoimento),
            "divergencias_encontradas": len(analise.proposta.divergencias),
            "fontes_descartadas": sum(len(f) for f in analise.fontes_descartadas.values()),
            "modelo": analise.modelo,
            "prompt": analise.versao_prompt,
        }
        linhas.append(linha)
        print(
            f"{projeto_id}: {'OK ' if linha['acertou'] else 'ERRO'} "
            f"referência={linha['referencia']} | derivada={linha['derivada']} | "
            f"critérios iguais={criterios_iguais}/5 | "
            f"modelo sozinho={linha['sugerida_pelo_modelo']} | "
            f"fontes descartadas={linha['fontes_descartadas']}",
            flush=True,
        )

    avaliados = [l for l in linhas if "erro" not in l]
    if avaliados:
        acertos = sum(l["acertou"] for l in avaliados)
        criterios = sum(l["criterios_iguais"] for l in avaliados)
        do_modelo = sum(l["modelo_acertou"] for l in avaliados)
        print(
            f"\nClassificação pela regra: {acertos}/{len(avaliados)} | "
            f"classificação do modelo sozinho: {do_modelo}/{len(avaliados)} | "
            f"critérios: {criterios}/{5 * len(avaliados)}"
        )
    saida = RAIZ / "saida"
    saida.mkdir(exist_ok=True)
    (saida / "calibracao.json").write_text(
        json.dumps(linhas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Detalhe salvo em saida/calibracao.json ({len(linhas)} projeto(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
