"""A calibração acumula rodadas e não refaz o que já foi avaliado com o prompt atual."""

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

from src.motor import orquestrador
from tests.unit.proposta_exemplo import ClienteFalso, proposta

RAIZ = Path(__file__).resolve().parents[2]
PACOTE = RAIZ / "dados" / "fixtures" / "pacote_exemplo"

_spec = importlib.util.spec_from_file_location("calibrar", RAIZ / "scripts" / "calibrar.py")
calibrar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(calibrar)


def test_rodada_pula_o_que_ja_foi_avaliado_com_o_prompt_atual():
    anteriores = {
        "PRJ01": {"projeto_id": "PRJ01", "prompt": "p@1", "acertou": True},
        "PRJ02": {"projeto_id": "PRJ02", "prompt": "p@0", "acertou": True},   # prompt antigo
        "PRJ03": {"projeto_id": "PRJ03", "erro": "falhou"},
    }
    ids = ["PRJ01", "PRJ02", "PRJ03", "PRJ04"]
    assert calibrar.a_avaliar(ids, anteriores, "p@1") == ["PRJ02", "PRJ03", "PRJ04"]
    assert calibrar.a_avaliar(ids, anteriores, "p@1", limite=2) == ["PRJ02", "PRJ03"]
    assert calibrar.a_avaliar(ids, anteriores, "p@1", refazer=True) == ids


@pytest.fixture
def pacote_com_historico(tmp_path, monkeypatch):
    """O projeto de exemplo passa a ter parecer de referencia, como um historico."""
    pacote = tmp_path / "pacote"
    shutil.copytree(PACOTE, pacote)
    historicos = pacote / "historicos_classificados.csv"
    historicos.write_text(
        historicos.read_text(encoding="utf-8-sig").replace("PRJ96", "PRJ99"), encoding="utf-8-sig"
    )
    monkeypatch.setenv("LEI_DO_BEM_PACOTE", str(pacote))
    return pacote


def _rodar(monkeypatch, capsys, saida, cliente, *argumentos):
    monkeypatch.setattr(calibrar, "papeis_padrao", lambda: orquestrador.Papeis(analista=cliente))
    monkeypatch.setattr(sys, "argv", ["calibrar.py", "--saida", str(saida), *argumentos])
    assert calibrar.main() == 0
    return capsys.readouterr().out


def test_rodadas_se_acumulam_sem_repetir_chamada_ao_modelo(
    pacote_com_historico, tmp_path, monkeypatch, capsys
):
    saida = tmp_path / "saida" / "calibracao.json"
    cliente = ClienteFalso(proposta())

    texto = _rodar(monkeypatch, capsys, saida, cliente, "--projetos", "PRJ99")
    assert "PRJ99: OK" in texto
    assert "critérios iguais=5/5" in texto
    assert "Classificação pela regra: 1/1" in texto
    assert "1 de 3 históricos avaliados. Faltam: PRJ97, PRJ98." in texto
    (linha,) = json.loads(saida.read_text(encoding="utf-8"))
    assert linha["acertou"] and linha["referencia"] == "Não elegível"

    chamadas = len(cliente.chamadas)
    texto = _rodar(monkeypatch, capsys, saida, cliente, "--projetos", "PRJ99")
    assert len(cliente.chamadas) == chamadas            # ja avaliado: nenhuma chamada
    assert "Classificação pela regra: 1/1" in texto

    _rodar(monkeypatch, capsys, saida, cliente, "--projetos", "PRJ99", "--refazer")
    assert len(cliente.chamadas) > chamadas
    assert len(json.loads(saida.read_text(encoding="utf-8"))) == 1


def test_projeto_sem_parecer_de_referencia_e_recusado(pacote_com_historico, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["calibrar.py", "--saida", str(tmp_path / "c.json"), "--projetos", "PRJ50"])
    assert calibrar.main() == 1
    assert "Sem parecer de referência: PRJ50" in capsys.readouterr().out
