"""Policy/value network for 1846. Small MLP; CPU inference is enough."""
import torch
import torch.nn as nn

STATE_SIZE = 128
ACTION_SIZE = 48


class PolicyValueNet(nn.Module):
    def __init__(self, hidden=192):
        super().__init__()
        self.hidden = int(hidden)
        self.state = nn.Sequential(nn.Linear(STATE_SIZE, hidden), nn.ReLU(),
                                   nn.Linear(hidden, hidden), nn.ReLU())
        self.act = nn.Sequential(nn.Linear(ACTION_SIZE, 64), nn.ReLU())
        self.head = nn.Sequential(nn.Linear(hidden + 64, 128), nn.ReLU())
        self.policy = nn.Linear(128, 1)
        self.value = nn.Linear(128, 1)

    def forward(self, state, actions):
        # state: [B, S]  actions: [B, N, A]  -> policy [B, N], value [B, N]
        h = self.state(state)
        b, n, _ = actions.shape
        h = h[:, None, :].expand(b, n, h.shape[-1])
        a = self.act(actions)
        z = self.head(torch.cat([h, a], dim=-1))
        return self.policy(z).squeeze(-1), torch.tanh(self.value(z).squeeze(-1))
