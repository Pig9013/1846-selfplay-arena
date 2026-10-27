"""Integration checks against a running local arena (python server.py --no-browser)."""
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:1846"
ROOT = Path(__file__).resolve().parent


def api(path, data=None):
    request = urllib.request.Request(BASE + path, data=None if data is None else json.dumps(data).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def wait_idle(timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = api("/api/runs")
        if not data["active"] and not data["batch"]["active"]:
            return data
        time.sleep(.4)
    raise AssertionError("Game did not finish within test budget")


def frame_count(run_id):
    return api("/api/state?id=" + run_id)["summary"]["frames"]


def check_records(run_id):
    directory = ROOT / "runs" / run_id
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "complete", summary
    game = json.loads((directory / "game.json").read_text(encoding="utf-8"))
    transitions = [json.loads(x) for x in (directory / "transitions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(transitions) == len(game["actions"]) == summary["action_count"]
    assert summary["frames"] == len(transitions) + 1
    assert transitions[-1]["next_observation"]["result"] == game["result"] == summary["result"]
    first = api(f"/api/frame?id={run_id}&index=0")
    last = api(f"/api/frame?id={run_id}&index={summary['frames']-1}")
    assert first["state"]["action_count"] == 0
    assert last["state"]["finished"]
    print("RECORDS OK", run_id, summary["config"]["players"], summary["action_count"], flush=True)
    return summary


def main():
    wait_idle()
    # Start paused before the Ruby process emits its first frame.
    run_id = api("/api/start", {"players": 3, "seed": 99})["id"]
    api("/api/control", {"id": run_id, "action": "pause"})
    time.sleep(2)
    count = frame_count(run_id)
    time.sleep(.5)
    assert frame_count(run_id) == count
    api("/api/control", {"id": run_id, "action": "step"})
    deadline = time.monotonic() + 15
    while frame_count(run_id) == count and time.monotonic() < deadline:
        time.sleep(.1)
    assert frame_count(run_id) == count + 1
    time.sleep(.5)
    assert frame_count(run_id) == count + 1
    api("/api/control", {"id": run_id, "action": "resume"})
    time.sleep(.7)
    api("/api/control", {"id": run_id, "action": "stop"})
    wait_idle()
    state = api("/api/state?id=" + run_id)
    assert state["summary"]["status"] == "stopped"
    with urllib.request.urlopen(BASE + f"/api/download?id={run_id}&file=game.json") as response:
        partial = json.load(response)
    assert len(partial["actions"]) == state["summary"]["action_count"]
    print("PAUSE / STEP / RESUME / STOP / EXPORT OK", flush=True)
    for bad in ({"players": 2}, {"players": 3, "strategies": ["bad"]}):
        try:
            api("/api/start", bad)
            raise AssertionError("Invalid input accepted")
        except urllib.error.HTTPError as error:
            assert error.code == 400
    request = urllib.request.Request(BASE + "/api/start", data=b'{}',
                                     headers={"Origin": "http://example.com"})
    try:
        urllib.request.urlopen(request)
        raise AssertionError("Foreign origin accepted")
    except urllib.error.HTTPError as error:
        assert error.code == 403
    print("INVALID INPUT / ORIGIN OK", flush=True)
    results = []
    for players, seed in ((3, 42), (4, 17), (5, 23)):
        run_id = api("/api/start", {"players": players, "seed": seed})["id"]
        wait_idle()
        results.append(check_records(run_id))
    api("/api/batch", {"players": 3, "seed": 50, "count": 2})
    batch = wait_idle()["batch"]
    assert not batch.get("error"), batch
    assert len(batch["runs"]) == 2
    for run_id in batch["runs"]:
        results.append(check_records(run_id))
    first, second = results[-2:]
    assert first["config"]["strategies"][1:] + first["config"]["strategies"][:1] == second["config"]["strategies"]
    report = {"passed": True, "games": results}
    (ROOT / "test-output").mkdir(exist_ok=True)
    (ROOT / "test-output/integration.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("ALL INTEGRATION CHECKS PASSED", flush=True)


if __name__ == "__main__":
    main()
