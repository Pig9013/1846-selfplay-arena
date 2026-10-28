[中文](README.zh-CN.md) · **English** · [Français](README.fr.md) · [日本語](README.ja.md) · [Русский](README.ru.md)

# 1846 Self-Play Arena · 1846 Self-Play Lab

A local **1846: The Race for the Midwest** self-play and self-learning platform: the open-source 18xx.games rules engine executes the rules, with rules-aware bots, a neural-network self-play training loop, a replayable web spectating interface, and an audit toolset that checks rule values against real game logs.

[![verify](https://github.com/Pig9013/1846-selfplay-arena/actions/workflows/verify.yml/badge.svg)](https://github.com/Pig9013/1846-selfplay-arena/actions/workflows/verify.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Version 1.2.0** · Windows · runs offline · no site account or cloud model required

> **What changed from 1.0.0**: continuous self-play with 316 usable games, 48-wide action features and bounded neural residuals, rotation-aware track/offboard scoring, a 665-game human prior replacing the hard-coded Chicago rule, and per-1000-game analysis. Full comparison: [RELEASE_NOTES.en.md](RELEASE_NOTES.en.md).

---

## What this project solves

The fine details of 18xx rules (terrain costs, offboard revenue changing by phase, east–west bonuses, Z/Chicago-specific tiles, station blocking, tile supply) are very easy to get wrong in a home-grown AI. This project hands the “rules” to an engine battle-tested in real play on the site, keeps the “decisions” for itself, and checks the rule implementation against **real game logs**:

- **Rule execution**: `18xx-master` (tobymao/18xx, MIT) is the only judge; the bots only generate candidates, and the engine validates them.
- **Real-game audit**: `audit/` exports the tile catalog from the engine, replays track laying, phases and bonus allocation from 95 18xx.games logs, and independently recomputes **69,494 route revenues**, agreeing with the site records **99.99%** of the time.
- **Self-learning loop**: a minimal KataGo-style implementation — multi-process continuous self-play sampling → policy/value network training → hot-reloading the new model → win-rate evaluation against heuristic baselines; a new action-logic analysis every 1000 games.
- **Observable**: the web page shows the board, costs, offboard values, bonus attribution, tile supply and per-turn track/upgrade slots in real time.

> 1846 is designed by Thomas Lehmann and published by GMT Games. This repository **does not include** the rulebook, art assets or any official files; the rules engine is third-party MIT code, and the self-play data is produced by this project's bots.

## Main features

| Module | Description |
| --- | --- |
| Rule values | Track cost = max($20, printed value); river/mountain/tunnel edge costs are paid on **first connection**; Z tiles / Chicago tiles / plain tiles are kept separate; tile counts are limited; a full station blocks passage |
| Offboard and east–west | Offboard revenue takes its value from the phase (yellow/brown); E→E is forbidden, W→W is allowed, Holland and Louisville are neutral; the E/W bonus is the sum of the offboard icon values at both ends |
| Private companies | Boomtown / Meat Packing / Steamboat act per **hex** and per **owner** (Wheeling/Holland ports +$40, the rest +$20); allocation and attribution are visible |
| Bots | Rules-aware candidate generation (connection checks, tile stock, colour/preserved-track checks, share and train limits), heuristic scoring, optional neural policy overlay |
| Self-learning | `p1846/selfplay.rb` sampling → `train/nnserver.py` inference → `train/trainer.py` training → `train/orchestrate.py` continuous orchestration → `train/analyze.py` per-1000-game analysis |
| Human prior | `train/human_playbook.py` builds `human_playbook.md` and `human_prior.json` from 665 human games; `p1846/human_prior.rb` uses them as a soft prior, not a rule |
| Spectating | Local web UI: board, replay, player assets, company table, decision reasons and a training panel |
| Audit | `audit/log_audit.py` recomputes route revenues from real logs; `verify_game.rb` replays every action and checks cash conservation |
| Resources | Child processes run below normal priority; 6 self-play workers by default; training uses only 2 torch threads |

## Quick start

### Dependencies

- Windows 10/11, Python 3.12 (the standard library is enough to run the platform; training needs PyTorch)
- The project bundles a portable Ruby 3.4.9 runtime in `runtime/` (the system Ruby is not modified)
- The **18xx rules engine** goes **next to** this directory: `../18xx-master` (clone `https://github.com/tobymao/18xx`, or use an existing snapshot)

```
parent/
├── 1846-selfplay-arena/   ← this repository
│   ├── server.py
│   ├── arena.rb
│   ├── p1846/
│   ├── train/
│   ├── audit/
│   ├── web/
│   └── runtime/           ← Ruby runtime (bundled with the release, ignored in git)
└── 18xx-master/           ← rules engine (MIT)
```

### Run the platform

```bat
启动平台.cmd
```

Open `http://127.0.0.1:1846`, choose the player count and seat strategies, and start a self-play game. You can also run:

```bat
python server.py --no-browser --port 1846
```

### Run self-learning

```bat
python train\orchestrate.py --workers 6 --minutes 0 --train-every 4 --steps 200 --eval-every 300 --report-every 1000
```

`--minutes 0` (the default) means **run until you stop it**. You can also double-click `启动训练.cmd`. The model is written to `train/checkpoints/latest.pt`, samples to `train/data/`, and the per-1000-game analysis to `train/reports/logic-N.md`; the web training panel can start/stop training and generate an analysis on demand.

### Validate the rules

```bat
ruby audit\export_catalog.rb     :: export the tile catalogue from the engine
python audit\log_audit.py        :: recompute route revenues from real logs
python verify_all.py runs        :: replay games and check revenue/cash conservation
python tests\test_audit.py       :: auditor unit test (also run by CI)
```

## Repository structure

```
RELEASE_NOTES.md        full 1.2.0 vs 1.0.0 comparison (Chinese)
RELEASE_NOTES.en.md     English release notes
server.py               local HTTP service, game/training management, static UI
arena.rb                single-game self-play loop: candidates → score/net → engine
engine_boot.rb          native Ruby loading adapter (skips browser-only JS)
verify_game.rb          independent replay of one game (revenue, cash conservation)
verify_all.py           batch replay verifier
p1846/board.rb          board and rule-value export (costs, edges, offboards, labels, stock, bonus attribution)
p1846/actions.rb        legal candidate generation + route combination search (upstream AutoRouter)
p1846/policy.rb         heuristic scoring
p1846/model.rb          neural feature encoding (128 state / 48 action)
p1846/connectivity.rb   rotation-aware connectivity / offboard links / E-W completion analysis
p1846/human_prior.rb    human-game frequency prior (soft weight, can be disabled)
p1846/selfplay.rb       self-play sampling process (writes training samples)
train/net.py            policy/value network
train/nnserver.py       local inference service (hot-reloads checkpoints)
train/trainer.py        training loop (advantage-weighted imitation + value regression)
train/analyze.py        per-1000-game action-logic report
train/human_playbook.py human play summary + prior generation
train/orchestrate.py    multi-process self-play + training + evaluation orchestration
audit/                  real-log audit tools and tile catalogue
web/                    Chinese spectating and training UI
examples/               sample games (JSON, engine logs, training samples)
```

## Data formats

### Games (`examples/selfplay/*/game.json`)

18xx engine format: players, seed, complete `raw_actions`. Replay with `verify_game.rb`:

```bat
ruby verify_game.rb "examples\selfplay\4p-seed606\game.json"
```

### Training samples (`examples/training/*.jsonl.gz`)

One JSONL per game, one line per record:

```json
{"type":"decision","actor":"1","state":[128 floats],"actions":[[48 floats],...],"chosen":0,"prior":[...]}
{"type":"result","scores":{"1":5506,"2":0,...},"z":{"1":0.98,...}}
```

- `state`: position features (phase, bank, company cash/trains/share price, player assets, board statistics)
- `actions`: up to 12 legal candidate actions at this decision point
- `chosen`: index of the executed candidate
- `prior`: heuristic score (used for distillation)
- `z`: rank return normalised by final assets (mean 0, standard deviation 1)

## Rule audit results

95 logs and 69,494 route revenues recomputed, **99.99%** agreement with the site (the 5 differences come from the auditor's own board-tracking gaps). The audit confirmed and fixed two easy-to-miss rules:

- **Mail Contract** pays for **visited** stops (including stops an N/M train passes through without counting them);
- **Port icons are sticky**: after a city upgrade the port icon remains until the phase-IV bonus-removal event.

The observed track-cost distribution also matches rule 6.48: H16 first lay $40 / upgrade $20; B16 $20 without crossing the mountain edge, $60 across it; I11 $60 across the river; F18 shows the 20/40/60/80 combination.

## Self-learning status (1.2)

Latest snapshot (2026-10-28 14:58, `train/reports/logic-0318.md`): **316 usable games, 182,549 decisions, 0 degenerate**; 96.8% green Chicago, 93.7% all three Z cities, 89.9% at least one C5, 35.8% E/W, 8.9% bankruptcy.

- **Continuous self-play**: 6 workers run until stopped; each game writes `train/games.jsonl` and `train/data/`; a `train/reports/logic-N.md` report is written every 1000 games.
- **Human prior (1.2)**: frequencies from 665 18xx.games human games produce `train/human_playbook.md` and `train/human_prior.json`. The policy treats them as a soft prior (default 10, 0 disables).
- **Chicago (1.2)**: the v1.1 hard-coding (D6 +30/+55/+90/+125, C5 +40, Chicago station +58, home-to-Chicago distance) is gone. Chicago now appears only through generic revenue, connectivity and the human frequency prior; the 96.8% green-Chicago rate is learned, not written into the scorer.
- **Feature repair (v1.1)**: action-type bits are no longer zero; action vectors are 48-wide; offboard links, rotation-aware connectivity and Chicago gateway features were added; old 40-wide and degenerate samples are filtered.
- **Track repair (v1.1)**: scoring uses the rotated tile; connecting an offboard gives `+42 + 0.6×revenue`, pointing at one without connecting `−30`; C&WI's free Chicago token is actually used.
- **E/W completion (1.2)**: joining the other side gives `+55`, the first side `+14`, approaching the missing side `+2` per hex; no Chicago coupling.
- **Scale repair**: network scores are standardised per decision and added at weight 15, with 5% uniform exploration, avoiding the old “pass forever” collapse.
- **Local models**: self-play is driven by the project's `latest.pt` + heuristic prior. LM Studio is an optional third-party decision backend; Ollama / llama.cpp are detection-only. No external model is required. The “local model detection” panel shows the checkpoint, inference service and external endpoints.
- **Largest gap**: E/W is only 35.8%, versus 98.8% in 665 human games. The cause is company-level route planning: in a typical game IC runs only W, while GT/ERIE/NYC/PRR/B&O run only E; no company spans both.
- **No MCTS**: engine positions cannot be cloned cheaply, so candidate ranking + prior distillation + advantage weighting replace tree search.
- **Win rate is not a conclusion**: only 2 evaluation games, 0 wins. The sample is too small to judge the network, let alone claim it beats humans.

## Known limitations

- Standard 1846 with 3–5 players only; no optional rules.
- Bot candidates do not yet cover every private-company ability or train trading between corporations.
- The web board is a data-driven schematic: values, orientation and adjacency match the rules, but it is not the official artwork.
- The complete action sequence of real games cannot be fetched from the site API (archived games return empty actions), and local logs hide private-company allocation; the audit therefore uses “board + revenue recomputation”, not a full replay.
- E/W completion and company-level cross-region planning remain the top behavioural gap; Chicago may be over-concentrated at 96.8%; bankruptcy is 8.9% in the latest sample.

## Version

Current **1.2.0**. Full comparison with 1.0.0: [RELEASE_NOTES.en.md](RELEASE_NOTES.en.md); per-version changes: [CHANGELOG.md](CHANGELOG.md). Roadmap: complete special-ability candidates, add track slots/stock/bonus attribution to network features, evaluate against a stricter opponent pool, and solve company-level E/W planning first.

## License and notices

- Original code in this repository: MIT (see [LICENSE](LICENSE)).
- Rules engine: `tobymao/18xx`, MIT.
- **1846: The Race for the Midwest** is designed by Thomas Lehmann and published by GMT Games; this project is not affiliated with the publisher and does not include the rulebook, map art or any official component.
- Self-play data is produced by this project's bots and may be used freely for research.
