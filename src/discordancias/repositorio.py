"""
Registro das discordancias em log somente de anexacao.

Cada acao vira uma linha de um arquivo JSONL: a discordancia registrada e a
revisao cega. Nada e editado nem apagado; o estado atual de cada discordancia
e reconstruido relendo os eventos na ordem.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.config import carregar_env
from src.schemas.discordancia import RegistroDiscordancia, RevisaoCega

VARIAVEL_ARQUIVO = "LEI_DO_BEM_DISCORDANCIAS"
ARQUIVO_PADRAO = (
    Path(__file__).resolve().parents[2] / "saida" / "discordancias" / "eventos.jsonl"
)

EVENTO_REGISTRO = "discordancia_registrada"
EVENTO_REVISAO = "revisao_registrada"


class DiscordanciaInvalida(ValueError):
    pass


def arquivo_padrao() -> Path:
    carregar_env()
    return Path(os.environ.get(VARIAVEL_ARQUIVO) or ARQUIVO_PADRAO)


class RepositorioDiscordancias:
    def __init__(self, caminho: Optional[str | Path] = None):
        self.caminho = Path(caminho) if caminho else arquivo_padrao()

    def eventos(self) -> list[dict]:
        if not self.caminho.is_file():
            return []
        linhas = self.caminho.read_text(encoding="utf-8").splitlines()
        return [json.loads(linha) for linha in linhas if linha.strip()]

    def listar(self) -> list[RegistroDiscordancia]:
        """Estado atual de cada discordancia, na ordem em que foram registradas."""
        registros: dict[str, RegistroDiscordancia] = {}
        for evento in self.eventos():
            if evento["evento"] == EVENTO_REGISTRO:
                registro = RegistroDiscordancia.model_validate(evento["registro"])
                registros[registro.discordancia_id] = registro
            elif evento["evento"] == EVENTO_REVISAO:
                registros[evento["discordancia_id"]].resolver_revisao(
                    RevisaoCega.model_validate(evento["revisao"])
                )
        return list(registros.values())

    def proximo_id(self) -> str:
        return f"DSC-{len(self.listar()) + 1:04d}"

    def registrar(self, registro: RegistroDiscordancia) -> RegistroDiscordancia:
        if any(r.discordancia_id == registro.discordancia_id for r in self.listar()):
            raise DiscordanciaInvalida(f"{registro.discordancia_id} já está registrada.")
        self._anexar(
            {
                "evento": EVENTO_REGISTRO,
                "discordancia_id": registro.discordancia_id,
                "registro": registro.model_dump(mode="json"),
            }
        )
        return registro

    def registrar_revisao(self, discordancia_id: str, revisao: RevisaoCega) -> RegistroDiscordancia:
        """Aplica a revisao cega e devolve a discordancia com o novo status."""
        registro = next(
            (r for r in self.listar() if r.discordancia_id == discordancia_id), None
        )
        if registro is None:
            raise DiscordanciaInvalida(f"{discordancia_id} não existe.")
        if registro.revisao is not None:
            raise DiscordanciaInvalida(f"{discordancia_id} já passou pela revisão cega.")
        registro.resolver_revisao(revisao)
        self._anexar(
            {
                "evento": EVENTO_REVISAO,
                "discordancia_id": discordancia_id,
                "revisao": revisao.model_dump(mode="json"),
                "status": registro.status.value,
            }
        )
        return registro

    def _anexar(self, evento: dict) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        evento = {**evento, "ts": datetime.now(timezone.utc).isoformat()}
        with self.caminho.open("a", encoding="utf-8") as arquivo:
            arquivo.write(json.dumps(evento, ensure_ascii=False) + "\n")
