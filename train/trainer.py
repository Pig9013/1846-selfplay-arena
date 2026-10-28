"""Training for the 1846 policy/value net.

Samples come from p1846/selfplay.rb: one JSONL per game with decision rows
(state, action features, chosen index, heuristic priors) and the final z-scores.
"""
import glob
import json
import math
import random
import time
from pathlib import Path

import torch
import torch.nn.functional as F

from net import ACTION_SIZE, STATE_SIZE, PolicyValueNet

ROOT = Path(__file__).resolve().parent
torch.set_num_threads(2)


def list_samples(data_dir):
    return sorted(glob.glob(str(Path(data_dir) / "*.jsonl")))


def load_games(files):
    games = []
    for path in files:
        decisions = []
        result = None
        meta = {}
        try:
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line)
                    kind = row.get("type")
                    if kind == "decision":
                        decisions.append(row)
                    elif kind == "result":
                        result = row
                    elif kind == "meta":
                        meta = row
        except (OSError, json.JSONDecodeError):
            continue
        # Old checkpoints/samples used a 40-wide action vector whose first 14
        # "type" bits were always zero (the arena never attached candidate
        # type). Those samples teach the net to ignore action type, so they are
        # not reusable. Degenerate pass-only games are discarded for the same
        # reason.
        if meta.get("degenerate") or meta.get("feature_version", 0) < 2:
            continue
        if meta.get("low_quality") or meta.get("end_reason") == "bankrupt":
            continue
        if not decisions or not result:
            continue
        for decision in decisions:
            actions = decision.get("actions") or []
            for i, action in enumerate(actions):
                if len(action) < ACTION_SIZE:
                    actions[i] = action + [0.0] * (ACTION_SIZE - len(action))
                elif len(action) > ACTION_SIZE:
                    actions[i] = action[:ACTION_SIZE]
            state = decision.get("state") or []
            decision["state"] = (state + [0.0] * STATE_SIZE)[:STATE_SIZE]
        scores = result.get("scores") or {}
        ranked = sorted(scores.items(), key=lambda item: -float(item[1]))
        winner = result.get("winner") or (ranked[0][0] if ranked else None)
        margin = result.get("margin")
        if margin is None and len(ranked) > 1:
            margin = float(ranked[0][1]) - float(ranked[1][1])
        winner_weight = result.get("winner_weight")
        if winner_weight is None:
            winner_weight = 1 + max(0, min(int((float(margin or 0) // 500)), 20))
        games.append({"decisions": decisions, "z": result["z"], "scores": scores,
                      "winner": winner, "margin": margin, "winner_weight": int(winner_weight),
                      "meta": meta})
    return games


def make_dataset(games, max_actions=12):
    data = []
    for game in games:
        zmap = game["z"]
        winner = str(game.get("winner"))
        winner_weight = int(game.get("winner_weight", 1))
        for d in game["decisions"]:
            actor = d.get("actor")
            if actor is None or actor not in zmap:
                continue
            # Learn mostly from the winner; the margin to second place controls
            # how strongly. Losers keep a small 0.15 weight for negative signal.
            sample_weight = winner_weight if str(actor) == winner else 0.15
            actions = d["actions"][:max_actions]
            if len(actions) < 2:
                continue
            chosen = d["chosen"]
            if chosen >= len(actions):
                chosen = 0
            prior = (d.get("prior") or [0.0] * len(actions))[:len(actions)]
            data.append({
                "state": d["state"],
                "actions": actions,
                "chosen": chosen,
                "prior": prior,
                "z": float(zmap[actor]),
                "weight": float(sample_weight),
            })
    return data


def pad_batch(batch, max_actions=12):
    n = max(len(b["actions"]) for b in batch)
    states, actions, mask, chosen, prior, z, sample = [], [], [], [], [], [], []
    for b in batch:
        a = b["actions"]
        pad = n - len(a)
        actions.append(a + [[0.0] * ACTION_SIZE for _ in range(pad)])
        mask.append([1.0] * len(a) + [0.0] * pad)
        states.append(b["state"])
        chosen.append(b["chosen"])
        p = b["prior"] + [0.0] * pad
        prior.append(p)
        z.append(b["z"])
        sample.append(b.get("weight", 1.0))
    return (torch.tensor(states, dtype=torch.float32), torch.tensor(actions, dtype=torch.float32),
            torch.tensor(mask, dtype=torch.float32), torch.tensor(chosen, dtype=torch.long),
            torch.tensor(prior, dtype=torch.float32), torch.tensor(z, dtype=torch.float32),
            torch.tensor(sample, dtype=torch.float32))


def train_once(model, data, steps=120, batch_size=128, lr=4e-4, temperature=18.0, seed=0):
    if len(data) < 64:
        return None
    rng = random.Random(seed)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    model.train()
    stats = {"loss": 0.0, "policy": 0.0, "value": 0.0, "n": 0}
    for _ in range(steps):
        batch = rng.sample(data, min(batch_size, len(data)))
        states, actions, mask, chosen, prior, z, sample = pad_batch(batch)
        logits, values = model(states, actions)
        logits = logits.masked_fill(mask == 0, -1e9)
        logp = F.log_softmax(logits, dim=1)
        chosen_logp = logp.gather(1, chosen[:, None]).squeeze(1).clamp(min=-8.0)
        # Advantage-weighted imitation: actions taken in better outcomes get
        # up-weighted (bounded), so the loss cannot explode the way plain
        # REINFORCE does when the policy moves off a sampled action.
        sample = (sample / sample.mean().clamp_min(1e-6)).clamp(max=20.0)
        weights = torch.exp(z.clamp(-2.0, 2.0)) * sample
        weights = weights / weights.mean().clamp_min(1e-6)
        advantage = -(weights * chosen_logp).mean()
        # Padded candidates must never receive target mass: their prior is 0
        # while real candidates may be negative.
        target = F.softmax(prior.masked_fill(mask == 0, -1e9) / temperature, dim=1)
        imitation = -((target * logp).sum(dim=1) * sample).mean()
        value_loss = (sample * (values.gather(1, chosen[:, None]).squeeze(1) - z) ** 2).mean() / sample.mean().clamp_min(1e-6)
        entropy = -((logp.exp() * logp).sum(dim=1)).mean()
        loss = 0.5 * advantage + 0.35 * imitation + 0.5 * value_loss - 0.02 * entropy
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        opt.step()
        stats["loss"] += float(loss.detach())
        stats["policy"] += float((0.5 * advantage + 0.35 * imitation).detach())
        stats["value"] += float(value_loss.detach())
        stats["n"] += 1
    model.eval()
    for key in ("loss", "policy", "value"):
        stats[key] /= max(stats["n"], 1)
    return stats


def save_checkpoint(model, step, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    torch.save({"model": model.state_dict(), "step": step}, tmp)
    tmp.replace(path)
