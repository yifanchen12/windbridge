from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass


DISCOVERY_PORT = 38765
DISCOVERY_MAGIC = b"WINDBRIDGE_DISCOVER_V1"


@dataclass(frozen=True, slots=True)
class DiscoveredNode:
    name: str
    address: str
    port: int


def encode_announcement(name: str, address: str, port: int) -> bytes:
    return json.dumps(
        {"protocol": "windbridge-v1", "name": name[:80], "address": address, "port": int(port)},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def decode_announcement(payload: bytes) -> DiscoveredNode | None:
    try:
        data = json.loads(payload.decode("utf-8"))
        if data.get("protocol") != "windbridge-v1":
            return None
        port = int(data["port"])
        if not 1 <= port <= 65535:
            return None
        return DiscoveredNode(name=str(data["name"]), address=str(data["address"]), port=port)
    except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        return None


class DiscoveryResponder:
    """Small UDP responder used by future WindBridge clients to find this node."""

    def __init__(self, name: str, address: str, service_port: int, discovery_port: int = DISCOVERY_PORT) -> None:
        self.name = name
        self.address = address
        self.service_port = service_port
        self.discovery_port = discovery_port
        self.socket: socket.socket | None = None
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("0.0.0.0", self.discovery_port))
        sock.settimeout(0.4)
        self.socket = sock
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._serve, name="WindBridgeDiscovery", daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        announcement = encode_announcement(self.name, self.address, self.service_port)
        while not self.stop_event.is_set() and self.socket:
            try:
                payload, sender = self.socket.recvfrom(1024)
                if payload == DISCOVERY_MAGIC:
                    self.socket.sendto(announcement, sender)
            except socket.timeout:
                continue
            except OSError:
                break

    def stop(self) -> None:
        self.stop_event.set()
        sock, self.socket = self.socket, None
        if sock:
            sock.close()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)
        self.thread = None


def discover_nodes(timeout: float = 0.8, discovery_port: int = DISCOVERY_PORT) -> list[DiscoveredNode]:
    found: dict[tuple[str, int], DiscoveredNode] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.15)
    try:
        sock.bind(("0.0.0.0", 0))
        sock.sendto(DISCOVERY_MAGIC, ("255.255.255.255", discovery_port))
        deadline = time.monotonic() + max(0.1, timeout)
        while time.monotonic() < deadline:
            try:
                payload, _sender = sock.recvfrom(2048)
            except socket.timeout:
                continue
            node = decode_announcement(payload)
            if node:
                found[(node.address, node.port)] = node
    finally:
        sock.close()
    return list(found.values())
