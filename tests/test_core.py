from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from windbridge.discovery import DiscoveredNode, decode_announcement, encode_announcement
from windbridge.server import create_app
from windbridge.settings import Settings
from windbridge.state import BridgeState, safe_filename, unique_destination


ROOT = Path(__file__).resolve().parents[1]


class StateTests(unittest.TestCase):
    def test_safe_filename_and_unique_destination(self):
        self.assertEqual(safe_filename("../../bad:name?.pdf"), "bad_name_.pdf")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "book.pdf").write_bytes(b"one")
            self.assertEqual(unique_destination(root, "book.pdf").name, "book (1).pdf")

    def test_files_and_clipboard(self):
        with tempfile.TemporaryDirectory() as folder:
            sample = Path(folder) / "hello.txt"
            sample.write_text("hello", encoding="utf-8")
            state = BridgeState(Path(folder) / "incoming")
            added = state.add_outbound([sample])
            self.assertEqual(len(added), 1)
            self.assertEqual(state.list_outbound()[0]["name"], "hello.txt")
            snapshot = state.publish_clipboard("随风而行", "desktop")
            self.assertEqual(snapshot["text"], "随风而行")
            self.assertTrue(state.remove_outbound(added[0].id))


class ServerTests(unittest.TestCase):
    def test_pairing_upload_download_and_clipboard(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = BridgeState(root / "incoming")
            sample = root / "shared.txt"
            sample.write_bytes(b"from desktop")
            item = state.add_outbound([sample])[0]
            control = "local-control-test"
            client = create_app(state, ROOT / "web", control).test_client()

            self.assertEqual(client.get("/api/status").status_code, 401)
            auth = {"X-WindBridge-Token": state.token}
            self.assertEqual(client.get("/api/status", headers=auth).status_code, 200)
            response = client.get(f"/api/files/{item.id}/download", headers=auth)
            self.assertEqual(response.data, b"from desktop")
            response.close()

            response = client.post(
                "/api/upload",
                data={"files": (io.BytesIO(b"from phone"), "phone.txt")},
                headers=auth,
                content_type="multipart/form-data",
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual((root / "incoming" / "phone.txt").read_bytes(), b"from phone")

            response = client.post("/api/clipboard", json={"text": "hello pc"}, headers=auth)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(state.clipboard_snapshot()["source"], "web")

            self.assertEqual(client.post("/internal/share", json={"paths": [str(sample)]}).status_code, 403)
            response = client.post(
                "/internal/share",
                json={"paths": [str(sample)]},
                headers={"X-WindBridge-Control": control},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["added"], 1)


class SettingsTests(unittest.TestCase):
    def test_roundtrip_and_port_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            settings = Settings(port=9000, incoming_dir=folder, auto_copy_received_text=True)
            control_token = settings.control_token
            settings.save(path)
            loaded = Settings.load(path)
            self.assertEqual(loaded.port, 9000)
            self.assertTrue(loaded.auto_copy_received_text)
            self.assertEqual(loaded.control_token, control_token)
            path.write_text('{"port": 1}', encoding="utf-8")
            self.assertEqual(Settings.load(path).port, 8765)


class DiscoveryTests(unittest.TestCase):
    def test_announcement_roundtrip_and_rejection(self):
        payload = encode_announcement("My Laptop", "192.168.1.8", 8765)
        self.assertEqual(decode_announcement(payload), DiscoveredNode("My Laptop", "192.168.1.8", 8765))
        self.assertIsNone(decode_announcement(b"not-json"))


if __name__ == "__main__":
    unittest.main()
