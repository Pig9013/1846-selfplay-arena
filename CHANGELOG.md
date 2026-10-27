# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and the
project uses [Semantic Versioning](https://semver.org/).

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
