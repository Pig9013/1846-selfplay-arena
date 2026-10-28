# v1.3 self-play samples

Six complete games from the 2026-10-28 v1.3 run, stored in 18xx engine format
(full `raw_actions`). They are examples, not a curated “best play” set.

| game | seed | decisions | non-pass | end | scores (seat: final assets) |
| ---: | ---: | ---: | ---: | --- | --- |
| 355 | 187142 | 827 | 619 | bank | 2: 4088, 3: 1453, 1: 1401, 4: 0 |
| 359 | 187146 | 802 | 576 | bank | 4: 2809, 3: 2201, 1: 2003, 2: 0 |
| 362 | 187149 | 597 | 451 | bank | 3: 3922, 4: 3587, 2: 886, 1: 123 |
| 370 | 187157 | 591 | 443 | bank | 3: 5025, 4: 2287, 2: 0, 1: 0 |
| 374 | 187161 | 563 | 431 | bank | 2: 4075, 1: 2184, 3: 1323, 4: 0 |
| 377 | 187164 | 303 | 234 | bankrupt | 4: 898, 3: 0, 2: 0, 1: 0 |

Snapshot: `train/status.json` at 2026-10-28 19:46 (361 games, 207,227 decisions,
0 degenerate, 192-wide checkpoint step 301, mixed seats, CUDA). Includes one
bankrupt game on purpose; the trainer excludes bankrupt/very short games from
learning, but the samples are useful to inspect the end condition.

Verify a game with the independent replay checker:

```bat
ruby verify_game.rb "examples\selfplay\v1.3\187146-00359.game.json"
```

Feature version is 2 (128 state / 48 action). The accompanying training
samples are in `examples/training/`.
