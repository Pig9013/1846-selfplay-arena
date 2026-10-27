"""Unit test for the real-log revenue auditor (no engine required).

Builds a tiny synthetic log that lays the green Chicago tile and runs a known
2-train route, then checks the auditor's recomputation against the catalogue.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = """Removing Boomtown
Privates in the game: Mail Contract
 -- Phase III (Operating Rounds: 2 | Train Limit: 3 | Available Tiles: Yellow, Green, Brown) --
IC spends $20 and lays tile #298 with rotation 0 on D6 (Chicago)
IC spends $40 and lays tile #299 with rotation 0 on D6 (Chicago)
IC runs a 2 train for $110: D6-C5
IC runs a 2 train for $40: D6-D6
"""


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "1846-000.txt").write_text(LOG, encoding="utf-8")
        proc = subprocess.run([sys.executable, str(ROOT / "audit" / "log_audit.py"), str(tmp)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(proc.stdout.strip())
        if proc.returncode != 0:
            print(proc.stderr)
            return 1
        if "routes checked 2" not in proc.stdout:
            print("unexpected number of audited routes")
            return 1
        if "mismatches 1" not in proc.stdout:
            print("expected exactly the degenerate D6-D6 route to be skipped or flagged")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
