"""Onde o app guarda configuração, logs e dados.

Linux segue o XDG; Windows segue `%APPDATA%` / `%LOCALAPPDATA%` e a pasta
Documents do perfil (o nome real da pasta é ``Documents`` mesmo no Windows em
português — ``Documentos`` é só o rótulo que o Explorer mostra).

IA4294_HOME redireciona tudo para um único diretório (usado pelos testes).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

WINDOWS = sys.platform.startswith("win")


def _home() -> Path | None:
    v = os.environ.get("IA4294_HOME")
    return Path(v) if v else None


def _env_dir(name: str, fallback: Path) -> Path:
    v = os.environ.get(name)
    return Path(v) if v else fallback


def config_dir() -> Path:
    if WINDOWS:
        base = _env_dir("APPDATA", Path.home() / "AppData" / "Roaming") / "ia4294"
    else:
        base = _env_dir("XDG_CONFIG_HOME", Path.home() / ".config") / "ia4294"
    p = (_home() / "config") if _home() else base
    p.mkdir(parents=True, exist_ok=True)
    return p


def profiles_dir() -> Path:
    p = config_dir() / "perfis"
    p.mkdir(parents=True, exist_ok=True)
    return p


def capabilities_file() -> Path:
    return config_dir() / "capacidades.json"


def log_dir() -> Path:
    if WINDOWS:
        base = _env_dir("LOCALAPPDATA", Path.home() / "AppData" / "Local") / "ia4294"
    else:
        base = _env_dir("XDG_STATE_HOME", Path.home() / ".local" / "state") / "ia4294"
    p = (_home() / "logs") if _home() else base / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def documents_dir() -> Path:
    """A pasta de documentos do usuário, com o nome que o sistema usa."""
    if WINDOWS:
        return _env_dir("USERPROFILE", Path.home()) / "Documents"
    for name in ("Documentos", "Documents"):
        if (Path.home() / name).is_dir():
            return Path.home() / name
    return Path.home() / "Documentos"


def data_dir() -> Path:
    p = (_home() / "dados") if _home() else documents_dir() / "ia4294"
    p.mkdir(parents=True, exist_ok=True)
    return p
