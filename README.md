[中文](README.zh-CN.md) · **English** · [Français](README.fr.md) · [日本語](README.ja.md) · [Русский](README.ru.md)

# 1846 Self-Play Arena · 1846 Self-Play Lab

A local **1846: The Race for the Midwest** self-play and self-learning platform: the open-source 18xx.games rules engine executes the rules, with rules-aware bots, a neural-network self-play training loop, a replayable web spectating interface, and an audit toolset that checks rule values against real game logs.

[![verify](https://github.com/Pig9013/1846-selfplay-arena/actions/workflows/verify.yml/badge.svg)](https://github.com/Pig9013/1846-selfplay-arena/actions/workflows/verify.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Version 1.3.0** · Windows · runs offline · no site account or cloud model required

Version history and release notes live in [docs/releases/](docs/releases/); dated run snapshots live in [docs/status/](docs/status/).

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
| Human table | `/human.html`: 1 human + 2 AI, 18xx.games-style board/companies/market/depot/action dock, undo, private-price ladder and seller consent; writes full logs and behaviour-cloning samples |
| GPU | `train/trainer.py` / `nnserver.py` use CUDA when available; Ruby rules remain CPU |
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
docs/releases/          version history, comparisons and release notes
docs/status/            dated run snapshots
examples/reports/       analysis report examples (1003 / 316 / A-B)
examples/selfplay/      self-play game samples (v1.0 + v1.3)
examples/training/      training sample examples
build_web.py            inline web/human_* into web/human.html
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

## Current status

- **1003-game diagnostic** (2026-10-28 17:47, `examples/reports/logic-1003.md`): 1,057 usable files, 590,721 decisions, 0 degenerate; 95.9% green Chicago, 85.7% all three Z cities, 88.5% C5, 41.9% E/W, 6.6% bankruptcy.
- **Latest restarted run** (`train/status.json`): 361 games, 207,227 decisions, 301 training steps, 0 degenerate; 192-wide net, CUDA, mixed seats, human prior 20, stopped.
- **Largest gaps**: E/W 41.9% vs human 98.8%; 4-train 3.14 stops vs 3.84; cross-holding 2.23 corps. The cause is company-level route planning, not another global bonus.
- Version history and the full “what is still unsolved” list: [docs/releases/](docs/releases/); dated snapshots: [docs/status/](docs/status/).

## Known limitations

- Standard 1846 with 3–5 players only; no optional rules.
- Bot candidates do not yet cover every private-company ability or train trading between corporations.
- The web board is a data-driven schematic: values, orientation and adjacency match the rules, but it is not the official artwork.
- The complete action sequence of real games cannot be fetched from the site API (archived games return empty actions), and local logs hide private-company allocation; the audit therefore uses “board + revenue recomputation”, not a full replay.
- E/W completion and company-level cross-region planning remain the top behavioural gap; the 4-train only runs 3.14 stops vs the human 3.84; bankruptcy is 6.6% in the 1003-game diagnostic.
- The 1003-game diagnostic predates the final E/W +30 change; the current 361-game run has no fresh 1000-game report yet.

## Version

Current **1.3.0**. Version history, comparisons and release notes: [docs/releases/](docs/releases/); per-version engineering changes: [CHANGELOG.md](CHANGELOG.md). Roadmap: solve company-level E/W planning, 4-train route length and cross-holding first; then evaluate larger networks or search.

## License and notices

- Original code in this repository: MIT (see [LICENSE](LICENSE)).
- Rules engine: `tobymao/18xx`, MIT.
- **1846: The Race for the Midwest** is designed by Thomas Lehmann and published by GMT Games; this project is not affiliated with the publisher and does not include the rulebook, map art or any official component.
- Self-play data is produced by this project's bots and may be used freely for research.
