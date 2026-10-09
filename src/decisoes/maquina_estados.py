"""
Maquina de estados dos pontos de decisao (D1 a D5).

Regras:
- A IA propoe. O analista aceita, altera ou rejeita.
- Nenhum ponto avanca sem decisao do analista.
- Alterar ou rejeitar exige motivo com pelo menos 20 caracteres.
- Toda decisao registra o analista que a tomou.
- Mudanca em um ponto reabre os pontos que dependem dele.
- Todo evento fica registrado em log somente de anexacao.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional


MOTIVO_MIN_CARACTERES = 20


class Ponto(str, Enum):
    D1 = "D1"  # entendimento do projeto
    D2 = "D2"  # avaliacao de um criterio (repete por criterio)
    D3 = "D3"  # segregacao de atividades
    D4 = "D4"  # evidencias contrarias e lacunas
    D5 = "D5"  # classificacao final


ORDEM_PONTOS: list[Ponto] = [Ponto.D1, Ponto.D2, Ponto.D3, Ponto.D4, Ponto.D5]

# Se o ponto da chave mudar, os pontos da lista precisam ser revistos.
DEPENDENTES: dict[Ponto, list[Ponto]] = {
    Ponto.D1: [],
    Ponto.D2: [Ponto.D4],
    Ponto.D3: [Ponto.D2],
    Ponto.D4: [Ponto.D5],
    Ponto.D5: [],
}


class Status(str, Enum):
    PROPOSTA = "proposta"
    AGUARDANDO_ANALISTA = "aguardando_analista"
    ACEITA = "aceita"
    ALTERADA = "alterada"
    REJEITADA = "rejeitada"
    REABERTA = "reaberta"


STATUS_DECIDIDOS = {Status.ACEITA, Status.ALTERADA}


class Acao(str, Enum):
    PROPOR = "propor"        # a IA publica (ou refaz) uma proposta
    ACEITAR = "aceitar"
    ALTERAR = "alterar"
    REJEITAR = "rejeitar"
    REABRIR = "reabrir"      # dependencia mudou


TRANSICOES: dict[tuple[Status, Acao], Status] = {
    (Status.PROPOSTA, Acao.PROPOR): Status.AGUARDANDO_ANALISTA,
    (Status.REJEITADA, Acao.PROPOR): Status.AGUARDANDO_ANALISTA,
    (Status.REABERTA, Acao.PROPOR): Status.AGUARDANDO_ANALISTA,
    (Status.AGUARDANDO_ANALISTA, Acao.ACEITAR): Status.ACEITA,
    (Status.AGUARDANDO_ANALISTA, Acao.ALTERAR): Status.ALTERADA,
    (Status.AGUARDANDO_ANALISTA, Acao.REJEITAR): Status.REJEITADA,
    (Status.ACEITA, Acao.REABRIR): Status.REABERTA,
    (Status.ALTERADA, Acao.REABRIR): Status.REABERTA,
}


class TransicaoInvalida(Exception):
    """Acao nao permitida no estado atual."""


class DecisaoInvalida(ValueError):
    """Dados insuficientes ou inconsistentes para a acao."""


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PontoDecisao:
    projeto_id: str
    ponto: Ponto
    criterio: Optional[str] = None
    status: Status = Status.PROPOSTA
    valor_proposto: Optional[str] = None
    valor_final: Optional[str] = None
    motivo: Optional[str] = None
    # Justificativa da proposta da IA. Formato:
    # {"porque": [{"afirmacao": str, "trecho_id": str}],
    #  "como": [str], "evidencias_contrarias": [str], "lacunas": [str]}
    justificativa: dict = field(default_factory=dict)
    # Quem tomou a ultima decisao do analista (aceita, alterada ou rejeitada).
    analista: Optional[str] = None
    eventos: list[dict] = field(default_factory=list)
    # Chamado a cada evento, para quem grava o log em disco.
    ao_registrar: Optional[Callable[[dict], None]] = field(default=None, repr=False, compare=False)

    @property
    def decision_id(self) -> str:
        sufixo = f"-{self.criterio}" if self.criterio else ""
        return f"{self.projeto_id}-{self.ponto.value}{sufixo}"

    @property
    def decidido(self) -> bool:
        return self.status in STATUS_DECIDIDOS

    # ----- acoes -----

    def propor(self, valor: str, justificativa: Optional[dict] = None) -> None:
        """A IA publica uma proposta (ou uma nova, depois de rejeicao ou reabertura)."""
        if not valor or not valor.strip():
            raise DecisaoInvalida("A proposta precisa de um valor.")
        novo = self._transicionar(Acao.PROPOR)
        self.valor_proposto = valor
        self.valor_final = None
        self.motivo = None
        self.analista = None
        self.justificativa = dict(justificativa or {})
        self.status = novo
        self._registrar(
            "proposta_publicada",
            valor_proposto=valor,
            justificativa=self.justificativa,
        )

    def aceitar(self, analista: str) -> None:
        self._exigir_analista(analista)
        novo = self._transicionar(Acao.ACEITAR)
        self.valor_final = self.valor_proposto
        self.analista = analista
        self.status = novo
        self._registrar(
            "decisao_analista",
            acao="aceita",
            analista=analista,
            valor_final=self.valor_final,
        )

    def alterar(self, valor_final: str, motivo: str, analista: str) -> None:
        self._exigir_analista(analista)
        self._exigir_motivo(motivo)
        if not valor_final or not valor_final.strip():
            raise DecisaoInvalida("Alterar exige o valor final.")
        if valor_final == self.valor_proposto:
            raise DecisaoInvalida("Alterar exige valor diferente da proposta. Use aceitar.")
        novo = self._transicionar(Acao.ALTERAR)
        self.valor_final = valor_final
        self.motivo = motivo
        self.analista = analista
        self.status = novo
        self._registrar(
            "decisao_analista",
            acao="alterada",
            analista=analista,
            valor_proposto=self.valor_proposto,
            valor_final=valor_final,
            motivo=motivo,
        )

    def rejeitar(self, motivo: str, analista: str) -> None:
        self._exigir_analista(analista)
        self._exigir_motivo(motivo)
        novo = self._transicionar(Acao.REJEITAR)
        self.motivo = motivo
        self.analista = analista
        self.status = novo
        self._registrar(
            "decisao_analista",
            acao="rejeitada",
            analista=analista,
            motivo=motivo,
        )

    def reabrir(self, causa: str) -> None:
        novo = self._transicionar(Acao.REABRIR)
        self.status = novo
        self._registrar("ponto_reaberto", causa=causa)

    # ----- internos -----

    def _transicionar(self, acao: Acao) -> Status:
        chave = (self.status, acao)
        if chave not in TRANSICOES:
            raise TransicaoInvalida(
                f"'{acao.value}' nao permitido em '{self.status.value}' "
                f"({self.decision_id})."
            )
        return TRANSICOES[chave]

    @staticmethod
    def _exigir_motivo(motivo: Optional[str]) -> None:
        if not motivo or len(motivo.strip()) < MOTIVO_MIN_CARACTERES:
            raise DecisaoInvalida(
                f"O motivo precisa ter pelo menos {MOTIVO_MIN_CARACTERES} caracteres."
            )

    @staticmethod
    def _exigir_analista(analista: Optional[str]) -> None:
        if not analista or not analista.strip():
            raise DecisaoInvalida("Toda decisao precisa identificar o analista.")

    def _registrar(self, evento: str, **dados) -> None:
        # Log somente de anexacao: nada deste historico e editado ou apagado.
        registro = {
            "evento": evento,
            "decision_id": self.decision_id,
            "projeto_id": self.projeto_id,
            "ponto": self.ponto.value,
            "criterio": self.criterio,
            "status": self.status.value,
            "ts": _agora(),
            **dados,
        }
        self.eventos.append(registro)
        if self.ao_registrar:
            self.ao_registrar(registro)


# ----- regras sobre o conjunto de pontos de um projeto -----

def _indice(ponto: Ponto) -> int:
    return ORDEM_PONTOS.index(ponto)


def pode_apresentar(pontos: list[PontoDecisao], ponto: Ponto) -> bool:
    """Um ponto so e apresentado quando todos os anteriores estiverem decididos."""
    return all(p.decidido for p in pontos if _indice(p.ponto) < _indice(ponto))


def proximo_ponto_pendente(pontos: list[PontoDecisao]) -> Optional[PontoDecisao]:
    """Primeiro ponto, na ordem D1 a D5, que ainda nao foi decidido."""
    for p in sorted(pontos, key=lambda x: _indice(x.ponto)):
        if not p.decidido:
            return p
    return None


def decisao_final_pronta(pontos: list[PontoDecisao]) -> bool:
    """O dossie so pode ser gerado quando todos os pontos estiverem decididos."""
    return bool(pontos) and all(p.decidido for p in pontos)


def reabrir_dependentes(
    pontos: list[PontoDecisao], origem: PontoDecisao
) -> list[PontoDecisao]:
    """
    Reabre, em cascata, os pontos decididos que dependem da origem.
    Pontos ainda nao decididos nao sao reabertos, mas a cascata continua por eles.
    D2 vale para todos os criterios do projeto.
    """
    reabertos: list[PontoDecisao] = []
    a_visitar: list[Ponto] = [origem.ponto]
    visitados: set[Ponto] = set()

    while a_visitar:
        atual = a_visitar.pop()
        if atual in visitados:
            continue
        visitados.add(atual)

        for dependente in DEPENDENTES[atual]:
            for p in pontos:
                if p.ponto != dependente:
                    continue
                if p.decidido:
                    p.reabrir(causa=origem.decision_id)
                    reabertos.append(p)
            a_visitar.append(dependente)

    return reabertos
