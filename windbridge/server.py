from __future__ import annotations

import hmac
import hashlib
import errno
import re
import threading
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from werkzeug.serving import BaseWSGIServer, make_server

from .state import BridgeState, unique_destination
from .uploads import CHUNK_SIZE, UploadError, UploadStore


MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024


def create_app(state: BridgeState, web_dir: Path, control_token: str = "") -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    store = UploadStore(state)
    app.extensions["uploads"] = store

    def authorized() -> bool:
        candidate = request.headers.get("X-WindBridge-Token") or request.args.get("token", "")
        return bool(candidate) and hmac.compare_digest(candidate, state.token)

    @app.before_request
    def protect_api():
        if request.path.startswith("/api/") and not authorized():
            return jsonify({"error": "配对码无效，请重新扫描电脑端二维码"}), 401
        return None

    @app.post("/internal/share")
    def internal_share():
        local_request = request.remote_addr in {"127.0.0.1", "::1"}
        candidate = request.headers.get("X-WindBridge-Control", "")
        if not local_request or not control_token or not hmac.compare_digest(candidate, control_token):
            abort(403)
        payload = request.get_json(silent=True) or {}
        paths = payload.get("paths")
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            return jsonify({"error": "文件列表无效"}), 400
        added = state.add_outbound(paths)
        return jsonify({"added": len(added)})

    @app.get("/")
    def index():
        return send_from_directory(web_dir, "index.html")

    @app.get("/favicon.svg")
    def favicon():
        return send_from_directory(web_dir, "favicon.svg", mimetype="image/svg+xml")

    @app.get("/transfer.js")
    @app.get("/sha256.js")
    def transfer_script():
        return send_from_directory(web_dir, request.path[1:], mimetype="text/javascript")

    @app.post("/api/uploads")
    def initialize_upload():
        request.max_content_length = 16 * 1024
        return jsonify(store.initialize(request.get_json(silent=True))), 201

    @app.get("/api/uploads")
    def list_uploads():
        return jsonify({"uploads": store.list_sessions()})

    @app.get("/api/uploads/<upload_id>")
    def upload_status(upload_id: str):
        return jsonify(store.status(upload_id))

    @app.put("/api/uploads/<upload_id>")
    def upload_chunk(upload_id: str):
        request.max_content_length = CHUNK_SIZE
        offset = request.headers.get("Upload-Offset", "")
        if not re.fullmatch(r"[0-9]{1,12}", offset):
            raise UploadError("上传位置无效")
        data = request.get_data()
        return jsonify(store.write(upload_id, int(offset), data, request.headers.get("X-Chunk-SHA256", "")))

    @app.post("/api/uploads/<upload_id>/complete")
    def complete_upload(upload_id: str):
        return jsonify(store.complete(upload_id))

    @app.delete("/api/uploads/<upload_id>")
    def cancel_upload(upload_id: str):
        store.cancel(upload_id)
        return "", 204

    @app.errorhandler(UploadError)
    def upload_error(error):
        return jsonify({"error": str(error)}), error.status

    @app.errorhandler(OSError)
    def storage_error(error):
        code = 507 if error.errno in {errno.ENOSPC, errno.EDQUOT} else 500
        return jsonify({"error": "接收目录写入失败，请检查磁盘空间及目录权限后继续"}), code

    @app.get("/api/status")
    def status():
        return jsonify({"ok": True, **state.snapshot()})

    @app.get("/api/files")
    def files():
        return jsonify({"files": state.list_outbound()})

    @app.get("/api/files/<file_id>/download")
    def download(file_id: str):
        item = state.get_outbound(file_id)
        if not item:
            abort(404)
        stat = Path(item.path).stat()
        tag = hashlib.sha256(f"{item.path}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}".encode()).hexdigest()
        response = send_file(item.path, as_attachment=True, download_name=item.name, conditional=True, etag=tag)
        response.headers["Accept-Ranges"] = "bytes"
        return response

    @app.post("/api/upload")
    def upload():
        uploads = request.files.getlist("files")
        if not uploads:
            return jsonify({"error": "没有选择文件"}), 400
        saved: list[dict[str, object]] = []
        for upload_item in uploads:
            if not upload_item.filename:
                continue
            with state.upload_lock:
                destination = unique_destination(state.incoming_dir, upload_item.filename)
                with destination.open("xb") as stream:
                    upload_item.save(stream)
                saved.append(state.register_upload(destination, destination.name).public())
        return jsonify({"saved": saved}), 201

    @app.get("/api/clipboard")
    def get_clipboard():
        return jsonify(state.clipboard_snapshot())

    @app.post("/api/clipboard")
    def set_clipboard():
        payload = request.get_json(silent=True) or {}
        text = payload.get("text")
        if not isinstance(text, str):
            return jsonify({"error": "文本内容无效"}), 400
        return jsonify(state.publish_clipboard(text, "web"))

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify({"error": "请求体超过上限（分块 4 MiB，文件 2 GiB）"}), 413

    return app


class LocalServer:
    def __init__(self, app: Flask, host: str, port: int) -> None:
        self.app = app
        self.host = host
        self.port = port
        self.server: BaseWSGIServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.server:
            return
        self.server = make_server(self.host, self.port, self.app, threaded=True)
        self.thread = threading.Thread(target=self.server.serve_forever, name="WindBridgeServer", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        server, self.server = self.server, None
        if server:
            server.shutdown()
            server.server_close()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        self.thread = None
