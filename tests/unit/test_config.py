import os

from src.config import carregar_env, ler_env


def test_le_chaves_ignorando_comentarios_aspas_e_valores_vazios(tmp_path):
    arquivo = tmp_path / ".env"
    arquivo.write_text(
        "# comentario\n"
        "\n"
        "CHAVE_SIMPLES=abc\n"
        'COM_ASPAS="caminho com espaco/pasta"\n'
        "export COM_EXPORT=1\n"
        "EM_BRANCO=\n"
        "linha sem igual\n",
        encoding="utf-8",
    )
    assert ler_env(arquivo) == {
        "CHAVE_SIMPLES": "abc",
        "COM_ASPAS": "caminho com espaco/pasta",
        "COM_EXPORT": "1",
    }


def test_arquivo_inexistente_nao_e_erro(tmp_path):
    assert ler_env(tmp_path / "nao_existe.env") == {}
    assert carregar_env(tmp_path / "nao_existe.env", forcar=True) == []


def test_ambiente_tem_prioridade_sobre_o_arquivo(tmp_path, monkeypatch):
    arquivo = tmp_path / ".env"
    arquivo.write_text("LDB_TESTE_A=do_arquivo\nLDB_TESTE_B=do_arquivo\n", encoding="utf-8")
    monkeypatch.setenv("LDB_TESTE_A", "do_ambiente")
    monkeypatch.delenv("LDB_TESTE_B", raising=False)

    assert carregar_env(arquivo, forcar=True) == ["LDB_TESTE_B"]
    assert os.environ["LDB_TESTE_A"] == "do_ambiente"
    assert os.environ["LDB_TESTE_B"] == "do_arquivo"
    monkeypatch.delenv("LDB_TESTE_B")


def test_carrega_uma_vez_por_processo(tmp_path, monkeypatch):
    arquivo = tmp_path / ".env"
    arquivo.write_text("LDB_TESTE_C=1\n", encoding="utf-8")
    monkeypatch.delenv("LDB_TESTE_C", raising=False)
    carregar_env(tmp_path / "outro.env", forcar=True)
    assert carregar_env(arquivo) == []
    assert "LDB_TESTE_C" not in os.environ
