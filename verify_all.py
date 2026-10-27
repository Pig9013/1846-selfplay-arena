"""Replay every saved self-play game through the rules engine and verify it.

Usage:  python verify_all.py [folder ...]
Default folders: runs/, train/data/ (game.json files).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUBY = ROOT / "runtime/rubyinstaller-3.4.9-1-x64/bin/ruby.exe"


def verify(path: Path) -> tuple[bool, str]:
    env = dict(os.environ, RUBYOPT="-EUTF-8")
    command = f'chcp 65001 >nul && "{RUBY}" verify_game.rb "{path}"'
    proc = subprocess.run('cmd.exe /d /s /c "' + command + '"', cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (proc.stdout or "").strip().splitlines()
    err = (proc.stderr or "").strip().splitlines()
    if proc.returncode == 0 and out:
        return True, out[-1]
    return False, (err[-1] if err else (out[-1] if out else "unknown failure"))


def main(argv):
    folders = [Path(a) for a in argv[1:]] or [ROOT / "runs", ROOT / "train" / "data"]
    files: list[Path] = []
    for folder in folders:
        folder = folder if folder.is_absolute() else ROOT / folder
        if folder.is_file() and folder.suffix == ".json":
            files.append(folder)
        elif folder.is_dir():
            files.extend(sorted(folder.rglob("*game.json")))
            files.extend(sorted(folder.rglob("game.json")))
    files = list(dict.fromkeys(files))
    if not files:
        print("no game.json found")
        return 1
    ok = 0
    for path in files:
        good, message = verify(path)
        ok += 1 if good else 0
        print(("OK   " if good else "FAIL ") + str(path.relative_to(ROOT)) + "  " + message[:180])
    print(f"\n{ok}/{len(files)} games verified")
    return 0 if ok == len(files) else 2



if __name__ == "__main__":
    sys.exit(main(sys.argv))
