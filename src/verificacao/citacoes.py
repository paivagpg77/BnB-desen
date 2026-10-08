"""
Verificador de citacoes: primeira barreira contra informacao inventada.

Cada afirmacao da IA chega com um trecho_id. O verificador confere:
1. O trecho existe na base.
2. O trecho foi recuperado nesta consulta (nao pode citar o que nao leu).
3. Se houver citacao literal, ela aparece no trecho (comparacao exata, sem acento).
4. Se nao houver literal, a afirmacao tem cobertura lexical suficiente no trecho.

LIMITACAO: a checagem lexical nao entende sentido. Ela barra citacoes
que nao tem nada a ver com a afirmacao, mas nao garante que a afirmacao esteja
correta. Uma segunda verificacao semantica (por modelo) pode ser adicionada
depois, sem remover esta.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional

from src.documentos.modelos import Trecho
from src.texto.tokens import remover_acentos, tokenizar

LIMIAR_COBERTURA = 0.6


class ResultadoVerificacao(str, Enum):
    SUSTENTADA = "sustentada"
    TRECHO_INEXISTENTE = "trecho_inexistente"
    TRECHO_NAO_RECUPERADO = "trecho_nao_recuperado"
    LITERAL_NAO_ENCONTRADA = "literal_nao_encontrada"
    NAO_SUSTENTADA = "nao_sustentada"


@dataclass(frozen=True)
class Citacao:
    afirmacao: str
    trecho_id: str
    literal: Optional[str] = None


@dataclass(frozen=True)
class ResultadoCitacao:
    citacao: Citacao
    resultado: ResultadoVerificacao
    cobertura: float

    @property
    def ok(self) -> bool:
        return self.resultado == ResultadoVerificacao.SUSTENTADA


def _normalizar_espacos(texto: str) -> str:
    return " ".join(remover_acentos(texto).lower().split())


def verificar_citacao(
    citacao: Citacao,
    trechos: dict[str, Trecho],
    recuperados: Optional[set[str]] = None,
) -> ResultadoCitacao:
    trecho = trechos.get(citacao.trecho_id)
    if trecho is None:
        return ResultadoCitacao(citacao, ResultadoVerificacao.TRECHO_INEXISTENTE, 0.0)

    if recuperados is not None and citacao.trecho_id not in recuperados:
        return ResultadoCitacao(citacao, ResultadoVerificacao.TRECHO_NAO_RECUPERADO, 0.0)

    if citacao.literal is not None:
        encontrado = _normalizar_espacos(citacao.literal) in _normalizar_espacos(trecho.texto)
        if encontrado:
            return ResultadoCitacao(citacao, ResultadoVerificacao.SUSTENTADA, 1.0)
        return ResultadoCitacao(citacao, ResultadoVerificacao.LITERAL_NAO_ENCONTRADA, 0.0)

    tokens_afirmacao = set(tokenizar(citacao.afirmacao))
    if not tokens_afirmacao:
        return ResultadoCitacao(citacao, ResultadoVerificacao.NAO_SUSTENTADA, 0.0)

    cobertura = len(tokens_afirmacao & set(tokenizar(trecho.texto))) / len(tokens_afirmacao)
    resultado = (
        ResultadoVerificacao.SUSTENTADA
        if cobertura >= LIMIAR_COBERTURA
        else ResultadoVerificacao.NAO_SUSTENTADA
    )
    return ResultadoCitacao(citacao, resultado, round(cobertura, 3))


def verificar_todas(
    citacoes: Iterable[Citacao],
    trechos: dict[str, Trecho],
    recuperados: Optional[set[str]] = None,
) -> list[ResultadoCitacao]:
    return [verificar_citacao(c, trechos, recuperados) for c in citacoes]


def proposta_tem_base(resultados: list[ResultadoCitacao]) -> tuple[bool, str]:
    """
    Uma proposta so pode ser apresentada ao analista se tiver pelo menos uma
    citacao e todas forem sustentadas. Uma citacao falha bloqueia a proposta
    inteira: a IA nao pode apresentar uma conclusao com parte da base inventada.
    """
    if not resultados:
        return False, "Proposta sem nenhuma citacao: deve ser 'Evidencia insuficiente'."
    falhas = [r for r in resultados if not r.ok]
    if falhas:
        tipos = sorted({r.resultado.value for r in falhas})
        return False, f"Citacoes nao verificadas: {', '.join(tipos)}."
    return True, "Todas as citacoes foram verificadas."
