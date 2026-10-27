# Example data

`selfplay/` contains three complete games played by the heuristic bots:

| folder | players | seed | actions | end |
| --- | --- | --- | --- | --- |
| `3p-seed1846` | 3 | 1846 | 392 | bank |
| `4p-seed606` | 4 | 606 | 460 | bank |
| `5p-seed23` | 5 | 23 | 589 | bank |

Each folder has `game.json` (engine action list), `engine-log.txt` (full
English engine log), `summary.json` and `outcome.json`.

Verify any of them with the independent replay checker:

```bat
ruby verify_game.rb "examples\selfplay\4p-seed606\game.json"
```

`training/` contains two gzipped self-play sample files (one game each):
`state` (128 floats), up to 12 candidate `actions` (40 floats each), the
`chosen` index, the heuristic `prior` scores and the final normalised
placement `z`. Decompress with `gzip -d` and feed them to
`train/trainer.py`.
