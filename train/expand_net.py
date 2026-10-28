"""Widen the policy/value MLP without changing its initial function.

Net2Net-style: copy the old weights into the top-left block of the wider
matrices and leave the new capacity at zero. The widened model then trains on
the existing replay data, so it does not lose the current policy.
"""
import argparse
from pathlib import Path

import torch

from net import PolicyValueNet

ROOT = Path(__file__).resolve().parent


def expand(old_state, new_hidden, noise=0.0):
    old_hidden = int(old_state["state.0.weight"].shape[0])
    old = PolicyValueNet(hidden=old_hidden)
    old.load_state_dict(old_state)
    new = PolicyValueNet(hidden=new_hidden)
    # Start from zeroed tensors: the newly added hidden units must be exactly
    # zero, otherwise random extra rows change the function immediately.
    dst = {key: torch.zeros_like(value) for key, value in new.state_dict().items()}
    for key, value in old.state_dict().items():
        if key == "state.0.weight":
            dst[key][:old_hidden, :] = value
        elif key == "state.0.bias":
            dst[key][:old_hidden] = value
        elif key == "state.2.weight":
            dst[key][:old_hidden, :old_hidden] = value
        elif key == "state.2.bias":
            dst[key][:old_hidden] = value
        elif key == "head.0.weight":
            # head input is [state_hidden, action_features]; keep the action
            # block at the end of the widened input, not at old_hidden.
            dst[key][:, :old_hidden] = value[:, :old_hidden]
            dst[key][:, new_hidden:] = value[:, old_hidden:]
        else:
            dst[key] = value.clone()
    if noise > 0:
        generator = torch.Generator().manual_seed(12345)
        def fill(tensor, rows, cols):
            tensor[rows, cols] = torch.randn(tensor[rows, cols].shape, generator=generator) * noise
        fill(dst["state.0.weight"], slice(old_hidden, new_hidden), slice(None))
        dst["state.0.bias"][old_hidden:new_hidden] = torch.randn(
            new_hidden - old_hidden, generator=generator) * noise
        fill(dst["state.2.weight"], slice(old_hidden, new_hidden), slice(None))
        fill(dst["state.2.weight"], slice(0, old_hidden), slice(old_hidden, new_hidden))
        dst["state.2.bias"][old_hidden:new_hidden] = torch.randn(
            new_hidden - old_hidden, generator=generator) * noise
        fill(dst["head.0.weight"], slice(None), slice(old_hidden, new_hidden))
    new.load_state_dict(dst)
    return old, new


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default=str(ROOT / "checkpoints" / "latest.pt"))
    parser.add_argument("--hidden", type=int, default=512)
    parser.add_argument("--noise", type=float, default=0.0,
                        help="random init for newly added capacity; 0 keeps it dead")
    parser.add_argument("--out", default=str(ROOT / "checkpoints" / "latest.pt"))
    args = parser.parse_args()
    path = Path(args.checkpoint)
    state = torch.load(path, map_location="cpu", weights_only=True)
    old, new = expand(state["model"], args.hidden, args.noise)
    old.eval()
    new.eval()
    with torch.no_grad():
        s = torch.randn(4, 128)
        a = torch.randn(4, 9, 48)
        old_policy, old_value = old(s, a)
        new_policy, new_value = new(s, a)
        diff = float((old_policy - new_policy).abs().max())
        vdiff = float((old_value - new_value).abs().max())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    torch.save({"model": new.state_dict(), "step": int(state.get("step", 0)),
                "hidden": args.hidden, "expanded_from": int(old.hidden)}, tmp)
    tmp.replace(out)
    print({"old_hidden": old.hidden, "new_hidden": args.hidden,
           "step": state.get("step"), "policy_diff": diff, "value_diff": vdiff,
           "saved": str(out)})


if __name__ == "__main__":
    main()
