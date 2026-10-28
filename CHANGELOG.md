# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and the
project uses [Semantic Versioning](https://semver.org/).

## [1.3.0] - 2026-10-28

Revenue-first tile scoring, margin-weighted winner learning, and route/equity diagnostics.

### Changed

- Track scoring no longer gives a large flat bonus for touching an off-board, nor
  a heavy penalty for an intermediate tile on a long E/W line. A tile is scored
  by current-turn revenue (city + off-board), next-turn revenue potential
  (through-edges / connected edges), upgrade value and cost.
- Off-board link bonus reduced to +10; intermediate off-board-facing tile
  penalty reduced to −8; E/W completion bonus reduced to +4.
- Route search budget raised to 48 routes / 1.6 s; train preference now weights
  distance 5 instead of 3.
- Training reward: the winner is the primary learning target; every $500 of
  margin over second place adds one weight unit (cap 20). Losers keep a small
  0.15 weight.
- Bankrupt or very short games (<200 non-pass actions) are excluded from
  training as low-quality operational examples.
- Reports now include route stops by train vs human baseline, holdings per
  player (cross-holding), and winner margin/learning weight.

### Validation

- Route stops: 4-train 3.18 vs human 3.84; 5-train 4.53 vs 4.87;
  6-train 5.18 vs 5.73 in the first 15-game sample.
- Average winner margin $828 → average winner weight 2.27 (max 7).
- Cross-holding: average 2.45 corps per invested player; 81.8% hold ≥2,
  47.7% hold ≥3.

## [1.2.0] - 2026-10-28

Human-play prior and removal of the hard-coded Chicago rule.

### Added

- **Human corpus prior** (`train/human_playbook.py`): reads 665 parsed
  3–5 player 1846 games from 18xx.games and writes
  `train/human_playbook.md` (Chinese summary of opening, track, trains,
  dividends and strategic themes) and `train/human_prior.json` (normalized
  frequency tables for phase/hex/tile, par prices, private prices, train and
  dividend choices).
- `p1846/human_prior.rb`: a small, configurable soft prior
  (`--human-prior-weight`, default 10, 0 disables) used by the heuristic.
  It is data-derived, not a rule; the neural policy can override it.
- Generic **E/W completion** bonus: when a company already reaches one side,
  joining the other side is rewarded (+55); the first side gets +14, and
  approaching the missing side gets +2 per hex. No Chicago special case.

### Changed

- Removed the hard-coded Chicago bonuses from the heuristic (D6
  +30/+55/+90/+125, C5 +40, Chicago token +58, home-distance-to-Chicago).
  Chicago now appears only through generic revenue/connectivity and the human
  frequency prior.
- README, usage guide and UI wording now distinguish the local neural
  checkpoint from optional LM Studio.

### Validation

- Human corpus: 665 games, 4p 461 / 5p 142 / 3p 62.
  D6 upgraded in 99.4% of games (green 99.4%, brown 97.7%, grey 86.6%);
  all three Z cities in 94.1%; E/W in 98.8%; C5 in 99.4%.
- The human prior files are generated from those games, not hand-written.

### Current status (2026-10-28 14:58)

- Latest analysis: `train/reports/logic-0318.md`, 316 usable games,
  182,549 decisions, 0 degenerate games.
- 96.8% green Chicago, 93.7% all three Z cities, 89.9% at least one C5,
  35.8% E/W, 8.9% bankruptcy.
- Top-1 acceptance 55.6%, mean rank 1.64, 93.5 track lays per game,
  4,151 offboard connections and 0 “pointed at offboard but did not connect”.
- Live training counter at the same time: 320 games, 95 train steps,
  combined policy/value loss 1.4767, 0 degenerate games, 4 worker errors
  retried.
- Neural evaluation: only 2 games, 0 wins. This is not yet a meaningful
  win-rate measurement; the report labels it 0% but the sample is tiny.

### Known gaps (measured)

- **E/W 35.8% vs 98.8% in 665 human games** — the largest behavioural gap.
  The cause is company-level route planning, not a missing global bonus:
  in a typical game IC runs only W while GT/ERIE/NYC/PRR/B&O run only E.
- Chicago 96.8% is close to the human 99.4% but the report still flags >90%
  as possibly over-concentrated; check whether it crowds out other offboards.
- Mean 93.5 lays per game; the player who lays most averages rank 2.60,
  worse than the 4-player random 2.50. The “lay if possible” tendency remains.
- Bankruptcy 8.9% is above the human level; train-rush cash, emergency
  issuance and dividend policy still need work.

## [1.1.0] - 2026-10-28

Continuous self-play, action-type/feature repair, and a Chicago/off-board-aware policy.

### Added

- **Continuous self-play**: `train/orchestrate.py` runs until stopped (the default);
  `--minutes 0` / no limit, `--report-every 1000`, per-game log in
  `train/games.jsonl`, unique global game indices across workers. The web
  training panel now starts continuous mode by default (6 workers, 0 minutes).
- **Local model report** (`GET /api/models`): detects the project's neural
  checkpoint + inference server and optional LM Studio / Ollama / llama.cpp /
  vLLM / text-generation-webui endpoints. The web panel explains which model is
  actually driving self-play.
- **Neural seats** in the web UI (`neural` strategy); they use the local
  checkpoint and need no external model.
- **Per-1000-game analysis** (`train/analyze.py` → `train/reports/logic-N.md`):
  action mix, decision-rank/entropy, track and off-board stats, Chicago/C5
  rates, winner correlations, self-correction notes, and a next-block fix list.
  Generated automatically by the orchestrator; also available from the web.
- Connectivity analysis (`p1846/connectivity.rb`): rotation-aware edge
  connectivity, off-board links, through-edges, upgrade revenue gain, Chicago
  distance/gateway.

### Changed

- Tile scoring now depends on the **rotated** tile: joining an off-board is
  rewarded (+42 + 0.6 × revenue), pointing at an off-board without joining it
  is punished (−30). Chicago D6 upgrades get explicit green/brown/grey bonuses
  and the C5 link bonus. **These Chicago-specific weights were removed again
  in 1.2.0**; 1.1 is an intermediate release.
- Heuristic weights: C&WI 38, MS 44; Chicago token +58; reserved/teleport
  token candidates are generated for company-owned abilities.
- Track-laying base score cut from 10 to 2 with a higher cost charge and a
  dead-end stub penalty, so "pass and keep the treasury" is a real option.
- Train-rust reserve: in phases III/IV a company holding a 2/4 train reserves
  the next train price before spending on track, reducing forced bankruptcies.
- Neural policy scores are normalised per decision (mean 0, std 1, clamp ±3)
  and added at weight 15 instead of raw logits × 60; self-play uses
  σ-scaled softmax with 5% uniform exploration.
- Feature version 2: action vectors are 48-wide and the 14 action-type bits are
  no longer all zero; six previously padded hex features now carry off-board
  link, off-board edges, Chicago gateway, upgrade gain, through-edges and
  Chicago distance. State features add Chicago/C5 facts.
- The arena batch supports `count=0` (run continuously) and the training
  launcher defaults to continuous mode.

### Fixed

- **Neural collapse to "pass forever"**: the old checkpoint/feature pipeline
  produced games with only pass actions (no par, no track). Old samples are
  filtered by feature version and degenerate games are rejected before
  training; a pass-loop guard aborts and retries such games.
- **Action-type features were always zero** because the arena candidate did not
  carry `type`; fixed in `Arena1846::Bot#add`.
- **C&WI's free Chicago token was never used**: the special-token action is now
  generated for company-owned abilities and the engine's `SpecialToken` step is
  found via `round.actions_for(company)`.
- **Upgrade token mapping**: old-city tokens are mapped to the new tile before
  deciding whether an upgrade joins the off-board.

### Validation

- Fresh neural self-play: 500–840 decisions per game, 0 degenerate games,
  Chicago green and C5 routes appear in every sampled game, 0/9 off-board
  rotations missed in the first fixed test.
- `python train/analyze.py` runs on the live sample and writes a Chinese
  report; `/api/report` serves it in the browser.

## [1.0.0] - 2026-10-28

First public release. The arena runs complete 3–5 player 1846 games with
rules-faithful bots, a local web observatory, a self-play training loop and a
real-log rule auditor.

### Added

- Rules-aware candidate generation (`p1846/actions.rb`): track connection,
  tile stock, colour/preserved-track checks, share and train limits, and
  route search on top of the upstream `AutoRouter`.
- Rich board export (`p1846/board.rb`): tile costs, hexside terrain costs,
  era-dependent off-board revenues, E/W labels and bonus values, Z/Chicago
  labels, token stacks, blocked cities, per-city edge anchors, tile stock and
  per-corporation tile-lay slots.
- Web observatory (`web/`): live board, replay, player assets, company table
  with private-company bonuses, decision explanations and a training panel.
- Self-play learning loop: `p1846/selfplay.rb`, `train/net.py`,
  `train/nnserver.py`, `train/trainer.py`, `train/orchestrate.py`.
  Advantage-weighted imitation plus value regression, hot-reloaded checkpoints,
  periodic evaluation against heuristic seats.
- Real-game rule auditor (`audit/`): exports the engine tile catalogue and
  recomputes every logged route revenue from the actual tile on each hex,
  era-dependent off-board values and printed bonuses.
- Independent replay verifier (`verify_game.rb`, `verify_all.py`): re-executes
  every action, recomputes route revenues and checks cash conservation.
- Sample self-play games and compressed training samples under `examples/`.

### Changed

- Tile-laying candidates use the same connection/upgrade checks as the engine
  (rules 6.43, 6.46, 6.47, 6.48) and explicitly reject degenerate
  "same tile on same hex" (A→A) proposals.
- Board projection follows the site's coordinates (letters A at the top,
  K at the bottom; numbers left to right); hidden edge off-boards are no
  longer drawn.
- Training loss replaced plain REINFORCE with bounded advantage-weighted
  imitation and a prior-distillation term to keep updates stable.

### Fixed

- Mail Contract bonus now counts **visited** stops, including stops an N/M
  train passes through without counting them (rule 6.65 note).
- Port icons are treated as sticky through city upgrades until the phase-IV
  bonus-removal event.
- Chicago's four stations render as four separate edge-anchored stops instead
  of a connected cluster.

### Validation

- 95 real 18xx.games logs, 69,494 routed revenues recomputed: 99.99% match.
- All bundled self-play games pass the independent replay verifier
  (route revenue recomputation and cash conservation).
- Tile-cost distribution observed in real logs matches rule 6.48
  (e.g. H16 first lay $40, upgrades $20; B16 $20 or $60 across the mountain
  hexside; I11 $60 across the river).

### Known limitations

- Standard 1846 with 3–5 players only; no optional rules.
- Bot candidates do not yet cover every private-company ability or train
  trading between corporations.
- No MCTS: the engine cannot be cloned cheaply, so search is replaced by
  candidate ranking plus prior distillation.
- The web board is a data-driven schematic, not the official artwork.
