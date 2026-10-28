# Analysis reports

Three reports kept as examples of what the platform actually produces:

## `logic-1003.md`

The 1003-game diagnostic generated 2026-10-28 17:47 from 1,057 usable files
(590,721 decisions, 0 degenerate). This is the most complete v1.3 baseline:

- 95.9% green Chicago, 85.7% all three Z cities, 88.5% at least one C5;
- 41.9% E/W bonus vs 98.8% in 665 human games;
- 4-train 3.14 stops vs human 3.84; 5-train 4.37 vs 4.87; 6-train 5.45 vs 5.73;
- 6.6% bankruptcy; 2.23 corps per invested player; winner margin $1,257.

Generated before the final E/W completion raise from +4 to +30, so 41.9% is a
“before” number. The report also shows “50% vs heuristic” on only 2 evaluation
games; ignore it as a statistical result.

## `logic-0318.md`

The v1.2 316-game baseline (2026-10-28 14:58), useful to see what changed
between v1.2 and v1.3:

- 96.8% green Chicago, 93.7% all three Z cities, 89.9% C5;
- 35.8% E/W; 8.9% bankruptcy; 93.5 track lays per game.

## `ab-eval-192-vs-512.json`

Raw 20-game paired A/B (same seeds; A = 192-wide, B = 512-wide), produced by
`train/ab_eval.py`. Result: A 3 wins / 5 top-2 / avg 2,090; B 2 / 3 / 1,931.
No evidence 512 is better; the live checkpoint stayed 192.

## How to regenerate

```bat
python train\analyze.py
python train\ab_eval.py --games 20
```

Reports are snapshots. They do not include the raw `train/data` (700 games,
~0.74 GB) or the human corpus; only these selected reports and the games under
`examples/selfplay/v1.3/` are kept in the repository.
