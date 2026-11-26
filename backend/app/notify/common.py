from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..core.appsettings import get_value


class ChannelError(Exception):
    """Falha de entrega com mensagem legível para o usuário."""


@dataclass
class Message:
    title: str
    body: str
    url: str = ""
    path: str = "/"
    image: str = ""
    priority: int = 2
    id: int = 0


def app_link(db: Session, path: str) -> str:
    return get_value(db, "public_url").rstrip("/") + (path or "/")
