"""Self-play + training orchestrator (KataGo-lite for 1846).

Runs N single-threaded Ruby self-play workers plus one neural inference server,
trains from the produced samples, and watches its own CPU footprint so the
machine stays responsive for other work.

Continuous mode is the default: workers keep producing games until the process
is stopped.  A finite run is still available with --minutes or --games.

  python train/orchestrate.py --workers 6                 # run forever
  python train/orchestrate.py --workers 6 --minutes 60    # stop after 60 min
  python train/orchestrate.py --workers 4 --games 200     # stop after 200
"""
import argparse
import json
import os
import random
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
GAMES_LOG = TRAIN / "games.jsonl"
REPORTS = TRAIN / "reports"
RUBY = ROOT / "runtime/rubyinstaller-3.4.9-1-x64/bin/ruby.exe"
NET_PORT = 18346
NET_URL = f"http://127.0.0.1:{NET_PORT}/scores"
BELOW_NORMAL = 0x00004000
STATE = {
    "games": 0, "attempts": 0, "decisions": 0, "train_steps": 0, "loss": None,
    "winrate": None, "workers": 0, "started": time.time(), "eval_games": 0,
    "eval_wins": 0, "stopped": False, "degenerate": 0, "errors": 0,
    "continuous": False, "rate": 0.0, "elapsed": 0.0, "last_report": 0,
    "checkpoint_step": 0, "dataset": 0, "net_url": NET_URL,
}
LOCK = threading.Lock()
STOP = threading.Event()
GAME_INDEX = {"next": 0}


def next_game_index():
    with LOCK:
        game = GAME_INDEX["next"]
        GAME_INDEX["next"] += 1
    return game


def ruby_cmd(script, cfg_path):
    command = f'chcp 65001 >nul && "{RUBY}" {script} "{cfg_path}"'
    # A single string keeps Windows from re-quoting the Chinese path segments.
    return 'cmd.exe /d /s /c "' + command + '"'


def kill_tree(pid):
    if pid is None:
        return
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def write_status():
    with LOCK:
        data = dict(STATE)
    elapsed = max(time.time() - data["started"], 1e-6)
    data["elapsed"] = round(elapsed, 1)
    data["rate"] = round(data["games"] / (elapsed / 60.0), 2)
    data["updated"] = time.time()
    tmp = STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    try:
        tmp.replace(STATUS)
    except OSError:
        pass


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


def monitor_net_server(proc_ref, stop_event):
    while not stop_event.is_set():
        proc = proc_ref[0]
        if proc.poll() is not None:
            with LOCK:
                STATE["errors"] += 1
            time.sleep(1.0)
            if not stop_event.is_set():
                proc_ref[0] = start_net_server()
        stop_event.wait(3.0)


def run_game(cfg_path, timeout=900):
    proc = subprocess.Popen(ruby_cmd("p1846/selfplay.rb", cfg_path), cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", creationflags=BELOW_NORMAL)
    deadline = time.time() + timeout
    while proc.poll() is None:
        if STOP.is_set() or time.time() > deadline:
            kill_tree(proc.pid)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            return None
        time.sleep(0.25)
    out, err = proc.communicate()
    return proc.returncode, out or "", err or ""


# The two focused personas are intentionally rarer (0.5 vs 1) so they add
# pressure without taking over the self-play distribution.
STRATEGY_POOL = [("neural", 5.0), ("balanced", 1.0), ("growth", 1.0),
                 ("income", 1.0), ("random", 1.0),
                 ("chicago_connector", 0.5), ("zone_connector", 0.5)]


def make_strategies(players, seed, mode="mixed"):
    if mode == "neural":
        return ["neural"] * players
    rng = random.Random(seed)
    names = [name for name, _ in STRATEGY_POOL]
    weights = [weight for _, weight in STRATEGY_POOL]
    return rng.choices(names, weights=weights, k=players)


def worker(index, seed_base, players, temperature, net_weight, human_prior_weight,
           strategy_mode, stop_event):
    consecutive_failures = 0
    while not stop_event.is_set():
        with LOCK:
            if not STATE["continuous"] and STATE["attempts"] >= STATE.get("game_limit", 10**12):
                return
        # A global counter prevents two workers from writing the same
        # seed-game filename (the old per-worker counter overlapped).
        game = next_game_index()
        seed = (seed_base + game) % 2_000_000_000
        cfg = {
            "players": players,
            "seed": seed,
            "game": game,
            "strategies": make_strategies(players, seed, strategy_mode),
            "net_url": NET_URL,
            "net_weight": net_weight,
            "human_prior_weight": human_prior_weight,
            "temperature": temperature,
            "out": str(DATA),
            "max_actions": 3000,
        }
        cfg_path = DATA / f"cfg-{index}.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        started = time.time()
        result = run_game(cfg_path)
        elapsed = time.time() - started
        info = None
        error = None
        if result is None:
            error = "stopped"
        else:
            code, out, err = result
            lines = [line for line in out.splitlines() if line.strip()]
            if code == 0 and lines:
                try:
                    info = json.loads(lines[-1])
                except ValueError:
                    error = "unparseable self-play output"
            else:
                error = (err or out)[-400:]
        ok = bool(info and info.get("decisions", 0) > 0 and not info.get("degenerate"))
        record = {
            "game": game,
            "seed": seed,
            "decisions": (info or {}).get("decisions", 0),
            "non_pass": (info or {}).get("non_pass", 0),
            "degenerate": bool((info or {}).get("degenerate")),
            "elapsed": round(elapsed, 1),
            "scores": (info or {}).get("scores"),
            "end": (info or {}).get("end_reason"),
            "error": None if ok else (error or "degenerate pass-only game"),
            "time": time.time(),
        }
        with LOCK:
            STATE["attempts"] += 1
            STATE["decisions"] += record["decisions"]
            if record["degenerate"]:
                STATE["degenerate"] += 1
            if ok:
                STATE["games"] += 1
            else:
                STATE["errors"] += 1
        with GAMES_LOG.open("a", encoding="utf-8") as log:
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
        if ok:
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                time.sleep(2.0)
                consecutive_failures = 0
        game += 1


def prune_buffer(keep=4000):
    files = list_samples(DATA)
    if len(files) <= keep:
        return
    for path in files[:-keep]:
        try:
            os.remove(path)
            os.remove(path.replace(".jsonl", ".game.json"))
        except OSError:
            pass


def load_model():
    model = PolicyValueNet()
    step = 0
    if CKPT.exists():
        try:
            state = torch.load(CKPT, map_location="cpu", weights_only=True)
            model.load_state_dict(state["model"])
            step = int(state.get("step", 0))
        except Exception:  # noqa: BLE001 - old 40-wide checkpoint is not loadable
            model = PolicyValueNet()
            step = 0
    with LOCK:
        STATE["checkpoint_step"] = step
    return model, step


def training_loop(stop_event, every=6, steps=120, buffer=1200, min_new=2, keep=4000):
    model, step = load_model()
    last_count = 0
    while not stop_event.is_set():
        files = list_samples(DATA)
        # Only train when there is new data.  When pruning removes old files the
        # count can fall; treat that as a reset rather than a negative delta.
        if len(files) < last_count:
            last_count = 0
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
                        STATE["checkpoint_step"] = step
                        STATE["device"] = stats.get("device", "cpu")
                    with LOG.open("a", encoding="utf-8") as log:
                        log.write(json.dumps({"step": step, "games": len(games), "samples": len(data),
                                              **{k: (round(v, 4) if isinstance(v, (int, float)) else v)
                                                 for k, v in stats.items()},
                                              "time": time.time()}) + "\n")
            prune_buffer(keep)
        stop_event.wait(every)


def evaluate(stop_event, players=4, games=2, net_weight=15):
    for i in range(games):
        if stop_event.is_set():
            break
        cfg = {"players": players, "seed": 900000 + int(time.time()) % 1000 + i,
               "strategies": ["neural"] + ["balanced", "growth", "income"][:players - 1],
               "net_url": NET_URL, "net_weight": net_weight, "max_actions": 3000}
        path = DATA / "eval.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        proc = subprocess.run(ruby_cmd("arena.rb", path), cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", creationflags=BELOW_NORMAL,
                              timeout=900)
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
        except (ValueError, KeyError, IndexError, subprocess.SubprocessError):
            pass


def report_once(label):
    try:
        REPORTS.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, str(TRAIN / "analyze.py"), "--data", str(DATA),
                        "--out", str(REPORTS), "--label", str(label)],
                       cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=BELOW_NORMAL, timeout=300)
        with LOCK:
            STATE["last_report"] = label
    except (OSError, subprocess.SubprocessError):
        pass


def report_loop(stop_event, every=1000):
    last = 0
    while not stop_event.is_set():
        with LOCK:
            games = STATE["games"]
        if every and games - last >= every:
            last = games
            report_once(games)
        stop_event.wait(15)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=max(1, min(6, (os.cpu_count() or 4) // 2)))
    parser.add_argument("--games", type=int, default=0, help="0 = unlimited")
    parser.add_argument("--minutes", type=float, default=0, help="0 = unlimited")
    parser.add_argument("--players", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--temperature", type=float, default=1.5)
    parser.add_argument("--net-weight", type=float, default=15)
    parser.add_argument("--human-prior-weight", type=float, default=10)
    parser.add_argument("--strategy-mode", choices=["mixed", "neural"], default="mixed")
    parser.add_argument("--train-every", type=int, default=6)
    parser.add_argument("--steps", type=int, default=120)
    parser.add_argument("--eval-every", type=int, default=300)
    parser.add_argument("--report-every", type=int, default=1000)
    parser.add_argument("--keep", type=int, default=4000)
    parser.add_argument("--buffer", type=int, default=1200)
    parser.add_argument("--continuous", action="store_true", help="run until stopped")
    args = parser.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    TRAIN.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    ensure_checkpoint()
    (TRAIN / "run.pid").write_text(str(os.getpid()), encoding="utf-8")
    server = start_net_server()
    server_ref = [server]
    threading.Thread(target=monitor_net_server, args=(server_ref, STOP), daemon=True).start()

    continuous = args.continuous or (args.games <= 0 and args.minutes <= 0)
    with LOCK:
        STATE["continuous"] = continuous
        STATE["workers"] = args.workers
        STATE["net_url"] = NET_URL
        STATE["human_prior_weight"] = args.human_prior_weight
        STATE["strategy_mode"] = args.strategy_mode
        STATE["game_limit"] = args.games if args.games > 0 else 10**12

    threads = [threading.Thread(target=worker,
                                args=(i, args.seed, args.players, args.temperature,
                                      args.net_weight, args.human_prior_weight,
                                      args.strategy_mode, STOP), daemon=True)
               for i in range(args.workers)]
    for thread in threads:
        thread.start()
    threading.Thread(target=training_loop,
                     args=(STOP, args.train_every, args.steps, args.buffer,
                           max(2, args.workers // 2), args.keep), daemon=True).start()
    if args.report_every:
        threading.Thread(target=report_loop, args=(STOP, args.report_every), daemon=True).start()

    deadline = time.time() + args.minutes * 60 if args.minutes else None
    last_eval = 0
    try:
        while any(t.is_alive() for t in threads):
            if deadline and time.time() > deadline:
                STOP.set()
                break
            if args.eval_every:
                with LOCK:
                    games = STATE["games"]
                if games - last_eval >= args.eval_every:
                    last_eval = games
                    evaluate(STOP, args.players, 2, args.net_weight)
            write_status()
            time.sleep(2)
    except KeyboardInterrupt:
        STOP.set()
    finally:
        STOP.set()
        time.sleep(1)
        kill_tree(server.pid)
        write_status()
        with LOCK:
            summary = {"games": STATE["games"], "attempts": STATE["attempts"],
                       "decisions": STATE["decisions"], "degenerate": STATE["degenerate"],
                       "errors": STATE["errors"], "train_steps": STATE["train_steps"],
                       "loss": STATE["loss"], "winrate": STATE.get("winrate"),
                       "elapsed": round(time.time() - STATE["started"], 1),
                       "continuous": continuous, "workers": args.workers}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        (TRAIN / "last-run.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
        if args.report_every:
            report_once(STATE["games"])
        try:
            (TRAIN / "run.pid").unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
