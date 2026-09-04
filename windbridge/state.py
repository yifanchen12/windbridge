from __future__ import annotations

import re
import secrets
import threading
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str) -> str:
    cleaned = INVALID_FILENAME.sub("_", Path(name).name).strip(" .")
    return cleaned[:180] or "unnamed-file"


def unique_destination(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / safe_filename(name)
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for index in range(1, 10_000):
        next_candidate = folder / f"{stem} ({index}){suffix}"
        if not next_candidate.exists():
            return next_candidate
    raise OSError("无法为上传文件生成唯一名称")


@dataclass(frozen=True, slots=True)
class SharedFile:
    id: str
    name: str
    path: str
    size: int
    direction: str
    created_at: str

    def public(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("path", None)
        return payload


class BridgeState:
    def __init__(self, incoming_dir: str | Path) -> None:
        self.lock = threading.RLock()
        self.incoming_dir = Path(incoming_dir).expanduser().resolve()
        self.incoming_dir.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(8)
        self.outbound: dict[str, SharedFile] = {}
        self.inbound: dict[str, SharedFile] = {}
        self.clipboard_text = ""
        self.clipboard_source = "desktop"
        self.clipboard_updated_at = ""
        self.revision = 0
        self.events: deque[dict[str, str]] = deque(maxlen=40)

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _touch(self, message: str) -> None:
        self.revision += 1
        self.events.appendleft({"time": self._now(), "message": message})

    def rotate_token(self) -> str:
        with self.lock:
            self.token = secrets.token_urlsafe(8)
            self._touch("已更新配对码，旧链接失效")
            return self.token

    def set_incoming_dir(self, folder: str | Path) -> None:
        target = Path(folder).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        with self.lock:
            self.incoming_dir = target
            self._touch(f"接收目录已切换至 {target}")

    def add_outbound(self, paths: Iterable[str | Path]) -> list[SharedFile]:
        added: list[SharedFile] = []
        with self.lock:
            for value in paths:
                path = Path(value).expanduser().resolve()
                if not path.is_file():
                    continue
                item = SharedFile(
                    id=secrets.token_hex(8),
                    name=path.name,
                    path=str(path),
                    size=path.stat().st_size,
                    direction="outbound",
                    created_at=self._now(),
                )
                self.outbound[item.id] = item
                added.append(item)
            if added:
                self._touch(f"已共享 {len(added)} 个文件")
        return added

    def register_upload(self, path: str | Path, original_name: str) -> SharedFile:
        target = Path(path).resolve()
        item = SharedFile(
            id=secrets.token_hex(8),
            name=safe_filename(original_name),
            path=str(target),
            size=target.stat().st_size,
            direction="inbound",
            created_at=self._now(),
        )
        with self.lock:
            self.inbound[item.id] = item
            self._touch(f"收到文件：{item.name}")
        return item

    def remove_outbound(self, file_id: str) -> bool:
        with self.lock:
            item = self.outbound.pop(file_id, None)
            if item:
                self._touch(f"已取消共享：{item.name}")
            return item is not None

    def get_outbound(self, file_id: str) -> SharedFile | None:
        with self.lock:
            item = self.outbound.get(file_id)
        if item and Path(item.path).is_file():
            return item
        return None

    def get_inbound(self, file_id: str) -> SharedFile | None:
        with self.lock:
            item = self.inbound.get(file_id)
        if item and Path(item.path).is_file():
            return item
        return None

    def list_outbound(self) -> list[dict[str, object]]:
        with self.lock:
            items = list(self.outbound.values())
        return [item.public() for item in reversed(items)]

    def list_inbound(self) -> list[dict[str, object]]:
        with self.lock:
            items = list(self.inbound.values())
        return [item.public() for item in reversed(items)]

    def publish_clipboard(self, text: str, source: str) -> dict[str, object]:
        value = text[:200_000]
        with self.lock:
            self.clipboard_text = value
            self.clipboard_source = source
            self.clipboard_updated_at = self._now()
            self._touch(f"收到来自{'网页' if source == 'web' else '电脑'}的文本")
            return self.clipboard_snapshot()

    def clipboard_snapshot(self) -> dict[str, object]:
        with self.lock:
            return {
                "text": self.clipboard_text,
                "source": self.clipboard_source,
                "updated_at": self.clipboard_updated_at,
                "revision": self.revision,
            }

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            outbound = len(self.outbound)
            inbound = len(self.inbound)
            outbound_bytes = sum(item.size for item in self.outbound.values())
            inbound_bytes = sum(item.size for item in self.inbound.values())
            return {
                "revision": self.revision,
                "outbound_count": outbound,
                "inbound_count": inbound,
                "outbound_bytes": outbound_bytes,
                "inbound_bytes": inbound_bytes,
                "events": list(self.events),
            }
