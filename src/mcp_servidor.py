"""
Servidor MCP da ferramenta: acesso padronizado, somente de leitura, as
evidencias dos projetos, as verificacoes deterministicas e a base de regras.

Nenhuma ferramenta daqui decide ou classifica: elas entregam evidencia com
identificador, para que quem consulta (pessoa ou agente) cite a fonte.

Uso (transporte stdio):
    .venv/bin/python -m src.mcp_servidor
"""

from __future__ import annotations

from functools import wraps

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from src import ferramentas
from src.pacote.carregador import PacoteInvalido

INSTRUCOES = (
    "Evidências de projetos para análise preliminar de elegibilidade à Lei do Bem. "
    "Toda afirmação sobre um projeto deve citar o trecho_id devolvido pelas "
    "ferramentas. Entrevista é depoimento de memória; medições são registro "
    "primário. Os projetos históricos e seus pareceres são referência de como "
    "fundamentar, nunca base para classificar outro projeto por semelhança. "
    "As ferramentas não classificam projetos: a decisão é do analista."
)

servidor = MCPServer("lei-do-bem-analise", instructions=INSTRUCOES)


def _com_erro_claro(funcao):
    """
    Projeto que nao existe ou pacote mal configurado sao erros de quem consulta:
    a mensagem chega a ele, em vez do erro generico de falha do servidor.
    """

    @wraps(funcao)
    def ferramenta(*argumentos, **nomeados):
        try:
            return funcao(*argumentos, **nomeados)
        except (ferramentas.ProjetoDesconhecido, PacoteInvalido) as erro:
            raise ToolError(str(erro)) from erro

    return ferramenta


for _funcao in (
    ferramentas.listar_projetos,
    ferramentas.listar_historicos,
    ferramentas.resumo_do_projeto,
    ferramentas.buscar_evidencias,
    ferramentas.ler_referencia,
    ferramentas.conferir_resultados,
    ferramentas.buscar_regras,
    ferramentas.buscar_orientacoes,
    ferramentas.buscar_pareceres_historicos,
    ferramentas.parecer_historico,
):
    servidor.tool()(_com_erro_claro(_funcao))


if __name__ == "__main__":
    servidor.run()
