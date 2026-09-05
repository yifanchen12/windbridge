"""Isolated loopback-only fixture for the optional browser integration test."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werkzeug.serving import WSGIRequestHandler, make_server
from windbridge.server import create_app
from windbridge.state import BridgeState


class QuietHandler(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


if __name__ == '__main__':
    state = BridgeState(Path(sys.argv[1]))
    state.token = os.environ['WINDBRIDGE_TEST_TOKEN']
    server = make_server('127.0.0.1', int(sys.argv[2]), create_app(state, Path(__file__).resolve().parents[1]/'web'),
                         threaded=True, request_handler=QuietHandler)
    print(f'PORT:{server.server_port}', flush=True)
    server.serve_forever()
