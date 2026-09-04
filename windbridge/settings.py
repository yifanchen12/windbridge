from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path


def app_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".windbridge")
    return base / "WindBridge"


@dataclass(slots=True)
class Settings:
    port: int = 8765
    incoming_dir: str = str(Path.home() / "Downloads" / "WindBridge")
    auto_copy_received_text: bool = False
    minimize_to_tray: bool = True
    control_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        target = path or app_data_dir() / "settings.json"
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return cls()
        try:
            port = int(payload.get("port", 8765))
        except (TypeError, ValueError):
            port = 8765
        if not 1024 <= port <= 65535:
            port = 8765
        incoming = str(payload.get("incoming_dir") or cls().incoming_dir)
        return cls(
            port=port,
            incoming_dir=incoming,
            auto_copy_received_text=bool(payload.get("auto_copy_received_text", False)),
            minimize_to_tray=bool(payload.get("minimize_to_tray", True)),
            control_token=str(payload.get("control_token") or secrets.token_urlsafe(24)),
        )

    def save(self, path: Path | None = None) -> None:
        target = path or app_data_dir() / "settings.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
