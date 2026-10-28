"""Local 1846 arena. Python standard library only; no cloud services required."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
TRAIN_STATUS = ROOT / "train" / "status.json"
TRAIN_LOG = ROOT / "train" / "log.jsonl"
TRAIN_PID = ROOT / "train" / "run.pid"
TRAIN_GAMES = ROOT / "train" / "games.jsonl"
TRAIN_REPORTS = ROOT / "train" / "reports"
TRAIN_SCRIPT = ROOT / "train" / "orchestrate.py"
RUBY = ROOT / "runtime/rubyinstaller-3.4.9-1-x64/bin/ruby.exe"
STYLES = {"balanced", "growth", "income", "random", "lmstudio", "neural"}
RUNS.mkdir(exist_ok=True)
LOCK = threading.RLock()
LIVE: dict[str, dict] = {}
ACTIVE: str | None = None
TRAIN_PROC = None
BATCH: dict = {"active": False}


def save(path: Path, obj):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    # Windows readers/virus scanners can briefly hold the destination open.
    for attempt in range(20):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(.025 * (attempt + 1))


def read(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def probe_json(url, timeout=0.8):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.load(response)
    except (urllib.error.URLError, OSError, ValueError):
        return None


def local_model_report():
    """Detect optional local LLM servers and the project's own checkpoint.

    The arena does not require any of these. The neural checkpoint is the
    built-in model that drives self-play; LM Studio / Ollama / llama.cpp are
    optional external decision sources.
    """
    providers = []

    data = probe_json("http://127.0.0.1:1234/v1/models")
    if data is not None:
        providers.append({"id": "lmstudio", "label": "LM Studio", "url": "http://127.0.0.1:1234",
                          "ok": True,
                          "models": [m.get("id") for m in data.get("data", []) if m.get("id")]})

    data = probe_json("http://127.0.0.1:11434/api/tags")
    if data is not None:
        providers.append({"id": "ollama", "label": "Ollama", "url": "http://127.0.0.1:11434",
                          "ok": True,
                          "models": [m.get("name") for m in data.get("models", []) if m.get("name")]})

    for port, label in ((8080, "llama.cpp"), (8000, "vLLM"), (5000, "text-generation-webui")):
        data = probe_json(f"http://127.0.0.1:{port}/v1/models")
        if data is not None:
            providers.append({"id": label.lower().replace(".", "").replace("-", ""),
                              "label": label, "url": f"http://127.0.0.1:{port}", "ok": True,
                              "models": [m.get("id") for m in data.get("data", []) if m.get("id")]})

    checkpoint = ROOT / "train" / "checkpoints" / "latest.pt"
    status = read(TRAIN_STATUS, {})
    health = probe_json("http://127.0.0.1:18346/health")
    neural = {"available": checkpoint.is_file(), "checkpoint": str(checkpoint),
              "step": status.get("checkpoint_step") or status.get("train_steps") or 0,
              "mtime": checkpoint.stat().st_mtime if checkpoint.is_file() else None,
              "size": checkpoint.stat().st_size if checkpoint.is_file() else 0,
              "server": health}
    return {"providers": providers, "neural": neural, "heuristic": True}


def validate(raw):
    players = int(raw.get("players", 3))
    seed = int(raw.get("seed", 42))
    strategies = raw.get("strategies", ["balanced", "growth", "income"])
    if players not in (3, 4, 5):
        raise ValueError("标准 1846 支持 3—5 人。")
    if not 0 <= seed <= 2_000_000_000:
        raise ValueError("种子必须在 0 到 20 亿之间。")
    if not isinstance(strategies, list) or not strategies or any(s not in STYLES for s in strategies):
        raise ValueError("请选择已支持的机器人策略。")
    strategies = [strategies[i % len(strategies)] for i in range(players)]
    model = str(raw.get("model", ""))[:200]
    if "lmstudio" in strategies and not model:
        raise ValueError("使用 LM Studio 时，请先检测并选择已加载的模型。")
    hpw = max(0.0, min(float(raw.get("human_prior_weight", 10)), 50.0))
    config = {"players": players, "seed": seed, "strategies": strategies, "model": model,
              "max_actions": 3000, "human_prior_weight": hpw}
    if "neural" in strategies:
        # The local neural checkpoint is a separate decision source from LM
        # Studio. It needs no external model server to be selectable; arena.rb
        # falls back to the heuristic if the inference server is down.
        config["net_url"] = os.environ.get("DSH_1846_NET", "http://127.0.0.1:18346/scores")
        config["net_weight"] = 15
    return config


def run_dir(run_id):
    if not re.fullmatch(r"[0-9a-f]{12}", run_id):
        raise ValueError("无效的对局编号。")
    path = RUNS / run_id
    if not path.is_dir():
        raise ValueError("找不到这局记录。")
    return path


def summary(run_id):
    return read(run_dir(run_id) / "summary.json", {})


def engine_process(config_path, *, script="arena.rb", output=subprocess.PIPE):
    env = dict(os.environ, RUBYOPT="-EUTF-8", RACK_ENV="production", ENGINE_LOG_LEVEL="4")
    # RubyInstaller resolves require_relative through the Windows console code
    # page. Set UTF-8 for this child so Chinese workspace paths work correctly.
    command = f'chcp 65001 >nul && "{RUBY}" {script} "{config_path}"'
    return subprocess.Popen('cmd.exe /d /s /c "' + command + '"', cwd=ROOT, env=env,
                            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW)


def start_run(config, *, from_batch=False):
    global ACTIVE
    with LOCK:
        if ACTIVE is not None or (BATCH["active"] and not from_batch):
            raise ValueError("已有对局或批次在运行。请等待结束或先停止。")
        if not RUBY.is_file():
            raise ValueError("找不到本地 Ruby 运行环境，请查看使用说明。")
        run_id = uuid.uuid4().hex[:12]
        path = RUNS / run_id
        path.mkdir()
        save(path / "config.json", config)
        data = {"id": run_id, "config": config, "status": "running", "created": time.time(),
                "frames": 0, "action_count": 0, "error": None, "version": "1.2.0"}
        save(path / "summary.json", data)
        LIVE[run_id] = {"summary": data, "state": None, "board": [], "decision": None,
                        "logs": [], "offsets": [], "process": None, "pause": False,
                        "stop": False, "step_budget": 0, "condition": threading.Condition()}
        ACTIVE = run_id
        threading.Thread(target=worker, args=(run_id,), daemon=True).start()
        return run_id


def worker(run_id):
    global ACTIVE
    live = LIVE[run_id]
    path = RUNS / run_id
    data = live["summary"]
    checkpoint = None
    try:
        proc = engine_process(path / "config.json")
        live["process"] = proc
        # Drain stderr independently so a diagnostic cannot block the engine.
        def drain():
            with (path / "engine-stderr.log").open("w", encoding="utf-8") as stream:
                for line in proc.stderr:
                    stream.write(line)
        threading.Thread(target=drain, daemon=True).start()
        with (path / "frames.jsonl").open("wb") as frames, \
             (path / "transitions.jsonl").open("w", encoding="utf-8") as transitions:
            for line in proc.stdout:
                with live["condition"]:
                    while live["pause"] and not live["stop"] and live["step_budget"] <= 0:
                        live["condition"].wait(timeout=1)
                    if live["stop"]:
                        break
                    if live["step_budget"] > 0:
                        live["step_budget"] -= 1
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    with (path / "engine-stderr.log").open("a", encoding="utf-8") as log:
                        log.write(line)
                    continue
                kind = event.get("event")
                if kind in ("state", "transition"):
                    if kind == "state":
                        checkpoint = event["game"]
                        save(path / "game.json", checkpoint)
                    elif checkpoint is not None:
                        checkpoint["actions"].append(event["accepted_action"])
                        checkpoint["result"] = event["state"]["result"]
                    frame = {"state": event["state"], "board": event["board"],
                             "decision": event.get("decision"), "logs": event.get("logs", [])}
                    with LOCK:
                        live["offsets"].append(frames.tell())
                        frames.write((json.dumps(frame, ensure_ascii=False) + "\n").encode("utf-8"))
                        frames.flush()
                        if kind == "transition":
                            transition = {"schema_version": 1,
                                          "observation": dict(event["observation"], board=live["board"]),
                                          "decision": event["decision"],
                                          "next_observation": dict(event["state"], board=event["board"])}
                            transitions.write(json.dumps(transition, ensure_ascii=False) + "\n")
                            transitions.flush()
                        live.update(frame)
                        live["logs"] = (live.get("history_logs", []) + frame["logs"])[-250:]
                        live["history_logs"] = live["logs"]
                        data.update(frames=len(live["offsets"]), action_count=event["state"]["action_count"],
                                    phase=event["state"]["phase"], turn=event["state"]["turn"])
                    if data["frames"] % 10 == 1:
                        save(path / "summary.json", data)
                        save(path / "latest.json", frame)
                        if checkpoint is not None:
                            save(path / "game.json", checkpoint)
                elif kind == "complete":
                    checkpoint = event["game"]
                    state = event["state"]
                    save(path / "game.json", event["game"])
                    (path / "对局日志.txt").write_text("\n".join(event["log"]), encoding="utf-8")
                    save(path / "outcome.json", {"result": state["result"], "end_reason": state["end_reason"],
                                                "ranks": {p: 1 + sum(v > value for v in state["result"].values())
                                                          for p, value in state["result"].items()}})
                    data.update(status="complete", result=state["result"], end_reason=state["end_reason"])
                    live["state"] = state
                elif kind == "error":
                    checkpoint = event.get("game", checkpoint)
                    save(path / "game.json", event.get("game", {}))
                    save(path / "error.json", event)
                    data.update(status="error", error=event["message"])
            if live["stop"]:
                if proc.poll() is None:
                    terminate_engine(proc)
                data["status"] = "stopped"
            code = proc.wait(timeout=20)
            if data["status"] not in ("complete", "stopped", "error"):
                data.update(status="error", error=f"规则引擎退出（{code}），请查看 engine-stderr.log。")
    except Exception as exc:
        data.update(status="error", error=str(exc))
    finally:
        proc = live.get("process")
        if proc is not None and proc.poll() is None:
            terminate_engine(proc)
        data["finished_at"] = time.time()
        data["elapsed"] = round(data["finished_at"] - data["created"], 2)
        if live["state"]:
            save(path / "latest.json", {k: live[k] for k in ("state", "board", "decision", "logs")})
        if checkpoint is not None:
            save(path / "game.json", checkpoint)
        save(path / "summary.json", data)
        with LOCK:
            if ACTIVE == run_id:
                ACTIVE = None


def terminate_engine(proc):
    # cmd.exe launches Ruby; terminate the whole process tree on Windows.
    if proc.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)


def control(run_id, action):
    live = LIVE.get(run_id)
    if live is None or live["summary"]["status"] not in ("running", "paused"):
        raise ValueError("这局当前没有运行。")
    with live["condition"]:
        if action == "pause":
            live["pause"] = True
            live["summary"]["status"] = "paused"
        elif action == "resume":
            live["pause"] = False
            live["summary"]["status"] = "running"
        elif action == "step":
            live["pause"] = True
            live["step_budget"] += 1
            live["summary"]["status"] = "paused"
        elif action == "stop":
            live["stop"] = True
            live["pause"] = False
            proc = live.get("process")
            if proc is not None and proc.poll() is None:
                terminate_engine(proc)
        else:
            raise ValueError("不支持此操作。")
        live["condition"].notify_all()
    return live["summary"]


def history_frame(run_id, index):
    path = run_dir(run_id)
    offsets = LIVE.get(run_id, {}).get("offsets")
    if offsets is None:
        offsets = []
        with (path / "frames.jsonl").open("rb") as stream:
            while True:
                pos = stream.tell()
                if not stream.readline():
                    break
                offsets.append(pos)
    if not 0 <= index < len(offsets):
        raise ValueError("回放位置超出记录范围。")
    with (path / "frames.jsonl").open("rb") as stream:
        stream.seek(offsets[index])
        return json.loads(stream.readline())


def batch_worker(config, count):
    global BATCH
    i = 0
    while count == 0 or i < count:
        if BATCH.get("cancelled"):
            break
        current = dict(config, seed=(config["seed"] + i) % 2_000_000_000)
        # Rotate seats within a batch to make strategy comparisons less seat dependent.
        rotation = i % config["players"]
        current["strategies"] = config["strategies"][rotation:] + config["strategies"][:rotation]
        try:
            run_id = start_run(current, from_batch=True)
            BATCH.update(current=run_id, index=i + 1)
            BATCH["runs"].append(run_id)
            while ACTIVE == run_id:
                time.sleep(0.2)
            data = summary(run_id)
            if data["status"] != "complete":
                BATCH.update(error=data.get("error") or "对局停止，批次已中止。")
                break
        except Exception as exc:
            BATCH["error"] = str(exc)
            break
        i += 1
    BATCH["active"] = False
    save(RUNS / "last-batch.json", BATCH)


def train_snapshot():
    status = read(TRAIN_STATUS, {})
    entries = []
    if TRAIN_LOG.is_file():
        try:
            lines = TRAIN_LOG.read_text(encoding="utf-8").strip().splitlines()[-30:]
            entries = [json.loads(line) for line in lines if line.strip()]
        except (OSError, json.JSONDecodeError):
            entries = []
    recent_games = []
    if TRAIN_GAMES.is_file():
        try:
            lines = TRAIN_GAMES.read_text(encoding="utf-8").strip().splitlines()[-12:]
            recent_games = [json.loads(line) for line in lines if line.strip()]
        except (OSError, json.JSONDecodeError):
            recent_games = []
    reports = []
    if TRAIN_REPORTS.is_dir():
        for path in sorted(TRAIN_REPORTS.glob("logic-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
            reports.append({"name": path.name, "mtime": path.stat().st_mtime, "size": path.stat().st_size})
    proc = TRAIN_PROC
    running = bool(proc is not None and proc.poll() is None)
    if not running and TRAIN_STATUS.is_file():
        # An orchestrator started outside this server still keeps status fresh.
        try:
            running = time.time() - TRAIN_STATUS.stat().st_mtime < 20
        except OSError:
            running = False
    data_dir = ROOT / "train" / "data"
    files = len(list(data_dir.glob("*.jsonl"))) if data_dir.is_dir() else 0
    return {"status": status, "log": entries, "recent_games": recent_games,
            "running": running, "samples": files, "reports": reports}


def start_training(payload):
    global TRAIN_PROC
    if TRAIN_PROC is not None and TRAIN_PROC.poll() is None:
        raise ValueError("训练已经在运行。")
    # An orchestrator started from the launcher keeps status.json fresh even
    # though this server did not spawn it.
    if TRAIN_PROC is None and TRAIN_STATUS.is_file():
        try:
            if time.time() - TRAIN_STATUS.stat().st_mtime < 10 and not read(TRAIN_STATUS, {}).get("stopped"):
                raise ValueError("训练已经在运行（由外部窗口启动）。请先停止那边的训练。")
        except OSError:
            pass
    cores = max(1, (os.cpu_count() or 4) - 2)
    workers = max(1, min(int(payload.get("workers", 6)), cores, 12))
    minutes = float(payload.get("minutes", 0))
    minutes = 0.0 if minutes <= 0 else min(minutes, 10080.0)
    human_prior_weight = max(0.0, min(float(payload.get("human_prior_weight", 10)), 50.0))
    seed = int(payload.get("seed", 2000))
    flags = subprocess.CREATE_NO_WINDOW | 0x00004000  # below normal priority
    command = [sys.executable, "-u", str(TRAIN_SCRIPT), "--workers", str(workers),
               "--minutes", str(minutes), "--seed", str(seed), "--train-every", "4",
               "--steps", "150", "--net-weight", "15", "--human-prior-weight", str(human_prior_weight),
               "--temperature", "1.5",
               "--report-every", "1000", "--eval-every", "300", "--keep", "4000"]
    if minutes == 0:
        command.append("--continuous")
    TRAIN_PROC = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, creationflags=flags)
    TRAIN_PID.write_text(str(TRAIN_PROC.pid), encoding="utf-8")
    return {"started": TRAIN_PROC.pid, "workers": workers, "minutes": minutes,
            "continuous": minutes == 0}


def run_analysis():
    script = ROOT / "train" / "analyze.py"
    if not script.is_file():
        raise ValueError("分析脚本尚未安装。")
    status = read(TRAIN_STATUS, {})
    label = int(status.get("games", 0) or 0)
    try:
        proc = subprocess.run([sys.executable, str(script), "--data", str(ROOT / "train" / "data"),
                               "--out", str(TRAIN_REPORTS), "--label", str(label)],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=300)
    except subprocess.TimeoutExpired:
        raise ValueError("分析超时；样本较多时请稍后再试。") from None
    if proc.returncode != 0:
        raise ValueError((proc.stderr or proc.stdout or "分析失败")[-500:])
    newest = None
    if TRAIN_REPORTS.is_dir():
        files = sorted(TRAIN_REPORTS.glob("logic-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        newest = files[0] if files else None
    return {"report": str(newest.relative_to(ROOT)) if newest else None,
            "label": label, "stdout": (proc.stdout or "")[-800:]}


def _kill_training(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


def stop_training():
    global TRAIN_PROC
    proc = TRAIN_PROC
    pid = None
    if proc is not None and proc.poll() is None:
        pid = proc.pid
    elif TRAIN_PID.is_file():
        # Only trust the PID file while the orchestrator is still writing
        # status.json. A stale PID could belong to an unrelated process after
        # Windows reuses it.
        try:
            fresh = TRAIN_STATUS.is_file() and time.time() - TRAIN_STATUS.stat().st_mtime < 60
            if fresh:
                pid = int(TRAIN_PID.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = None
    TRAIN_PROC = None
    if pid is None:
        return {"stopped": False}
    _kill_training(pid)
    time.sleep(0.5)
    try:
        TRAIN_PID.unlink()
    except OSError:
        pass
    return {"stopped": True}


class Handler(BaseHTTPRequestHandler):
    server_version = "1846Arena/1.0"
    def log_message(self, *_):
        pass

    def respond(self, payload, status=200):
        blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(blob)

    def do_GET(self):
        try:
            parts = urlsplit(self.path)
            path = parts.path
            query = parse_qs(parts.query)
            if path == "/api/runs":
                items = [read(p, {}) for p in RUNS.glob("*/summary.json")]
                for item in items:
                    if item.get("id") in LIVE:
                        item.update(LIVE[item["id"]]["summary"])
                return self.respond({"runs": sorted(items, key=lambda x: x.get("created", 0), reverse=True),
                                     "active": ACTIVE, "batch": BATCH})
            if path == "/api/state":
                run_id = query["id"][0]
                data = summary(run_id)
                with LOCK:
                    live = LIVE.get(run_id)
                    frame = ({k: live[k] for k in ("state", "board", "decision", "logs")} if live
                             else read(run_dir(run_id) / "latest.json", {}))
                    if live:
                        data = dict(live["summary"])
                return self.respond(dict(frame, summary=data))
            if path == "/api/frame":
                return self.respond(history_frame(query["id"][0], int(query["index"][0])))
            if path == "/api/train":
                return self.respond(train_snapshot())
            if path == "/api/models":
                return self.respond(local_model_report())
            if path == "/api/lmstudio":
                try:
                    with urllib.request.urlopen("http://127.0.0.1:1234/v1/models", timeout=3) as response:
                        models = json.load(response)
                    return self.respond({"available": True, "models": [m["id"] for m in models.get("data", [])
                                                                    if "embedding" not in m["id"].lower()]})
                except Exception:
                    return self.respond({"available": False, "models": []})
            if path == "/api/report":
                name = query.get("file", [""])[0]
                if not re.fullmatch(r"logic-\d+\.md", name):
                    raise ValueError("无效的报告名。")
                report = TRAIN_REPORTS / name
                if not report.is_file():
                    raise ValueError("报告尚未生成。")
                blob = report.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Length", str(len(blob)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(blob)
                return
            if path == "/api/download":
                folder = run_dir(query["id"][0])
                name = query.get("file", ["game.json"])[0]
                allowed = {"game.json", "transitions.jsonl", "outcome.json", "config.json", "对局日志.txt"}
                if name not in allowed or not (folder / name).is_file():
                    raise ValueError("该文件尚未生成。")
                blob = (folder / name).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", 'attachment; filename="' + ("game-log.txt" if name.endswith(".txt") else name) + '"')
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob)
                return
            files = {"/": ("web/index.html", "text/html"), "/app.js": ("web/app.js", "text/javascript"),
                     "/style.css": ("web/style.css", "text/css")}
            if path not in files:
                return self.respond({"error": "找不到此页面。"}, 404)
            filename, mime = files[path]
            blob = (ROOT / filename).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)
        except (ValueError, KeyError, FileNotFoundError) as exc:
            self.respond({"error": str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_POST(self):
        global BATCH
        try:
            # Bind locally and reject cross-origin mutations, including DNS rebinding.
            host = self.headers.get("Host", "")
            expected = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            origin = self.headers.get("Origin")
            if host not in expected or (origin and origin not in {"http://" + h for h in expected}):
                return self.respond({"error": "仅接受本机页面操作。"}, 403)
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16_384:
                raise ValueError("请求大小无效。")
            raw = json.loads(self.rfile.read(size))
            if self.path == "/api/start":
                return self.respond({"id": start_run(validate(raw))})
            if self.path == "/api/control":
                return self.respond(control(raw["id"], raw["action"]))
            if self.path == "/api/batch":
                config = validate(raw)
                count = int(raw.get("count", 3))
                if not 0 <= count <= 100:
                    raise ValueError("每批支持 0—100 局；0 表示一直连续运行。")
                if count and config["seed"] + count - 1 > 2_000_000_000:
                    raise ValueError("批次种子超出范围。")
                with LOCK:
                    if ACTIVE or BATCH["active"]:
                        raise ValueError("请先结束当前对局或批次。")
                    BATCH = {"active": True, "total": count, "index": 0, "runs": [],
                             "cancelled": False, "continuous": count == 0}
                    threading.Thread(target=batch_worker, args=(config, count), daemon=True).start()
                return self.respond(BATCH)
            if self.path == "/api/train":
                if raw.get("action") == "stop":
                    return self.respond(stop_training())
                return self.respond(start_training(raw))
            if self.path == "/api/analyze":
                return self.respond(run_analysis())
            if self.path == "/api/batch-stop":
                BATCH["cancelled"] = True
                if ACTIVE:
                    control(ACTIVE, "stop")
                return self.respond(BATCH)
            self.respond({"error": "不支持此操作。"}, 404)
        except (ValueError, KeyError, TypeError) as exc:
            self.respond({"error": str(exc)}, 400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=1846)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    # Opening the launcher twice should return to the existing arena.
    try:
        with urllib.request.urlopen(url + "/api/runs", timeout=1) as response:
            existing_arena = response.headers.get("Server", "").startswith("1846Arena/")
    except (urllib.error.URLError, OSError):
        existing_arena = False
    if existing_arena:
        print("1846 自战平台已经运行：" + url, flush=True)
        if not args.no_browser:
            import webbrowser
            webbrowser.open(url)
        return
    # A previous force quit must not leave a historical run marked as running.
    for path in RUNS.glob("*/summary.json"):
        data = read(path, {})
        if data.get("status") in ("running", "paused"):
            data.update(status="interrupted", error="上次服务退出时对局尚未结束；已有记录可以回放。")
            save(path, data)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("1846 自战平台已启动：" + url, flush=True)
    if not args.no_browser:
        import webbrowser
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        BATCH["cancelled"] = True
        if ACTIVE:
            control(ACTIVE, "stop")
        server.server_close()


if __name__ == "__main__":
    main()