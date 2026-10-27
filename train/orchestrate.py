"""Self-play + training orchestrator (KataGo-lite for 1846).

Runs N single-threaded Ruby self-play workers plus one neural inference server,
trains from the produced samples, and watches its own CPU footprint so the
machine stays responsive for other work.

  python train/orchestrate.py --workers 6 --games 200
  python train/orchestrate.py --workers 4 --minutes 60 --eval-every 40
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import torch

from net import PolicyValueNet
from trainer import list_samples, load_games, make_dataset, save_checkpoint, train_once

ROOT = Path(__file__).resolve().parent.parent
TRAIN = ROOT / "train"
DATA = TRAIN / "data"
CKPT = TRAIN / "checkpoints" / "latest.pt"
STATUS = TRAIN / "status.json"
LOG = TRAIN / "log.jsonl"
RUBY = ROOT / "runtime/rubyinstaller-3.4.9-1-x64/bin/ruby.exe"
NET_PORT = 18346
NET_URL = f"http://127.0.0.1:{NET_PORT}/scores"
BELOW_NORMAL = 0x00004000
STATE = {"games": 0, "decisions": 0, "train_steps": 0, "loss": None, "winrate": None,
         "workers": 0, "started": time.time(), "eval_games": 0, "eval_wins": 0,
         "stopped": False}
LOCK = threading.Lock()


def ruby_cmd(script, cfg_path, out=None):
    command = f'chcp 65001 >nul && "{RUBY}" {script} "{cfg_path}"'
    if out:
        command += f' > "{out}" 2> "{out}.err"'
    # A single string keeps Windows from re-quoting the Chinese path segments.
    return 'cmd.exe /d /s /c "' + command + '"'


def write_status():
    with LOCK:
        data = dict(STATE)
    data["updated"] = time.time()
    tmp = STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATUS)


def start_net_server():
    proc = subprocess.Popen([sys.executable, "-u", str(TRAIN / "nnserver.py"), str(NET_PORT)],
                            cwd=TRAIN, creationflags=BELOW_NORMAL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.2)
    return proc


def ensure_checkpoint():
    if CKPT.exists():
        return
    CKPT.parent.mkdir(parents=True, exist_ok=True)
    save_checkpoint(PolicyValueNet(), 0, CKPT)


def worker(index, games, seed_base, players, temperature, stop_event, results):
    game = index
    while not stop_event.is_set() and game < games:
        cfg = {
            "players": players,
            "seed": seed_base + game,
            "game": game,
            "strategies": ["neural"] * players,
            "net_url": NET_URL,
            "net_weight": 60,
            "temperature": temperature,
            "out": str(DATA),
            "max_actions": 3000,
        }
        cfg_path = DATA / f"cfg-{index}.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        started = time.time()
        proc = subprocess.run(ruby_cmd("p1846/selfplay.rb", cfg_path), cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              creationflags=BELOW_NORMAL)
        elapsed = time.time() - started
        ok = proc.returncode == 0
        decisions = 0
        if ok:
            try:
                info = json.loads(proc.stdout.strip().splitlines()[-1])
                decisions = info.get("decisions", 0)
                results.append({"game": game, "decisions": decisions, "elapsed": round(elapsed, 1),
                                "scores": info.get("scores"), "end": info.get("end_reason")})
            except (ValueError, IndexError):
                ok = False
        if not ok:
            results.append({"game": game, "error": (proc.stderr or proc.stdout)[-400:], "elapsed": round(elapsed, 1)})
        with LOCK:
            STATE["games"] += 1
            STATE["decisions"] += decisions
        game += 1


def prune_buffer(keep=1200):
    files = list_samples(DATA)
    if len(files) <= keep:
        return
    for path in files[:-keep]:
        try:
            os.remove(path)
            os.remove(path.replace(".jsonl", ".game.json"))
        except OSError:
            pass


def training_loop(stop_event, every=6, steps=120, buffer=800, min_new=2):
    model = PolicyValueNet()
    step = 0
    if CKPT.exists():
        try:
            state = torch.load(CKPT, map_location="cpu", weights_only=True)
            model.load_state_dict(state["model"])
            step = int(state.get("step", 0))
        except Exception:  # noqa: BLE001
            pass
    last_count = 0
    while not stop_event.is_set():
        files = list_samples(DATA)
        if len(files) - last_count >= min_new:
            last_count = len(files)
            games = load_games(files[-buffer:])
            data = make_dataset(games)
            if len(data) >= 64:
                stats = train_once(model, data, steps=steps, seed=step)
                step += 1
                if stats:
                    save_checkpoint(model, step, CKPT)
                    with LOCK:
                        STATE["train_steps"] = step
                        STATE["loss"] = round(stats["loss"], 4)
                        STATE["dataset"] = len(data)
                    with LOG.open("a", encoding="utf-8") as log:
                        log.write(json.dumps({"step": step, "games": len(games), "samples": len(data),
                                              **{k: round(v, 4) for k, v in stats.items()},
                                              "time": time.time()}) + "\n")
            prune_buffer()
        stop_event.wait(every)


def evaluate(stop_event, players=4, games=2):
    write_status()
    for i in range(games):
        if stop_event.is_set():
            break
        cfg = {"players": players, "seed": 900000 + int(time.time()) % 1000 + i,
               "strategies": ["neural"] + ["balanced", "growth", "income"][:players - 1],
               "net_url": NET_URL, "net_weight": 60, "max_actions": 3000}
        path = DATA / "eval.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        proc = subprocess.run(ruby_cmd("arena.rb", path), cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", creationflags=BELOW_NORMAL)
        try:
            lines = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
            done = [e for e in lines if e.get("event") == "complete"]
            if done:
                result = done[-1]["state"]["result"]
                best = max(result.values())
                won = abs(result.get("1", -1) - best) < 1e-9
                with LOCK:
                    STATE["eval_games"] = STATE.get("eval_games", 0) + 1
                    STATE["eval_wins"] = STATE.get("eval_wins", 0) + (1 if won else 0)
                    STATE["winrate"] = round(STATE["eval_wins"] / STATE["eval_games"], 3)
        except (ValueError, KeyError, IndexError):
            pass
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) // 2 - 1))
    parser.add_argument("--games", type=int, default=200)
    parser.add_argument("--minutes", type=float, default=0)
    parser.add_argument("--players", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--temperature", type=float, default=18.0)
    parser.add_argument("--train-every", type=int, default=6)
    parser.add_argument("--steps", type=int, default=120)
    parser.add_argument("--eval-every", type=int, default=0)
    args = parser.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    ensure_checkpoint()
    server = start_net_server()
    stop = threading.Event()
    results = []
    threads = [threading.Thread(target=worker, args=(i, args.games, args.seed, args.players,
                                                     args.temperature, stop, results), daemon=True)
               for i in range(args.workers)]
    for thread in threads:
        thread.start()
    train_thread = threading.Thread(target=training_loop, args=(stop, args.train_every, args.steps),
                                    daemon=True)
    train_thread.start()
    with LOCK:
        STATE["workers"] = args.workers
    deadline = time.time() + args.minutes * 60 if args.minutes else None
    last_eval = 0
    try:
        while any(t.is_alive() for t in threads):
            if deadline and time.time() > deadline:
                stop.set()
                break
            if args.eval_every and STATE["games"] - last_eval >= args.eval_every:
                last_eval = STATE["games"]
                evaluate(stop)
            write_status()
            time.sleep(2)
    except KeyboardInterrupt:
        stop.set()
    finally:
        stop.set()
        time.sleep(1)
        server.terminate()
        write_status()
        summary = {"games": STATE["games"], "decisions": STATE["decisions"],
                   "train_steps": STATE["train_steps"], "loss": STATE["loss"],
                   "winrate": STATE.get("winrate"), "recent": results[-8:]}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        (TRAIN / "last-run.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
