"""A/B evaluation: same seeds, neural seat 1, fixed heuristic opponents."""
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUBY = ROOT / "runtime/rubyinstaller-3.4.9-1-x64/bin/ruby.exe"
OUT = ROOT / "train" / "ab_eval.json"


def run_game(seed, url):
    cfg = {"players": 4, "seed": seed,
           "strategies": ["neural", "balanced", "growth", "income"],
           "net_url": url, "net_weight": 15, "human_prior_weight": 20,
           "max_actions": 3000}
    path = ROOT / "train" / "data" / f"ab-{seed}.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    command = ('chcp 65001 >nul && "' + str(RUBY) + '" arena.rb "' + str(path) + '"')
    proc = subprocess.run(command, cwd=ROOT, shell=True, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=180)
    if proc.returncode != 0:
        return {"seed": seed, "error": (proc.stderr or proc.stdout)[-300:]}
    for line in reversed(proc.stdout.splitlines()):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") == "complete":
            result = {str(k): float(v) for k, v in event["state"]["result"].items()}
            return {"seed": seed, "result": result,
                    "winner": max(result, key=result.get)}
    return {"seed": seed, "error": "no complete event"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url-a", default="http://127.0.0.1:18347")
    parser.add_argument("--url-b", default="http://127.0.0.1:18348")
    parser.add_argument("--games", type=int, default=10)
    parser.add_argument("--seed", type=int, default=700000)
    args = parser.parse_args()
    rows = []
    for i in range(args.games):
        seed = args.seed + i
        a = run_game(seed, args.url_a)
        b = run_game(seed, args.url_b)
        rows.append({"seed": seed, "a": a, "b": b})
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    def stats(key):
        wins = top2 = 0
        scores = []
        for row in rows:
            data = row[key]
            if "result" not in data:
                continue
            result = data["result"]
            score = result.get("1", 0.0)
            scores.append(score)
            wins += 1 if score >= max(result.values()) else 0
            top2 += 1 if sorted(result.values(), reverse=True).index(score) < 2 else 0
        return {"games": len(scores), "wins": wins, "top2": top2,
                "avg_score": round(sum(scores) / max(1, len(scores)), 1)}
    summary = {"a": stats("a"), "b": stats("b"), "rows": rows}
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "out": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
