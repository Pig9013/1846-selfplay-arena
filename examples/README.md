# Example data

## Games

`selfplay/` contains complete games from two eras:

- `selfplay/3p-seed1846`, `selfplay/4p-seed606`, `selfplay/5p-seed23`: v1.0
  heuristic games with engine logs, summaries and outcomes.
- `selfplay/v1.3/`: six v1.3 neural/mixed games (full `game.json`, manifest),
  including one bankrupt game. See the folder README for metadata.

Each v1.0 folder has `game.json` (engine action list), `engine-log.txt` (full
English engine log), `summary.json` and `outcome.json`. The v1.3 folder keeps
only `game.json` + `manifest.json` to stay small.

Verify any game with the independent replay checker:

```bat
ruby verify_game.rb "examples\selfplay\4p-seed606\game.json"
ruby verify_game.rb "examples\selfplay\v1.3\187146-00359.game.json"
```

## Reports

`reports/` keeps three analysis examples:

- `logic-1003.md`: the 1003-game v1.3 diagnostic (1,057 files, 590,721 decisions);
- `logic-0318.md`: the v1.2 316-game baseline;
- `ab-eval-192-vs-512.json`: raw 20-game paired A/B (192 vs 512, no evidence 512 wins).

## Training samples

`training/` contains gzipped self-play sample files (one game each):

- v1.0 examples: 128 state floats, up to 12 actions × 40 floats;
- v1.3 examples: 128 state floats, up to 12 actions × 48 floats (feature version 2),
  plus winner/margin/winner-weight metadata.

Each line has `state`, candidate `actions`, the chosen index, the heuristic
`prior` and the final normalised placement `z`. Decompress with `gzip -d` and
feed them to `train/trainer.py`.
