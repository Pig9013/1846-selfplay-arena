"""Local inference server for the 1846 self-play workers.

POST /scores  {"state": [...128], "actions": [[...40], ...]} -> {"scores": [...]}
Reloads checkpoints/latest.pt whenever it changes, so workers always use the
newest trained network without restarting.
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import torch

from net import PolicyValueNet

ROOT = Path(__file__).resolve().parent
CKPT = ROOT / "checkpoints" / "latest.pt"
LOCK = threading.Lock()
MODEL = PolicyValueNet()
MODEL.eval()
MTIME = None


def maybe_reload():
    global MTIME
    try:
        mtime = CKPT.stat().st_mtime
    except FileNotFoundError:
        return
    if MTIME == mtime:
        return
    try:
        state = torch.load(CKPT, map_location="cpu", weights_only=True)
        MODEL.load_state_dict(state["model"])
        MODEL.eval()
        MTIME = mtime
        print(f"[nn] loaded checkpoint step={state.get('step')}", flush=True)
    except Exception as exc:  # noqa: BLE001 - a half-written checkpoint must not kill the server
        print(f"[nn] checkpoint reload failed: {exc}", flush=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        state = payload["state"]
        actions = payload["actions"]
        if not actions:
            body = json.dumps({"scores": []}).encode()
        else:
            with LOCK, torch.no_grad():
                maybe_reload()
                s = torch.tensor([state], dtype=torch.float32)
                a = torch.tensor([actions], dtype=torch.float32)
                logits, _value = MODEL(s, a)
                body = json.dumps({"scores": logits[0].tolist()}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main(port=18346):
    maybe_reload()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[nn] listening on {port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    import sys
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 18346)
