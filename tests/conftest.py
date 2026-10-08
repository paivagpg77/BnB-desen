from src.config import carregar_env

# Carrega o .env antes da coleta: os testes de integracao decidem se rodam
# olhando LEI_DO_BEM_PACOTE no momento da importacao.
carregar_env()
