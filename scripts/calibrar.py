"""
Regressao do motor contra os projetos historicos (PRJ01 a PRJ20).

Compara, por projeto, a classificacao derivada e o estado de cada criterio com
o parecer de referencia. Cada projeto custa uma chamada ao modelo; com modelo
gratuito, use --limite para caber na cota diaria.

As rodadas se acumulam em saida/calibracao.json: projeto ja avaliado com o
prompt atual nao e refeito, entao basta repetir o comando ate cobrir os vinte.
Mudou o prompt, os resultados antigos deixam de valer e sao refeitos.

Uso:
    .venv/bin/python scripts/calibrar.py --limite 5
    .venv/bin/python scripts/calibrar.py --projetos PRJ01 PRJ08
    .venv/bin/python scripts/calibrar.py --refazer
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src import ferramentas  # noqa: E402
from src.llm.cliente import ErroLLM, LimiteDeUso  # noqa: E402
from src.motor.analisador import versao_do_prompt  # noqa: E402
from src.motor.orquestrador import analisar_com_orquestracao, papeis_padrao  # noqa: E402
from src.motor.regras import ROTULO_CRITERIO  # noqa: E402
from src.pacote.carregador import PacoteInvalido, raiz_do_pacote  # noqa: E402
from src.pacote.historicos import carregar_historicos  # noqa: E402

ARQUIVO_SAIDA = RAIZ / "saida" / "calibracao.json"


def carregar_rodadas(arquivo: Path) -> dict[str, dict]:
    """Resultado mais recente de cada projeto nas rodadas anteriores."""
    if not arquivo.is_file():
        return {}
    return {l["projeto_id"]: l for l in json.loads(arquivo.read_text(encoding="utf-8"))}


def avaliado(linha: Optional[dict], prompt: str) -> bool:
    """Vale o resultado sem erro obtido com o prompt atual."""
    return bool(linha) and "erro" not in linha and linha.get("prompt") == prompt


def a_avaliar(
    ids: list[str],
    anteriores: dict[str, dict],
    prompt: str,
    refazer: bool = False,
    limite: Optional[int] = None,
) -> list[str]:
    pendentes = [i for i in ids if refazer or not avaliado(anteriores.get(i), prompt)]
    return pendentes[:limite] if limite else pendentes


def resumo(linhas: list[dict]) -> str:
    acertos = sum(l["acertou"] for l in linhas)
    criterios = sum(l["criterios_iguais"] for l in linhas)
    do_modelo = sum(l["modelo_acertou"] for l in linhas)
    return (
        f"Classificação pela regra: {acertos}/{len(linhas)} | "
        f"classificação do modelo sozinho: {do_modelo}/{len(linhas)} | "
        f"critérios: {criterios}/{5 * len(linhas)}"
    )


def main() -> int:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    argumentos.add_argument("--projetos", nargs="*", help="ids a avaliar (padrao: todos os historicos)")
    argumentos.add_argument("--limite", type=int, help="numero maximo de projetos nesta rodada")
    argumentos.add_argument("--refazer", action="store_true", help="reavalia tambem os ja avaliados")
    argumentos.add_argument("--saida", type=Path, default=ARQUIVO_SAIDA, help="arquivo de resultados")
    opcoes = argumentos.parse_args()

    try:
        historicos = carregar_historicos(raiz_do_pacote())
    except PacoteInvalido as erro:
        print(erro)
        return 1
    ids = [p.upper() for p in opcoes.projetos] if opcoes.projetos else sorted(historicos)
    desconhecidos = [i for i in ids if i not in historicos]
    if desconhecidos:
        print(f"Sem parecer de referência: {', '.join(desconhecidos)}.")
        return 1
    prompt = versao_do_prompt()
    resultados = carregar_rodadas(opcoes.saida)
    rodada = a_avaliar(ids, resultados, prompt, opcoes.refazer, opcoes.limite)
    if len(rodada) < len(ids):
        print(f"{len(ids) - len(rodada)} projeto(s) ficam fora desta rodada: já avaliados ou além do limite.")
    if rodada:
        try:
            # Em lote, com todos os modelos sem cota, espera a cota voltar antes de desistir.
            papeis = papeis_padrao(rodadas_de_espera=3)
        except ErroLLM as erro:
            print(erro)
            return 1
    por_rotulo = {rotulo: criterio for criterio, rotulo in ROTULO_CRITERIO.items()}

    def salvar() -> None:
        # A cada projeto: uma rodada interrompida nao perde o que ja foi avaliado.
        linhas = [resultados[i] for i in sorted(resultados)]
        opcoes.saida.parent.mkdir(parents=True, exist_ok=True)
        opcoes.saida.write_text(json.dumps(linhas, ensure_ascii=False, indent=2), encoding="utf-8")

    for projeto_id in rodada:
        parecer = historicos[projeto_id]
        corpus = ferramentas.corpus_do_projeto(projeto_id)
        try:
            analise = analisar_com_orquestracao(corpus.projeto, papeis, corpus)
        except LimiteDeUso as erro:
            print(f"{projeto_id}: {erro} Rodada interrompida.")
            break
        except ErroLLM as erro:
            print(f"{projeto_id}: ERRO {erro}")
            resultados[projeto_id] = {"projeto_id": projeto_id, "erro": str(erro)}
            salvar()
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
            "modelos_por_papel": {
                p.papel: f"{p.provedor} ({p.modelo})"
                for p in analise.orquestracao.papeis
                if p.concluido
            },
            "prompt": analise.versao_prompt,
        }
        resultados[projeto_id] = linha
        salvar()
        print(
            f"{projeto_id}: {'OK ' if linha['acertou'] else 'ERRO'} "
            f"referência={linha['referencia']} | derivada={linha['derivada']} | "
            f"critérios iguais={criterios_iguais}/5 | "
            f"modelo sozinho={linha['sugerida_pelo_modelo']} | "
            f"fontes descartadas={linha['fontes_descartadas']}",
            flush=True,
        )

    linhas = [resultados[i] for i in sorted(resultados)]
    avaliados = [l for l in linhas if avaliado(l, prompt)]
    if avaliados:
        print(f"\n{resumo(avaliados)}")
    faltam = [i for i in sorted(historicos) if not avaliado(resultados.get(i), prompt)]
    print(
        f"Calibração com o prompt {prompt}: {len(historicos) - len(faltam)} de "
        f"{len(historicos)} históricos avaliados."
        + (f" Faltam: {', '.join(faltam)}." if faltam else "")
    )
    salvar()
    print(f"Detalhe salvo em {opcoes.saida} ({len(linhas)} projeto(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
