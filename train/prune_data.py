"""Prune old self-play games while keeping recent, useful samples.

The trainer only reads the newest N files. Keeping tens of thousands of old
JSONL/game pairs wastes disk and RAM; the replay buffer is bounded anyway.
"""
import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "train" / "data"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", type=int, default=700)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    files = sorted(DATA.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    keep = set(files[:args.keep])
    delete = [p for p in files if p not in keep]
    pairs = []
    size = 0
    for path in delete:
        game = path.with_suffix(".game.json")
        pairs.append(path)
        if game.exists():
            pairs.append(game)
        size += path.stat().st_size + (game.stat().st_size if game.exists() else 0)
    print(json.dumps({"jsonl_total": len(files), "keep": len(keep), "delete_games": len(delete),
                      "delete_files": len(pairs), "delete_gb": round(size / 1e9, 3),
                      "apply": args.apply}))
    if args.apply:
        for path in pairs:
            try:
                path.unlink()
            except OSError as exc:
                print(f"skip {path}: {exc}")
        print(json.dumps({"remaining_jsonl": len(list(DATA.glob('*.jsonl')))}))


if __name__ == "__main__":
    main()
