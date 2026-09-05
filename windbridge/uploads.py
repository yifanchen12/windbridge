from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path

from .state import BridgeState, safe_filename, unique_destination


CHUNK_SIZE = 4 * 1024 * 1024
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024
MAX_SESSIONS = 128
RETENTION_SECONDS = 7 * 24 * 60 * 60
_ID = re.compile(r"[0-9a-f]{32}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class UploadError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class UploadStore:
    """Sequential, durable chunk commits. Never expose partial files as downloads.

    Data is flushed before atomically replacing the manifest. An uncommitted
    tail is discarded after interruption. Final publication is no-clobber;
    a durable finalizing record makes completion safe to retry after a crash.
    A dedicated lock serializes upload I/O without blocking desktop snapshots.
    """

    def __init__(self, state: BridgeState) -> None:
        self.state = state
        self.destination = state.incoming_dir.resolve()
        self.root = self.destination / ".windbridge-partials"

    def _prepare(self) -> None:
        # Do not follow an accidentally or deliberately redirected staging folder.
        self.destination.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or self.root.resolve() != self.root:
            raise UploadError("续传目录被重定向，请在电脑端检查接收目录", 409)
        self.root.mkdir(exist_ok=True)

    def _paths(self, upload_id: str) -> tuple[Path, Path]:
        if not _ID.fullmatch(upload_id):
            raise UploadError("续传任务不存在", 404)
        manifest = self.root / f"{upload_id}.json"
        part = self.root / f"{upload_id}.part"
        if manifest.is_symlink() or part.is_symlink():
            raise UploadError("续传任务路径异常", 409)
        return manifest, part

    def _save(self, session: dict) -> None:
        manifest, _ = self._paths(session["id"])
        temporary = manifest.with_suffix(".tmp")
        if temporary.is_symlink():
            raise UploadError("续传任务路径异常", 409)
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(session, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, manifest)

    def _load(self, upload_id: str) -> dict:
        manifest, part = self._paths(upload_id)
        if not manifest.is_file():
            raise UploadError("续传任务不存在或已过期，请重新选择文件", 404)
        def require(condition: object) -> None:
            if not condition:
                raise ValueError("invalid upload manifest")

        try:
            session = json.loads(manifest.read_text(encoding="utf-8"))
            require(isinstance(session, dict) and session["id"] == upload_id)
            require(session["status"] in {"uploading", "finalizing", "completed"})
            require(type(session["size"]) is int and 0 <= session["size"] <= MAX_FILE_SIZE)
            require(type(session["offset"]) is int and 0 <= session["offset"] <= session["size"])
            require(session["chunk_size"] == CHUNK_SIZE)
            require(len(session["hashes"]) == (session["offset"] + CHUNK_SIZE - 1) // CHUNK_SIZE)
            require(all(isinstance(digest, str) and _HASH.fullmatch(digest) for digest in session["hashes"]))
            require(session["offset"] == session["size"] or session["offset"] % CHUNK_SIZE == 0)
            require(safe_filename(session["name"]) == session["name"])
            require(_HASH.fullmatch(session["fingerprint"]))
            require(isinstance(session["updated_at"], (int, float)))
            if session["status"] != "uploading":
                require(session["offset"] == session["size"])
                require(safe_filename(session["final_name"]) == session["final_name"])
                require(_HASH.fullmatch(session["sha256"]))
        except (ValueError, KeyError, TypeError, AssertionError):
            raise UploadError("续传记录损坏，请取消任务后重新上传", 409) from None
        if session["status"] == "uploading":
            if not part.is_file():
                raise UploadError("未完成文件已丢失，请取消任务后重新上传", 409)
            length = part.stat().st_size
            if length < session["offset"]:
                raise UploadError("未完成文件长度异常，请取消任务后重新上传", 409)
            if length > session["offset"]:
                # A previous write reached disk but its manifest commit did not.
                with part.open("r+b") as stream:
                    stream.truncate(session["offset"])
        return session

    @staticmethod
    def _public(session: dict) -> dict:
        data = {key: session[key] for key in (
            "id", "name", "size", "fingerprint", "offset", "chunk_size", "hashes", "updated_at"
        )}
        data["status"] = "completed" if session["status"] == "completed" else "uploading"
        if session["status"] == "completed":
            data["file"] = {
                "id": session["id"], "name": session["final_name"],
                "size": session["size"], "sha256": session["sha256"],
            }
        return data

    def _cleanup(self) -> None:
        cutoff = time.time() - RETENTION_SECONDS
        for manifest in self.root.glob("*.json"):
            if not _ID.fullmatch(manifest.stem) or manifest.is_symlink():
                continue
            # Manifest mtime changes only at committed progress/receipt updates.
            if manifest.stat().st_mtime < cutoff:
                self._delete(manifest.stem)

    def initialize(self, payload: object) -> dict:
        if not isinstance(payload, dict):
            raise UploadError("上传参数必须为对象")
        name, size, fingerprint = (payload.get(key) for key in ("name", "size", "fingerprint"))
        if not isinstance(name, str) or not name.strip() or len(name) > 1024:
            raise UploadError("文件名无效")
        if type(size) is not int or size < 0:
            raise UploadError("文件大小无效")
        if size > MAX_FILE_SIZE:
            raise UploadError("单文件超过 2 GiB 上限", 413)
        if not isinstance(fingerprint, str) or not _HASH.fullmatch(fingerprint):
            raise UploadError("文件指纹无效")
        name = safe_filename(name)
        with self.state.upload_lock:
            self._prepare()
            self._cleanup()
            manifests = list(self.root.glob("*.json"))
            for manifest in manifests:
                if not _ID.fullmatch(manifest.stem):
                    continue
                try:
                    session = self._load(manifest.stem)
                except UploadError:
                    continue
                if (session["name"], session["size"], session["fingerprint"]) == (name, size, fingerprint):
                    return self._public(session)
            if len(manifests) >= MAX_SESSIONS:
                raise UploadError("续传记录已达上限，请先取消不需要的任务", 429)
            upload_id = secrets.token_hex(16)
            session = {
                "id": upload_id, "name": name, "size": size, "fingerprint": fingerprint,
                "offset": 0, "hashes": [], "chunk_size": CHUNK_SIZE,
                "status": "uploading", "updated_at": time.time(),
            }
            _, part = self._paths(upload_id)
            part.touch(exist_ok=False)
            self._save(session)
            return self._public(session)

    def list_sessions(self) -> list[dict]:
        with self.state.upload_lock:
            self._prepare()
            self._cleanup()
            result = []
            for manifest in self.root.glob("*.json"):
                if not _ID.fullmatch(manifest.stem):
                    continue
                try:
                    result.append(self._public(self._load(manifest.stem)))
                except UploadError:
                    continue
            return sorted(result, key=lambda item: item["updated_at"], reverse=True)

    def status(self, upload_id: str) -> dict:
        with self.state.upload_lock:
            self._prepare()
            return self._public(self._load(upload_id))

    def write(self, upload_id: str, offset: int, data: bytes, digest: str) -> dict:
        if not _HASH.fullmatch(digest):
            raise UploadError("分块校验值无效")
        if hashlib.sha256(data).hexdigest() != digest:
            raise UploadError("分块校验失败，数据未写入", 422)
        with self.state.upload_lock:
            self._prepare()
            session = self._load(upload_id)
            if session["status"] != "uploading" or offset != session["offset"]:
                raise UploadError("上传位置已改变，请读取最新进度后继续", 409)
            expected = min(CHUNK_SIZE, session["size"] - offset)
            if not data or len(data) != expected:
                raise UploadError("分块长度不符合当前上传位置")
            if shutil.disk_usage(self.destination).free < len(data) + 16 * 1024 * 1024:
                raise UploadError("接收磁盘剩余空间不足，请释放空间后继续", 507)
            _, part = self._paths(upload_id)
            with part.open("r+b") as stream:
                stream.seek(offset)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            session["offset"] += len(data)
            session["hashes"].append(digest)
            session["updated_at"] = time.time()
            self._save(session)
            return self._public(session)

    def _verify(self, path: Path, session: dict) -> str:
        whole = hashlib.sha256()
        with path.open("rb") as stream:
            for expected in session["hashes"]:
                block = stream.read(CHUNK_SIZE)
                if hashlib.sha256(block).hexdigest() != expected:
                    raise UploadError("已保存分块校验失败，请取消任务并重新上传", 422)
                whole.update(block)
            if stream.read(1):
                raise UploadError("文件长度不符，请重新上传", 422)
        if path.stat().st_size != session["size"]:
            raise UploadError("文件长度不符，请重新上传", 422)
        return whole.hexdigest()

    def complete(self, upload_id: str) -> dict:
        with self.state.upload_lock:
            self._prepare()
            session = self._load(upload_id)
            _, part = self._paths(upload_id)
            if session["status"] == "completed":
                target = self.destination / session.get("final_name", "")
                if safe_filename(target.name) != session.get("final_name") or target.is_symlink():
                    raise UploadError("成品路径异常", 409)
                if not target.is_file():
                    raise UploadError("已完成文件被移动，请取消记录后重新上传", 410)
                if self._verify(target, session) != session["sha256"]:
                    raise UploadError("已完成文件被修改，请取消记录后重新上传", 410)
            if session["offset"] != session["size"]:
                raise UploadError("文件尚未上传完整", 409)
            if session["status"] == "uploading":
                session["sha256"] = self._verify(part, session)
                session["final_name"] = unique_destination(self.destination, session["name"]).name
                session["status"] = "finalizing"
                self._save(session)
            if safe_filename(session.get("final_name", "")) != session.get("final_name"):
                raise UploadError("成品路径异常", 409)
            target = self.destination / session["final_name"]
            if target.is_symlink():
                raise UploadError("成品路径被重定向，请取消后重新上传", 409)
            if session["status"] == "finalizing":
                # Recover a crash after publication but before receipt commit.
                published = False
                if target.is_file():
                    published = (part.is_file() and os.path.samefile(part, target)) or (
                        not part.exists() and self._verify(target, session) == session["sha256"]
                    )
                if not published:
                    if not part.is_file():
                        raise UploadError("未完成文件已丢失，请重新上传", 409)
                    if self._verify(part, session) != session["sha256"]:
                        raise UploadError("成品校验失败", 422)
                    for _attempt in range(100):
                        try:
                            if os.name == "nt":
                                # Windows rename is atomic and fails if target exists.
                                os.rename(part, target)
                            else:
                                os.link(part, target)
                            break
                        except FileExistsError:
                            target = unique_destination(self.destination, session["name"])
                            session["final_name"] = target.name
                            self._save(session)
                    else:
                        raise UploadError("同名文件冲突，请稍后重试", 409)
                session["status"] = "completed"
                session["updated_at"] = time.time()
                self._save(session)
            if not target.is_file() or target.stat().st_size != session["size"]:
                raise UploadError("已完成文件被移动或修改，请取消记录后重新上传", 410)
            part.unlink(missing_ok=True)
            self.state.register_upload(target, target.name, file_id=session["id"])
            return self._public(session)

    def _delete(self, upload_id: str) -> None:
        manifest, part = self._paths(upload_id)
        part.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)
        temporary = manifest.with_suffix(".tmp")
        if not temporary.is_symlink():
            temporary.unlink(missing_ok=True)

    def cancel(self, upload_id: str) -> None:
        with self.state.upload_lock:
            self._prepare()
            self._delete(upload_id)
