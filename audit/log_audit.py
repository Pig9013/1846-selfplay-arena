"""Audit real 18xx.games 1846 logs against the engine's tile catalogue.

Recomputes every logged route's revenue from the tile laid on each hex, the
era-dependent off-board values and the printed E/W / port / meat / boom bonus
values, then compares with what the site reported.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAT = json.loads((ROOT / "audit" / "catalog.json").read_text(encoding="utf-8"))
TILES = CAT["tiles"]
HEXES = CAT["hexes"]
DEFAULT_LOGS = Path(r"D:\兵棋\18xx\复盘分析\1846")
LOGS = DEFAULT_LOGS

PHASE_RE = re.compile(r"-- Phase (I{1,3}V?|IV) ")
LAY_RE = re.compile(r"lays tile #(\S+) with rotation \d+ on ([A-Z]\d+)")
RUN_RE = re.compile(r"(.+?) runs a ([\d/]+) train for \$([\d,]+): (.+)$")
ASSIGN_RE = re.compile(r"(Meat Packing Company|Steamboat Company|Boomtown) is assigned to ([A-Z]\d+|[A-Z&]+)$")

ERA = {"I": "yellow", "II": "yellow", "III": "brown", "IV": "brown"}


def tile_value(hex_id, phase, board):
    tile = TILES.get(board.get(hex_id) or HEXES[hex_id]["tile"])
    if not tile:
        return None
    if tile["cities"]:
        return max(c["revenue"].get(ERA[phase], 0) for c in tile["cities"])
    if tile["offboards"]:
        return max(o["revenue"].get(ERA[phase], 0) for o in tile["offboards"])
    if tile["towns"]:
        return max(t["revenue"].get(ERA[phase], 0) for t in tile["towns"])
    return 0


def is_east(hex_id, board):
    tile = TILES.get(board.get(hex_id) or HEXES[hex_id]["tile"])
    return bool(tile) and any("E" in (o.get("groups") or []) for o in tile["offboards"])


def is_west(hex_id, board):
    tile = TILES.get(board.get(hex_id) or HEXES[hex_id]["tile"])
    return bool(tile) and (tile.get("label") == "W")


def bonus_icons(hex_id, board):
    tile = TILES.get(board.get(hex_id) or HEXES[hex_id]["tile"])
    if not tile:
        return 0
    total = 0
    for name in tile["icons"]:
        try:
            total += int(name)
        except ValueError:
            pass
    return total


def port_icons(hex_id, board):
    # Port icons are printed on the original hex and stay sticky through
    # upgrades until the phase-IV event removes them.
    tile = TILES.get(HEXES[hex_id]["tile"])
    return sum(1 for n in (tile or {}).get("icons", []) if n == "port")


def audit_log(path: Path):
    board = {}
    phase = "I"
    assign = {}
    checked = 0
    bad = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("] ", 1)[-1].strip()
        if "Privates in the game:" in line or line.startswith("Removing "):
            # A new game starts (the corpus concatenates some logs).
            board, assign, phase = {}, {}, "I"
            continue
        m = PHASE_RE.search(line)
        if m:
            phase = m.group(1)
            continue
        m = LAY_RE.search(line)
        if m:
            board[m.group(2)] = m.group(1)
            continue
        m = ASSIGN_RE.search(line)
        if m:
            assign[m.group(1)] = m.group(2)
            continue
        m = RUN_RE.search(line)
        if not m:
            continue
        corp, train, revenue, route = m.groups()
        revenue = int(revenue.replace(",", ""))
        parts = [p.strip() for p in route.split(" + ")]
        path_part = parts[0]
        bonuses = parts[1:]
        unknown = [b for b in bonuses if b not in ("E/W", "Mail Contract", "Meat-Packing", "Port", "Boomtown")]
        if unknown:
            continue
        tokens = [tok.strip() for tok in path_part.split("-") if tok.strip()]
        visited = [tok.strip("() ") for tok in tokens]
        stops = [tok.strip() for tok in tokens if not tok.startswith("(")]
        values = []
        missing = False
        for hex_id in stops:
            if hex_id not in HEXES:
                missing = True
                break
            value = tile_value(hex_id, phase, board)
            values.append(value)
        if missing or any(v is None for v in values):
            continue
        count = int(train.split("/")[0])
        counted = sorted(values, reverse=True)[:count]
        total = sum(counted)
        if "E/W" in bonuses:
            east = next((h for h in stops if is_east(h, board)), None)
            west = next((h for h in stops if is_west(h, board)), None)
            if east and west:
                total += bonus_icons(east, board) + bonus_icons(west, board)
            else:
                continue
        if "Mail Contract" in bonuses:
            # The Mail Contract pays per *visited* stop, including the stops an
            # N/M train passes through but does not count (rule 6.65 note).
            total += 10 * len(visited)
        if "Meat-Packing" in bonuses:
            if assign.get("Meat Packing Company") in stops:
                total += 30
            else:
                continue
        if "Port" in bonuses:
            hexes = [h for h in stops if h == assign.get("Steamboat Company")]
            if not hexes:
                continue
            total += 20 * port_icons(hexes[0], board)
        if "Boomtown" in bonuses:
            if "H12" not in stops:
                continue
            total += 20
        checked += 1
        if total != revenue:
            bad.append({"corp": corp, "train": train, "stops": stops, "values": values,
                        "phase": phase, "calc": total, "log": revenue, "bonuses": bonuses})
    return checked, bad


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    logs_dir = Path(argv[0]) if argv else (DEFAULT_LOGS if DEFAULT_LOGS.is_dir() else ROOT / "examples" / "logs")
    total_checked = 0
    all_bad = []
    files = sorted(logs_dir.glob("1846-*.txt"))
    for path in files:
        checked, bad = audit_log(path)
        total_checked += checked
        all_bad.extend((path.name, b) for b in bad)
    print(f"logs {len(files)}  routes checked {total_checked}  mismatches {len(all_bad)}  "
          f"match rate {100*(total_checked-len(all_bad))/max(total_checked,1):.2f}%")
    for name, b in all_bad[:15]:
        print(name, json.dumps(b, ensure_ascii=False))
    Path(ROOT / "audit" / "mismatches.json").write_text(
        json.dumps([{"log": n, **b} for n, b in all_bad], ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(0 if main() is None else 1)