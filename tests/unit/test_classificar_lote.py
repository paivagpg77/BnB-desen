"""O resumo do lote acumula rodadas: rodada parcial não apaga os outros projetos."""

import importlib.util
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location("classificar_lote", RAIZ / "scripts" / "classificar_lote.py")
lote = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lote)


def _linha(projeto_id, segundos, classe="Elegível"):
    return {"projeto_id": projeto_id, "classificacao_pela_regra": classe, "segundos": segundos}


def test_rodada_parcial_mantem_os_projetos_que_nao_tocou():
    anteriores = {"PRJ21": _linha("PRJ21", 30.0), "PRJ22": _linha("PRJ22", 41.5)}
    junto = lote.juntar(anteriores, [_linha("PRJ22", 12.3, "Com ressalvas"), _linha("PRJ23", 20.0)])
    assert [l["projeto_id"] for l in junto] == ["PRJ21", "PRJ22", "PRJ23"]
    assert junto[0] == anteriores["PRJ21"]
    assert junto[1]["segundos"] == 12.3 and junto[1]["classificacao_pela_regra"] == "Com ressalvas"


def test_projeto_relido_do_disco_nao_perde_o_tempo_medido():
    anteriores = {"PRJ21": _linha("PRJ21", 30.0)}
    junto = lote.juntar(anteriores, [_linha("PRJ21", None), _linha("PRJ22", None)])
    assert [l["segundos"] for l in junto] == [30.0, None]


def test_lote_anterior_e_lido_por_projeto(tmp_path):
    arquivo = tmp_path / "classificacao_lote.json"
    assert lote.carregar_lote(arquivo) == {}
    arquivo.write_text(json.dumps([_linha("PRJ21", 30.0)]), encoding="utf-8")
    assert lote.carregar_lote(arquivo) == {"PRJ21": _linha("PRJ21", 30.0)}
