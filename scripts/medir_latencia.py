"""
Mede a latencia de cada etapa da analise, com chamadas reais ao modelo.

Etapas: leitura do projeto, montagem do corpus (com a conferencia dos
resultados), recuperacao do contexto e montagem da mensagem, chamada ao modelo,
conferencia da proposta e criacao dos pontos de decisao. Mede tambem as
consultas usadas pelo servidor MCP.

Uso:
    .venv/bin/python scripts/medir_latencia.py --projetos PRJ21 PRJ22 PRJ23
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src import ferramentas  # noqa: E402
from src.llm.cliente import ErroLLM, cliente_padrao  # noqa: E402
from src.motor.analisador import _pedir_proposta, conferir_proposta, preparar_analise  # noqa: E402
from src.motor.fluxo import criar_pontos  # noqa: E402
from src.pacote.carregador import carregar_projeto, localizar_projetos, raiz_do_pacote  # noqa: E402
from src.rag import biblioteca  # noqa: E402
from src.rag.corpus import montar_corpus  # noqa: E402


class _Cronometro:
    def __init__(self):
        self.tempos: dict[str, float] = {}

    def medir(self, etapa: str, funcao, *argumentos):
        inicio = time.perf_counter()
        resultado = funcao(*argumentos)
        self.tempos[etapa] = round(time.perf_counter() - inicio, 4)
        return resultado


class _ClienteCronometrado:
    """Repassa ao cliente real e guarda duracao e tokens de cada chamada."""

    def __init__(self, cliente):
        self._cliente = cliente
        self.chamadas: list[dict] = []

    def completar(self, sistema, usuario, esquema=None):
        inicio = time.perf_counter()
        resposta = self._cliente.completar(sistema, usuario, esquema)
        self.chamadas.append(
            {
                "segundos": round(time.perf_counter() - inicio, 2),
                "tokens_entrada": resposta.uso.get("prompt_tokens"),
                "tokens_saida": resposta.uso.get("completion_tokens"),
            }
        )
        return resposta


def medir_projeto(projeto_id: str, pasta: Path, raiz: Path, cliente) -> dict:
    cronometro = _Cronometro()
    cronometrado = _ClienteCronometrado(cliente)

    projeto = cronometro.medir("1_leitura_do_projeto", carregar_projeto, pasta)
    corpus = cronometro.medir("2_corpus_e_conferencia", montar_corpus, projeto)
    preparo = cronometro.medir("3_recuperacao_e_mensagem", preparar_analise, projeto, corpus, raiz)
    proposta, modelo = cronometro.medir(
        "4_modelo", _pedir_proposta, cronometrado, preparo["sistema"], preparo["mensagem"]
    )
    analise = cronometro.medir(
        "5_conferencia_da_proposta",
        conferir_proposta,
        proposta,
        corpus,
        preparo["contexto"],
        preparo["regras"] + preparo["orientacoes"],
        modelo,
    )
    cronometro.medir("6_pontos_de_decisao", criar_pontos, analise)

    sem_modelo = sum(v for k, v in cronometro.tempos.items() if k != "4_modelo")
    return {
        "projeto_id": projeto_id,
        "modelo": modelo,
        "tempos_s": cronometro.tempos,
        "total_s": round(sum(cronometro.tempos.values()), 2),
        "sem_modelo_s": round(sem_modelo, 3),
        "chamadas_ao_modelo": cronometrado.chamadas,
        "mensagem_caracteres": len(preparo["mensagem"]) + len(preparo["sistema"]),
        "trechos_no_contexto": len(preparo["contexto"]),
        "classificacao_derivada": analise.classificacao_derivada,
        "fontes_descartadas": sum(len(f) for f in analise.fontes_descartadas.values()),
        "avisos": len(analise.avisos),
    }


def medir_consultas(projeto_id: str, repeticoes: int = 20) -> dict:
    """Latencia das consultas do MCP, com o corpus ja em memoria."""
    ferramentas.corpus_do_projeto(projeto_id)
    consultas = {
        "buscar_evidencias": lambda: ferramentas.buscar_evidencias(projeto_id, "hipótese mecanismo versão"),
        "ler_referencia": lambda: ferramentas.ler_referencia(projeto_id, "evidencias/metodo.md#2"),
        "conferir_resultados": lambda: ferramentas.conferir_resultados(projeto_id),
        "buscar_regras": lambda: ferramentas.buscar_regras("incerteza tecnológica"),
        "buscar_orientacoes": lambda: ferramentas.buscar_orientacoes("fonte primária derivada"),
        "buscar_pareceres_historicos": lambda: ferramentas.buscar_pareceres_historicos("configuração homologação"),
    }
    medidas = {}
    for nome, consulta in consultas.items():
        tempos = []
        for _ in range(repeticoes):
            inicio = time.perf_counter()
            consulta()
            tempos.append((time.perf_counter() - inicio) * 1000)
        medidas[nome] = {"mediana_ms": round(statistics.median(tempos), 2), "maximo_ms": round(max(tempos), 2)}
    return medidas


def main() -> int:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    argumentos.add_argument("--projetos", nargs="+", default=["PRJ21"])
    opcoes = argumentos.parse_args()

    raiz = raiz_do_pacote()
    pastas = localizar_projetos(raiz)
    try:
        cliente = cliente_padrao()
    except ErroLLM as erro:
        print(erro)
        return 1

    inicio = time.perf_counter()
    biblioteca.carregar_orientacoes(raiz)
    biblioteca.trechos_dos_historicos(raiz)
    carga_biblioteca = round(time.perf_counter() - inicio, 3)
    print(f"Biblioteca de referência (uma vez por processo): {carga_biblioteca}s")

    resultados = []
    for projeto_id in (p.upper() for p in opcoes.projetos):
        try:
            medida = medir_projeto(projeto_id, pastas[projeto_id], raiz, cliente)
        except ErroLLM as erro:
            print(f"{projeto_id}: {type(erro).__name__}: {erro}")
            resultados.append({"projeto_id": projeto_id, "erro": str(erro)})
            continue
        resultados.append(medida)
        chamadas = medida["chamadas_ao_modelo"]
        print(
            f"{projeto_id}: total {medida['total_s']}s | modelo {medida['tempos_s']['4_modelo']}s "
            f"em {len(chamadas)} chamada(s) | restante {medida['sem_modelo_s']}s | "
            f"tokens {chamadas[-1]['tokens_entrada']}→{chamadas[-1]['tokens_saida']} | "
            f"classe {medida['classificacao_derivada']}"
        )
        for etapa, segundos in medida["tempos_s"].items():
            print(f"    {etapa:<28} {segundos:>8.3f}s")

    consultas = medir_consultas(opcoes.projetos[0].upper())
    print("\nConsultas do MCP (mediana / máximo, em ms):")
    for nome, medida in consultas.items():
        print(f"    {nome:<30} {medida['mediana_ms']:>7.2f} / {medida['maximo_ms']:.2f}")

    saida = RAIZ / "saida"
    saida.mkdir(exist_ok=True)
    (saida / "latencia.json").write_text(
        json.dumps(
            {"biblioteca_s": carga_biblioteca, "projetos": resultados, "consultas_mcp": consultas},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\nDetalhe salvo em saida/latencia.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
