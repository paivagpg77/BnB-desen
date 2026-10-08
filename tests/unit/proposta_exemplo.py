"""Proposta ficticia do modelo para o projeto de exemplo PRJ99."""

import copy
import json

from src.llm.cliente import RespostaLLM

REGRA_NOVIDADE = "regras-v1#002"

PROPOSTA = {
    "entendimento": {
        "problema": "Etiquetas eram lidas duas vezes pelo coletor.",
        "estado_anterior": "O coletor já descartava leitura repetida por janela fixa.",
        "trabalho_realizado": "A janela de descarte foi ajustada de um para dois segundos.",
        "fontes": ["evidencias/metodo.md#1", "evidencias/metodo.md#2"],
    },
    "criterios": [
        {"criterio": "novidade", "estado": "não demonstrada",
         "justificativa": "O coletor já oferecia o descarte por janela.",
         "regra": REGRA_NOVIDADE, "fontes": ["evidencias/metodo.md#1"]},
        {"criterio": "criatividade", "estado": "NÃO DEMONSTRADA",
         "justificativa": "Só o parâmetro da janela foi alterado.",
         "regra": "", "fontes": ["evidencias/metodo.md#2"]},
        {"criterio": "incerteza", "estado": "NÃO CARACTERIZADA",
         "justificativa": "Não há hipótese técnica desconhecida.",
         "regra": "", "fontes": ["evidencias/metodo.md#2", "PRJ99-EV77"]},
        {"criterio": "sistematicidade", "estado": "DOCUMENTADA COMO ACEITE",
         "justificativa": "Quarenta leituras em dois cenários.",
         "regra": "", "fontes": ["evidencias/medicoes.csv#PRJ99-S01"]},
        {"criterio": "transferencia", "estado": "DOCUMENTADA PARA A CONFIGURAÇÃO",
         "justificativa": "A receita está registrada.",
         "regra": "", "fontes": ["evidencias/metodo.md#3"]},
    ],
    "atividades": [
        {"id_atividade": "PRJ99-ATV01", "natureza": "apoio", "justificativa": "Caracterização."},
        {"id_atividade": "PRJ99-ATV02", "natureza": "rotina", "justificativa": "Registro de teste."},
        {"id_atividade": "PRJ99-ATV55", "natureza": "rotina", "justificativa": "Não existe."},
    ],
    "divergencias": [],
    "favoraveis": [{"texto": "Medições por cenário registradas.", "fontes": ["PRJ99-S01"]}],
    "contrarias": [
        {"texto": "A referência anterior já fazia o descarte.", "fontes": ["evidencias/metodo.md#1"]},
        {"texto": "Afirmação sem base.", "fontes": ["evidencias/inexistente.md"]},
    ],
    "lacunas": ["Dossiê e entrevista não foram entregues."],
    "classificacao_sugerida": "Não elegível",
    "justificativa": "O trabalho ajustou um parâmetro de recurso existente.",
    "recorte_sustentado": None,
    "limitacao": None,
    "evidencia_necessaria": None,
    "elo_ausente": None,
    "evidencias_a_solicitar": [],
}


def proposta(**alteracoes) -> dict:
    dados = copy.deepcopy(PROPOSTA)
    dados.update(alteracoes)
    return dados


class ClienteFalso:
    """Devolve as respostas na ordem dada e guarda o que recebeu."""

    def __init__(self, *respostas, modelo="falso/modelo"):
        self._respostas = list(respostas)
        self.modelo = modelo
        self.chamadas: list[tuple[str, str]] = []

    def completar(self, sistema, usuario, esquema=None):
        self.chamadas.append((sistema, usuario))
        resposta = self._respostas.pop(0) if len(self._respostas) > 1 else self._respostas[0]
        texto = resposta if isinstance(resposta, str) else json.dumps(resposta, ensure_ascii=False)
        return RespostaLLM(texto=texto, modelo=self.modelo)
