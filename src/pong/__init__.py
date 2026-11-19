from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toxinator.api import Game, GameManifest


def create_game(manifest: GameManifest) -> Game:
    from .game import Pong

    return Pong(manifest)
