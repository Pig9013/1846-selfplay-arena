"""Local inference server for the 1846 self-play workers.

POST /scores  {"state": [...128], "actions": [[...48], ...]} -> {"scores": [...]}
GET  /health  -> {"ok": true, "step": N, "loaded": true, "device": "cuda", ...}

The server batches requests from all Ruby workers for a few milliseconds and
runs one GPU forward pass. A batch-1 request per decision leaves the GPU idle;
batching makes the neural part actually use the device without changing the
rules engine (which stays on CPU).
"""
import json
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import torch

from net import ACTION_SIZE, PolicyValueNet

ROOT = Path(__file__).resolve().parent
CKPT = ROOT / "checkpoints" / "latest.pt"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
LOCK = threading.Lock()
MODEL = PolicyValueNet().to(DEVICE)
MODEL.eval()
MTIME = None
STEP = 0
LOADED = False
REQUESTS = queue.Queue()
BATCH_MS = float(os.environ.get("NN_BATCH_MS", "8"))
BATCH_MAX = int(os.environ.get("NN_BATCH_MAX", "64"))
STATS = {"requests": 0, "batches": 0, "max_batch": 0, "last_batch": 0}


def maybe_reload():
    global MTIME, STEP, LOADED, MODEL
    try:
        mtime = CKPT.stat().st_mtime
    except FileNotFoundError:
        return
    if MTIME == mtime:
        return
    try:
        state = torch.load(CKPT, map_location="cpu", weights_only=True)
        hidden = int(state.get("hidden") or state["model"]["state.0.weight"].shape[0])
        if hidden != MODEL.hidden:
            MODEL = PolicyValueNet(hidden=hidden).to(DEVICE)
        MODEL.load_state_dict(state["model"])
        MODEL.to(DEVICE)
        MODEL.eval()
        STEP = int(state.get("step", 0))
        LOADED = True
        MTIME = mtime
        print(f"[nn] loaded checkpoint step={state.get('step')} device={DEVICE.type}", flush=True)
    except Exception as exc:  # a half-written checkpoint must not kill the server
        print(f"[nn] checkpoint reload failed: {exc}", flush=True)


def batch_worker():
    while True:
        first = REQUESTS.get()
        batch = [first]
        deadline = time.time() + BATCH_MS / 1000.0
        while len(batch) < BATCH_MAX:
            timeout = deadline - time.time()
            if timeout <= 0:
                break
            try:
                batch.append(REQUESTS.get(timeout=timeout))
            except queue.Empty:
                break
        try:
            with LOCK, torch.inference_mode():
                maybe_reload()
                width = max(len(item["actions"]) for item in batch)
                states = torch.tensor([item["state"] for item in batch],
                                      dtype=torch.float32, device=DEVICE)
                actions = torch.tensor(
                    [item["actions"] + [[0.0] * ACTION_SIZE] * (width - len(item["actions"]))
                     for item in batch],
                    dtype=torch.float32, device=DEVICE)
                logits, _ = MODEL(states, actions)
                rows = logits.detach().cpu().tolist()
            for item, row in zip(batch, rows):
                item["result"] = row[:len(item["actions"])]
        except Exception as exc:  # never leave an HTTP thread waiting forever
            for item in batch:
                item["error"] = str(exc)
        finally:
            for item in batch:
                item["event"].set()
            STATS["requests"] += len(batch)
            STATS["batches"] += 1
            STATS["last_batch"] = len(batch)
            STATS["max_batch"] = max(STATS["max_batch"], len(batch))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] != "/health":
            return self._json(404, {"error": "not found"})
        maybe_reload()
        self._json(200, {"ok": True, "step": STEP, "loaded": LOADED,
                         "device": DEVICE.type, "checkpoint": str(CKPT),
                         "batch_ms": BATCH_MS, "batch_max": BATCH_MAX,
                         "requests": STATS["requests"], "batches": STATS["batches"],
                         "last_batch": STATS["last_batch"], "max_batch": STATS["max_batch"]})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        actions = payload["actions"]
        if not actions:
            return self._json(200, {"scores": []})
        item = {"state": payload["state"], "actions": actions,
                "event": threading.Event(), "result": None, "error": None}
        REQUESTS.put(item)
        if not item["event"].wait(timeout=30):
            return self._json(500, {"error": "inference timeout"})
        if item["error"]:
            return self._json(500, {"error": item["error"]})
        self._json(200, {"scores": item["result"]})


def main(port=18346):
    maybe_reload()
    threading.Thread(target=batch_worker, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[nn] listening on {port} device={DEVICE.type} batch_ms={BATCH_MS}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    import sys
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 18346)
