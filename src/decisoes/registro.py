"""
Log das decisoes em disco, somente de anexacao.

Um arquivo JSONL por projeto. Cada linha e um evento da maquina de estados
(proposta, decisao, reabertura), na ordem em que aconteceu. Nada e reescrito:
uma nova analise do mesmo projeto comeca com a linha "analise_iniciada" e o
historico anterior continua no arquivo.

Os pontos de uma analise sao reconstruidos so a partir dos eventos, sem nova
chamada ao modelo.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.decisoes.maquina_estados import Ponto, PontoDecisao, Status

ANALISE_INICIADA = "analise_iniciada"
PROPOSTA_PUBLICADA = "proposta_publicada"
# Campos do ponto que um evento pode trazer.
_CAMPOS = ("valor_proposto", "valor_final", "motivo", "analista", "justificativa")


def reconstruir_pontos(eventos: list[dict], projeto_id: str) -> list[PontoDecisao]:
    """Refaz os pontos de uma analise aplicando os eventos na ordem do log."""
    pontos: dict[str, PontoDecisao] = {}
    for evento in eventos:
        if evento["evento"] == ANALISE_INICIADA:
            continue
        ponto = pontos.get(evento["decision_id"])
        if ponto is None:
            ponto = PontoDecisao(
                projeto_id=evento["projeto_id"],
                ponto=Ponto(evento["ponto"]),
                criterio=evento.get("criterio"),
            )
            pontos[ponto.decision_id] = ponto
        if evento["evento"] == PROPOSTA_PUBLICADA:
            # Proposta nova apaga a decisao anterior, como em PontoDecisao.propor.
            ponto.valor_final = ponto.motivo = ponto.analista = None
        for campo in _CAMPOS:
            if campo in evento:
                setattr(ponto, campo, evento[campo])
        ponto.status = Status(evento["status"])
        ponto.eventos.append(evento)

    lista = list(pontos.values())
    # D5 so ganha evento quando e proposto, depois dos criterios decididos.
    if lista and not any(p.ponto == Ponto.D5 for p in lista):
        lista.append(PontoDecisao(projeto_id=projeto_id, ponto=Ponto.D5))
    return lista


class RegistroDecisoes:
    def __init__(self, pasta: Path, projeto_id: str) -> None:
        self.projeto_id = projeto_id
        self.caminho = Path(pasta) / f"{projeto_id}.jsonl"

    def anexar(self, evento: dict) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self.caminho.open("a", encoding="utf-8") as arquivo:
            arquivo.write(json.dumps(evento, ensure_ascii=False) + "\n")

    def historico(self) -> list[dict]:
        """Todos os eventos do projeto, de todas as analises."""
        if not self.caminho.is_file():
            return []
        linhas = self.caminho.read_text(encoding="utf-8").splitlines()
        return [json.loads(linha) for linha in linhas if linha.strip()]

    def eventos_da_analise_atual(self) -> list[dict]:
        eventos = self.historico()
        inicios = [i for i, e in enumerate(eventos) if e["evento"] == ANALISE_INICIADA]
        return eventos[inicios[-1] + 1 :] if inicios else eventos

    def acompanhar(self, pontos: list[PontoDecisao]) -> None:
        """A partir daqui, todo evento destes pontos vai para o arquivo."""
        for ponto in pontos:
            ponto.ao_registrar = self.anexar

    def iniciar_analise(self, pontos: list[PontoDecisao]) -> None:
        """Marca uma nova analise e grava as propostas ja publicadas."""
        self.anexar(
            {
                "evento": ANALISE_INICIADA,
                "projeto_id": self.projeto_id,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        for ponto in pontos:
            for evento in ponto.eventos:
                self.anexar(evento)
        self.acompanhar(pontos)

    def retomar(self) -> Optional[list[PontoDecisao]]:
        """Pontos da ultima analise, com as decisoes ja tomadas. None se nao ha log."""
        eventos = self.eventos_da_analise_atual()
        if not eventos:
            return None
        pontos = reconstruir_pontos(eventos, self.projeto_id)
        self.acompanhar(pontos)
        return pontos

    def proposta_vigente(self, decision_id: str, ate: datetime) -> Optional[PontoDecisao]:
        """
        O ponto como a IA o propos ate o instante dado, sem nenhuma decisao de
        analista. E o que o segundo analista ve na revisao cega.
        """
        propostas = [
            e
            for e in self.historico()
            if e["evento"] == PROPOSTA_PUBLICADA
            and e["decision_id"] == decision_id
            and datetime.fromisoformat(e["ts"]) <= ate
        ]
        if not propostas:
            return None
        ultima = propostas[-1]
        return PontoDecisao(
            projeto_id=ultima["projeto_id"],
            ponto=Ponto(ultima["ponto"]),
            criterio=ultima.get("criterio"),
            status=Status.AGUARDANDO_ANALISTA,
            valor_proposto=ultima["valor_proposto"],
            justificativa=ultima["justificativa"],
        )
