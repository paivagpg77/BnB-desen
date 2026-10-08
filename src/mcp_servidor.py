"""
Servidor MCP da ferramenta: acesso padronizado, somente de leitura, as
evidencias dos projetos, as verificacoes deterministicas e a base de regras.

Nenhuma ferramenta daqui decide ou classifica: elas entregam evidencia com
identificador, para que quem consulta (pessoa ou agente) cite a fonte.

Uso (transporte stdio):
    .venv/bin/python -m src.mcp_servidor
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from src import ferramentas

INSTRUCOES = (
    "Evidências de projetos para análise preliminar de elegibilidade à Lei do Bem. "
    "Toda afirmação sobre um projeto deve citar o trecho_id devolvido pelas "
    "ferramentas. Entrevista é depoimento de memória; medições são registro "
    "primário. As ferramentas não classificam projetos: a decisão é do analista."
)

servidor = MCPServer("lei-do-bem-analise", instructions=INSTRUCOES)

for _funcao in (
    ferramentas.listar_projetos,
    ferramentas.resumo_do_projeto,
    ferramentas.buscar_evidencias,
    ferramentas.ler_referencia,
    ferramentas.conferir_resultados,
    ferramentas.buscar_regras,
    ferramentas.parecer_historico,
):
    servidor.tool()(_funcao)


if __name__ == "__main__":
    servidor.run()
