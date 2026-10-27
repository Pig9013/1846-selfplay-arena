[中文](README.zh-CN.md) · **English** · [Français](README.fr.md) · [日本語](README.ja.md) · [Русский](README.ru.md)

# 1846 Self-Play Arena · 1846 Self-Play Lab

A local **1846: The Race for the Midwest** self-play and self-learning platform: the open-source 18xx.games rules engine executes the rules, with rules-aware bots, a neural-network self-play training loop, a replayable web spectating interface, and an audit toolset that checks rule values against real game logs.

[![verify](https://github.com/Pig9013/1846-selfplay-arena/actions/workflows/verify.yml/badge.svg)](https://github.com/Pig9013/1846-selfplay-arena/actions/workflows/verify.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Version 1.0.0** · Windows · runs offline · no site account or cloud model required

---

## What this project solves

The fine details of 18xx rules (terrain costs, offboard revenue changing by phase, east–west bonuses, Z/Chicago-specific tiles, station blocking, tile supply) are very easy to get wrong in a home-grown AI. This project hands the “rules” to an engine battle-tested in real play on the site, keeps the “decisions” for itself, and checks the rule implementation against **real game logs**:

- **Rule execution**: `18xx-master` (tobymao/18xx, MIT) is the only judge; the bots only generate candidates, and the engine validates them.
- **Real-game audit**: `audit/` exports the tile catalog from the engine, replays track laying, phases and bonus allocation from 95 18xx.games logs, and independently recomputes **69,494 route revenues**, agreeing with the site records **99.99%** of the time.
- **Self-learning loop**: a minimal KataGo-style implementation — multi-process self-play sampling → policy/value network training → hot-reloading the new model → win-rate evaluation against heuristic baselines.
- **Observable**: the web page shows the board, costs, offboard values, bonus attribution, tile supply and per-turn track/upgrade slots in real time.

> 1846 is designed by Thomas Lehmann and published by GMT Games. This repository **does not include** the rulebook, art assets or any official files; the rules engine is third-party MIT code, and the self-play data is produced by this project's bots.

## Main features

| Module | Description |
| --- | --- |
| Rule values | Track cost = max($20, printed value); river/mountain/tunnel edge costs are paid on **first connection**; Z tiles / Chicago tiles / plain tiles are kept separate; tile counts are limited; a full station blocks passage |
| Offboard and east–west | Offboard revenue takes its value from the phase (yellow/brown); E→E is forbidden, W→W is allowed, Holland and Louisville are neutral; the E/W bonus is the sum of the offboard icon values at both ends |
| Private companies | Boomtown / Meat Packing / Steamboat act per **hex** and per **owner** (Wheeling/Holland ports +$40, the rest +$20); allocation and attribution are visible |
| Bots | Rules-aware candidate generation (connection checks, tile supply, colour/reserved track, share and train limits), heuristic scoring, optionally overlaid with a neural-network policy |
| Self-learning | `p1846/selfplay.rb` samples → `train/nnserver.py` inference → `train/trainer.py` training → `train/orchestrate.py` orchestration |
| Spectating | Local web page: board, replay, player assets, corporation table, decision reasons, training panel |
| Audit | `audit/log_audit.py` recomputes route revenues from real logs; `verify_game.rb` replays action by action and checks cash conservation |
| Resource use | Child processes run below normal priority; concurrency defaults to “cores − 2”; training uses only 2 torch threads |

## Quick start

### Requirements

- Windows 10/11, Python 3.12 (the standard library alone runs the platform; training needs PyTorch)
- The project ships a portable Ruby 3.4.9 runtime in `runtime/` (the system Ruby is not modified)
- The **18xx rules engine** goes **next to** this directory: `../18xx-master` (clone `https://github.com/tobymao/18xx`, or use a snapshot you already have)

```
父目录/
├── 1846自战平台/      ← 本仓库
│   ├── server.py
│   ├── arena.rb
│   ├── p1846/
│   ├── train/
│   ├── audit/
│   ├── web/
│   └── runtime/        ← Ruby 运行时（发布包自带，仓库中忽略）
└── 18xx-master/        ← 规则引擎（MIT）
```

### Running the platform

```bat
启动平台.cmd
```

Open `http://127.0.0.1:1846` in a browser, choose the player count and seat policies, and start a self-play game. Alternatively:

```bat
python server.py --no-browser --port 1846
```

### Running self-learning

```bat
python train\orchestrate.py --workers 6 --minutes 120 --train-every 4 --steps 200 --eval-every 30 --seed 3000
```

Or double-click `启动训练.cmd`. Models are written to `train/checkpoints/latest.pt`, samples to `train/data/`, and the “Self-learning training” panel on the web page starts and stops it.

### Verifying the rules

```bat
ruby audit\export_catalog.rb     :: 从引擎导出瓦片目录
python audit\log_audit.py        :: 重算真实日志的线路收入并比对
python verify_all.py runs        :: 逐局重放并核对收入与现金守恒
python tests\\test_audit.py       :: 审计器单元测试（CI 也跑这个）
```

## Repository structure

```
server.py              本机 HTTP 服务、对局/训练管理、静态页面
arena.rb               单局自战循环：候选生成 → 打分/网络 → 引擎执行
engine_boot.rb         原生 Ruby 加载适配（跳过仅供浏览器的 JS 段）
verify_game.rb         独立复核一局（逐行动重放、收入重算、现金守恒）
verify_all.py          批量复核
p1846/board.rb         版图与规则数值导出（成本、边费、外域、标签、库存、奖励归属）
p1846/actions.rb       合法候选生成 + 线路组合搜索（上游 AutoRouter）
p1846/policy.rb        启发式打分
p1846/model.rb         神经网络特征编码（128 维状态 / 40 维动作）
p1846/selfplay.rb      自战采样进程（写出训练样本）
train/net.py           策略/价值网络
train/nnserver.py      本机推理服务（热加载检查点）
train/trainer.py       训练循环（优势加权模仿 + 价值回归）
train/orchestrate.py   多进程自战 + 训练 + 评估编排
audit/                 真实对局日志审计工具与瓦片目录
web/                   中文观战与训练面板
examples/              自战样例（对局 JSON、引擎日志、训练样本）
```

## Data formats

### Games (`examples/selfplay/*/game.json`)

18xx engine format: players, seed, full `raw_actions`. Replay directly with `verify_game.rb`:

```bat
ruby verify_game.rb "examples\selfplay\4p-seed606\game.json"
```

### Training samples (`examples/training/*.jsonl.gz`)

One JSONL per game, line by line:

```json
{"type":"decision","actor":"1","state":[128 个浮点],"actions":[[40 个浮点],...],"chosen":0,"prior":[...]}
{"type":"result","scores":{"1":5506,"2":0,...},"z":{"1":0.98,...}}
```

- `state`: position features (phase, bank, corporation cash/trains/share price, player assets, board statistics)
- `actions`: action features of at most 12 legal candidates at that decision point
- `chosen`: index of the candidate actually taken
- `prior`: heuristic score (used for distillation)
- `z`: rank payoff normalised by final assets (mean 0, standard deviation 1)

## Rule verification results

95 logs and 69,494 route revenues recomputed, **99.99%** agreement with the site (the 5 differences come from gaps in the auditor's own board tracking). The audit confirmed and fixed two implementations that are easy to get wrong:

- **Mail Contract** bills by the stations **passed through** (including stations skipped by N/M trains and stations that generate no revenue);
- **Port icons are sticky**: after a city upgrades, the port icon stays until the phase IV event removes the bonus.

The real distribution of track costs also matches rule 6.48: H16 $40 for the first lay / $20 for an upgrade; B16 $20 when it does not cross a mountain edge, $60 when it does; I11 $60 across the river; F18 shows the 20/40/60/80 combinations.

## Self-learning status (1.0)

- The loop runs end to end: 6 processes in 9 minutes produce about 100+ games and tens of thousands of decision samples, with the loss falling steadily.
- The small-sample win rate against three heuristic seats is about 0.67 (few samples, indicative only, **not a claim that playing strength already exceeds humans or the heuristics**).
- No MCTS: engine positions cannot be cloned cheaply, so candidate ranking + prior distillation + advantage weighting stand in for tree search.

## Known limitations

- Only standard 1846, 3–5 players, no optional rules.
- Bot candidates do not cover every special ability (track laying by some private companies, train trading).
- The web board is a simplified data-driven drawing: values, orientation and adjacencies match the rules, but it is not the official art.
- The full action sequence of real games cannot be fetched from the site API (archived games return empty actions), and local logs hide the private-company allocation step, so the audit uses “board state + revenue recomputation”, not a full game replay.

## Version

Currently **1.0.0**. Changes in [CHANGELOG.md](CHANGELOG.md). Roadmap: cover the missing special-ability candidates, fold track slots/supply/bonus attribution into the network features, and add stricter opponent-pool evaluation.

## English summary

A local, offline arena for **1846: The Race for the Midwest**. A sibling
checkout of the MIT-licensed [tobymao/18xx](https://github.com/tobymao/18xx)
engine judges every action; this project adds rules-aware candidate generation,
a data-driven board/replay UI, a KataGo-style self-play training loop and a
real-log rule auditor (95 logs, 69,494 route revenues recomputed, 99.99% match).
Version 1.0.0. Sample games and compressed training samples live under
`examples/` and in the v1.0.0 release. The repository does not vendor the rules
engine, the Ruby runtime, or any official 1846 assets.

## License and notices

- Original code in this repository: MIT (see [LICENSE](LICENSE)).
- Rules engine: `tobymao/18xx`, MIT.
- **1846: The Race for the Midwest** is designed by Thomas Lehmann and published by GMT Games; this project is not affiliated with its publisher and contains no rulebook, map art or any official components.
- Self-play data is produced by this project's bots and can be used freely for research.
