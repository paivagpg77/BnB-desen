"""
Discordancias entre analista e IA, revisao cega e precedentes internos.

Quando o analista altera ou rejeita uma proposta, a discordancia e gravada e
fica aguardando um segundo analista, que decide sem ver a decisao do primeiro.
Discordancia confirmada pelos dois vira precedente interno: aparece como
contexto para o proximo analista, nunca altera proposta, estado ou
classificacao, e nao e fundamento legal.

O arquivo e somente de anexacao: cada mudanca de uma discordancia e uma linha
nova com o registro inteiro, e vale a ultima linha de cada identificador.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.decisoes.maquina_estados import Ponto, PontoDecisao, Status
from src.motor.regras import CLASSIFICACOES
from src.schemas.discordancia import (
    ClassificacaoPreliminar,
    PrecedenteInterno,
    RegistroDiscordancia,
    ResultadoAnalista,
    ResumoPrecedentes,
    RevisaoCega,
    StatusDiscordancia,
    TipoDiscordancia,
    e_padrao_candidato,
)

ROTULO_TIPO: dict[TipoDiscordancia, str] = {
    TipoDiscordancia.EVIDENCIA_MAL_LIDA: "A fonte citada não sustenta a afirmação",
    TipoDiscordancia.EVIDENCIA_AUSENTE: "A IA concluiu sem fonte suficiente",
    TipoDiscordancia.REGRA_MAL_APLICADA: "O critério foi aplicado de forma diferente da regra",
    TipoDiscordancia.DIVERGENCIA_DE_MERITO: "Leitura diferente do mesmo caso",
}

ROTULO_STATUS: dict[StatusDiscordancia, str] = {
    StatusDiscordancia.REGISTRADA: "aguarda revisão cega",
    StatusDiscordancia.EM_REVISAO_CEGA: "em revisão cega",
    StatusDiscordancia.CONVERGENCIA_CONTRA_IA: "confirmada pelo segundo analista",
    StatusDiscordancia.NAO_CONFIRMADA: "não confirmada: o segundo analista concordou com a IA",
    StatusDiscordancia.DIVERGENCIA_ENTRE_ANALISTAS: "divergência entre analistas: vai ao responsável da equipe",
    StatusDiscordancia.ENCAMINHADA_CURADOR: "encaminhada ao curador",
}

_CLASSE = dict(zip(CLASSIFICACOES, ClassificacaoPreliminar))


def pseudonimo(analista: str) -> str:
    """Identificador estavel do analista nos dados de discordancia, sem o nome dele."""
    resumo = hashlib.sha256(analista.strip().lower().encode("utf-8")).hexdigest()
    return f"ANL-{resumo[:6]}"


def abrir_discordancia(
    ponto: PontoDecisao,
    tipo: TipoDiscordancia,
    versao_norma: str,
    versao_motor: str,
) -> RegistroDiscordancia:
    """Registro para um ponto que o analista acabou de alterar ou rejeitar."""
    if ponto.status not in (Status.ALTERADA, Status.REJEITADA):
        raise ValueError("Só há discordância quando o analista altera ou rejeita a proposta.")
    agora = datetime.now(timezone.utc)
    e_classificacao = ponto.ponto == Ponto.D5
    return RegistroDiscordancia(
        discordancia_id=f"{ponto.decision_id}-{agora.strftime('%Y%m%dT%H%M%S%f')}",
        projeto_id=ponto.projeto_id,
        decision_id=ponto.decision_id,
        criterio=ponto.criterio or ponto.ponto.value,
        tipo=tipo,
        versao_norma=versao_norma,
        versao_motor=versao_motor,
        analista_origem_pseudonimo=pseudonimo(ponto.analista or ""),
        motivo=ponto.motivo or "",
        valor_ia=ponto.valor_proposto,
        valor_analista=ponto.valor_final,
        classificacao_ia=_CLASSE.get(ponto.valor_proposto or "") if e_classificacao else None,
        classificacao_analista=_CLASSE.get(ponto.valor_final or "") if e_classificacao else None,
        registrada_em=agora,
    )


def revisar(
    registro: RegistroDiscordancia,
    analista: str,
    concorda_com_ia: bool,
    motivo: str,
    valor: Optional[str] = None,
) -> RegistroDiscordancia:
    """
    Aplica a decisao do segundo analista. Nao muda a decisao do caso. O valor e
    o que ele daria ao ponto ao discordar da IA: diferente do valor do primeiro
    analista, a discordancia vira divergencia entre analistas.
    """
    return registro.resolver_revisao(
        RevisaoCega(
            analista_pseudonimo=pseudonimo(analista),
            decisao=ResultadoAnalista.ACEITA_IA if concorda_com_ia else ResultadoAnalista.DISCORDA_IA,
            valor=None if concorda_com_ia else valor,
            motivo=motivo,
            registrada_em=datetime.now(timezone.utc),
        )
    )


def pendentes_para(registros: list[RegistroDiscordancia], analista: str) -> list[RegistroDiscordancia]:
    """Discordancias que este analista pode revisar: as que nao sao dele."""
    quem = pseudonimo(analista)
    return [
        r
        for r in registros
        if r.status == StatusDiscordancia.REGISTRADA and r.analista_origem_pseudonimo != quem
    ]


def _grupos_confirmados(
    registros: list[RegistroDiscordancia],
) -> dict[tuple[str, TipoDiscordancia], list[RegistroDiscordancia]]:
    grupos: dict[tuple[str, TipoDiscordancia], list[RegistroDiscordancia]] = {}
    for r in registros:
        if r.status == StatusDiscordancia.CONVERGENCIA_CONTRA_IA:
            grupos.setdefault((r.criterio, r.tipo), []).append(r)
    return grupos


def precedentes_do_criterio(
    registros: list[RegistroDiscordancia], criterio: str, projeto_atual: str
) -> list[ResumoPrecedentes]:
    """Discordancias confirmadas no mesmo criterio, em outros projetos, por tipo."""
    resumos = []
    for (criterio_do_grupo, tipo), casos in _grupos_confirmados(registros).items():
        casos = [r for r in casos if r.projeto_id != projeto_atual]
        if criterio_do_grupo != criterio or not casos:
            continue
        resumos.append(
            ResumoPrecedentes(
                criterio=criterio,
                tipo=tipo,
                quantidade_casos=len(casos),
                casos=[
                    PrecedenteInterno(
                        precedente_id=f"P-{r.discordancia_id}",
                        discordancia_id=r.discordancia_id,
                        projeto_origem=r.projeto_id,
                        criterio=r.criterio,
                        tipo=r.tipo,
                        motivo_resumido=r.motivo[:300],
                        valor_resultante=r.valor_analista,
                        classificacao_resultante=r.classificacao_analista,
                        data=r.registrada_em,
                    )
                    for r in casos
                ],
            )
        )
    return resumos


def padroes_candidatos(
    registros: list[RegistroDiscordancia],
) -> list[tuple[str, TipoDiscordancia, list[str]]]:
    """(criterio, tipo, projetos) de cada padrao que deve ir ao curador normativo."""
    return [
        (criterio, tipo, sorted({r.projeto_id for r in casos}))
        for (criterio, tipo), casos in _grupos_confirmados(registros).items()
        if e_padrao_candidato(casos)
    ]


def metricas(registros: list[RegistroDiscordancia]) -> dict:
    def com(status: StatusDiscordancia) -> int:
        return sum(r.status == status for r in registros)

    confirmadas = com(StatusDiscordancia.CONVERGENCIA_CONTRA_IA)
    revisadas = sum(r.revisao is not None for r in registros)
    return {
        "total": len(registros),
        "aguardando_revisao": com(StatusDiscordancia.REGISTRADA),
        "revisadas": revisadas,
        "confirmadas": confirmadas,
        "nao_confirmadas": com(StatusDiscordancia.NAO_CONFIRMADA),
        "divergentes": com(StatusDiscordancia.DIVERGENCIA_ENTRE_ANALISTAS),
        # Confirmadas contra a IA sobre o total de discordancias. None sem discordancia.
        "taxa_convergencia": confirmadas / len(registros) if registros else None,
        # Revisoes cegas em que o segundo analista decidiu como o primeiro.
        "concordancia_entre_analistas": confirmadas / revisadas if revisadas else None,
    }


class RepositorioDiscordancias:
    def __init__(self, caminho: Path) -> None:
        self.caminho = Path(caminho)

    def salvar(self, registro: RegistroDiscordancia) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self.caminho.open("a", encoding="utf-8") as arquivo:
            arquivo.write(registro.model_dump_json() + "\n")

    def todas(self) -> list[RegistroDiscordancia]:
        """A versao mais recente de cada discordancia, na ordem em que foram abertas."""
        if not self.caminho.is_file():
            return []
        registros: dict[str, RegistroDiscordancia] = {}
        for linha in self.caminho.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                registro = RegistroDiscordancia.model_validate(json.loads(linha))
                registros[registro.discordancia_id] = registro
        return list(registros.values())
