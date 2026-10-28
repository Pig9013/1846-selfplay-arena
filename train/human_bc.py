"""Behaviour cloning from human-seat games.

Human-seat JSONL (p1846/human_seat.rb) has the same state/action/chosen format
as self-play. This script trains the policy head to imitate those choices,
either from scratch or on top of the latest self-play checkpoint.

  python train/human_bc.py --data train/human_data --steps 300
  python train/human_bc.py --data train/human_data --base checkpoints/latest.pt --out checkpoints/human_bc.pt
"""
import argparse
import glob
import json
import random
from pathlib import Path

import torch
import torch.nn.functional as F

from net import ACTION_SIZE, PolicyValueNet
from trainer import load_games, make_dataset, pad_batch

ROOT = Path(__file__).resolve().parent
torch.set_num_threads(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(ROOT / "human_data"))
    parser.add_argument("--base", default=str(ROOT / "checkpoints" / "latest.pt"))
    parser.add_argument("--out", default=str(ROOT / "checkpoints" / "human_bc.pt"))
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--lr", type=float, default=3e-4)
    args = parser.parse_args()

    files = sorted(glob.glob(str(Path(args.data) / "*.jsonl")))
    if not files:
        raise SystemExit(f"no human JSONL under {args.data}")
    games = load_games(files)
    data = make_dataset(games, max_actions=12)
    if len(data) < 16:
        raise SystemExit(f"only {len(data)} human decisions; need more")
    model = PolicyValueNet()
    base = Path(args.base)
    if base.is_file():
        try:
            state = torch.load(base, map_location="cpu", weights_only=True)
            model.load_state_dict(state["model"])
            print(f"loaded base {base} step={state.get('step')}")
        except Exception as exc:  # noqa: BLE001
            print(f"base checkpoint not loaded: {exc}")
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    rng = random.Random(0)
    model.train()
    best = 0.0
    for step in range(args.steps):
        batch = rng.sample(data, min(args.batch, len(data)))
        states, actions, mask, chosen, prior, z, sample = pad_batch(batch)
        logits, values = model(states, actions)
        logits = logits.masked_fill(mask == 0, -1e9)
        # Pure imitation of the human choice; value head still learns the
        # outcome z so the checkpoint stays compatible with self-play.
        policy_loss = F.cross_entropy(logits, chosen)
        value_loss = F.mse_loss(values.gather(1, chosen[:, None]).squeeze(1), z)
        loss = policy_loss + 0.3 * value_loss
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        opt.step()
        if step % 25 == 0 or step == args.steps - 1:
            with torch.no_grad():
                pred = logits.argmax(dim=1)
                acc = float((pred == chosen).float().mean())
            best = max(best, acc)
            print(json.dumps({"step": step, "loss": round(float(loss.detach()), 4),
                              "policy": round(float(policy_loss.detach()), 4),
                              "top1": round(acc, 3), "n": len(data)}))
    model.eval()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"model": model.state_dict(), "step": args.steps, "human_bc": True}, out)
    print(json.dumps({"saved": str(out), "games": len(games), "decisions": len(data),
                      "best_batch_top1": round(best, 3)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
