from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.schemas.discordancia import (
    ClassificacaoPreliminar,
    LIMIAR_PADRAO_CANDIDATO,
    RegistroDiscordancia,
    ResultadoAnalista,
    RevisaoCega,
    StatusDiscordancia,
    TipoDiscordancia,
    e_padrao_candidato,
)

AGORA = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)
MOTIVO = "A evidencia citada nao sustenta a afirmacao de novidade."


def registro(projeto="PRJ21", id_="D-001", tipo=TipoDiscordancia.EVIDENCIA_MAL_LIDA):
    return RegistroDiscordancia(
        discordancia_id=id_,
        projeto_id=projeto,
        decision_id=f"{projeto}-D2-novidade",
        criterio="novidade",
        tipo=tipo,
        versao_norma="Lei 11.196/2005 + Decreto 5.798/2006",
        versao_motor="prompt-novidade-v1 / modelo-x",
        analista_origem_pseudonimo="ANL-07",
        motivo=MOTIVO,
        classificacao_ia=ClassificacaoPreliminar.ELEGIVEL,
        classificacao_analista=ClassificacaoPreliminar.COM_RESSALVAS,
        registrada_em=AGORA,
    )


def revisao(pseudonimo="ANL-12", decisao=ResultadoAnalista.DISCORDA_IA):
    return RevisaoCega(
        analista_pseudonimo=pseudonimo,
        decisao=decisao,
        motivo=MOTIVO,
        registrada_em=AGORA,
    )


# ----- revisao cega e convergencia -----

def test_convergencia_contra_ia_quando_segundo_analista_discorda_tambem():
    r = registro().resolver_revisao(revisao(decisao=ResultadoAnalista.DISCORDA_IA))
    assert r.status == StatusDiscordancia.CONVERGENCIA_CONTRA_IA


def test_nao_confirmada_quando_segundo_analista_concorda_com_ia():
    r = registro().resolver_revisao(revisao(decisao=ResultadoAnalista.ACEITA_IA))
    assert r.status == StatusDiscordancia.NAO_CONFIRMADA


def test_revisor_nao_pode_ser_o_mesmo_analista():
    with pytest.raises(ValueError):
        registro().resolver_revisao(revisao(pseudonimo="ANL-07"))


def test_revisao_no_construtor_tambem_exige_analista_diferente():
    with pytest.raises(ValidationError):
        RegistroDiscordancia(
            **registro().model_dump(exclude={"revisao", "status"}),
            revisao=revisao(pseudonimo="ANL-07"),
        )


def test_resolver_revisao_nao_altera_classificacao_do_caso():
    original = registro()
    r = original.resolver_revisao(revisao())
    assert r.classificacao_ia == ClassificacaoPreliminar.ELEGIVEL
    assert r.classificacao_analista == ClassificacaoPreliminar.COM_RESSALVAS


# ----- validacoes de campos -----

def test_motivo_curto_e_recusado():
    with pytest.raises(ValidationError):
        RegistroDiscordancia(
            **registro().model_dump(exclude={"motivo"}),
            motivo="curto",
        )


def test_precedente_nao_normativo_por_padrao():
    from src.schemas.discordancia import PrecedenteInterno

    p = PrecedenteInterno(
        precedente_id="P-1",
        discordancia_id="D-001",
        projeto_origem="PRJ21",
        criterio="novidade",
        tipo=TipoDiscordancia.EVIDENCIA_MAL_LIDA,
        motivo_resumido="Trecho nao sustenta a afirmacao.",
        classificacao_resultante=ClassificacaoPreliminar.COM_RESSALVAS,
        data=AGORA,
    )
    assert p.natureza == "interno_nao_normativo"


# ----- padrao candidato -----

def convergente(projeto: str, i: int) -> RegistroDiscordancia:
    return registro(projeto=projeto, id_=f"D-{i}").resolver_revisao(
        revisao(decisao=ResultadoAnalista.DISCORDA_IA)
    )


def test_limiar_padrao_candidato_e_tres_projetos_distintos():
    assert LIMIAR_PADRAO_CANDIDATO == 3
    casos = [convergente("PRJ21", 1), convergente("PRJ22", 2), convergente("PRJ23", 3)]
    assert e_padrao_candidato(casos)


def test_dois_casos_nao_formam_padrao():
    casos = [convergente("PRJ21", 1), convergente("PRJ22", 2)]
    assert not e_padrao_candidato(casos)


def test_casos_do_mesmo_projeto_nao_contam_como_independentes():
    casos = [convergente("PRJ21", 1), convergente("PRJ21", 2), convergente("PRJ21", 3)]
    assert not e_padrao_candidato(casos)


def test_nao_confirmadas_nao_contam_para_padrao():
    nao_confirmadas = [
        registro(projeto=p, id_=f"N-{i}").resolver_revisao(
            revisao(decisao=ResultadoAnalista.ACEITA_IA)
        )
        for i, p in enumerate(["PRJ21", "PRJ22", "PRJ23"])
    ]
    assert not e_padrao_candidato(nao_confirmadas)
