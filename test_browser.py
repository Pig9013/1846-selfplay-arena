"""Optional browser QA; requires Playwright and Microsoft Edge, not used at runtime."""
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from test_platform import api, wait_idle

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "test-output"


def main():
    wait_idle()
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("http://127.0.0.1:1846")
        page.wait_for_function("latest !== null")
        page.evaluate("selectRun('b9f2d517970b')")
        expect(page.locator("#subtitle")).to_contain_text("本局胜者 AI 4")
        assert page.locator("#map .hex").count() > 50
        page.locator("#first").click()
        expect(page.locator("#actions")).to_have_text("0")
        page.locator("#next").click()
        expect(page.locator("#actions")).to_have_text("1")
        page.locator("#live").click()
        expect(page.locator("#actions")).to_have_text("455")
        page.screenshot(path=str(OUT / "desktop.png"), full_page=True)

        page.locator("#seed").fill("1846")
        page.locator("#start").click()
        expect(page.locator("#status")).to_have_text("自战中")
        page.wait_for_function("latest?.summary.action_count > 2")
        page.locator("#pause").click()
        expect(page.locator("#status")).to_have_text("已暂停")
        run_id = page.evaluate("selected")
        before = api("/api/state?id=" + run_id)["summary"]["action_count"]
        page.wait_for_timeout(1700)
        assert api("/api/state?id=" + run_id)["summary"]["action_count"] == before
        page.locator("#step").click()
        page.wait_for_function("latest?.summary.action_count === " + str(before + 1))
        page.wait_for_timeout(1600)
        assert api("/api/state?id=" + run_id)["summary"]["action_count"] == before + 1
        page.locator("#pause").click()
        expect(page.locator("#status")).to_have_text("自战中")
        expect(page.locator("#status")).to_have_text("已完成", timeout=90000)
        summary = api("/api/state?id=" + run_id)["summary"]
        winner = max(summary["result"], key=summary["result"].get)
        expect(page.locator("#subtitle")).to_contain_text("本局胜者 AI " + winner)

        mobile = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, device_scale_factor=1)
        mobile.on("pageerror", lambda e: errors.append(str(e)))
        mobile.goto("http://127.0.0.1:1846")
        mobile.wait_for_function("latest !== null && latest.state !== null")
        assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth")
        mobile.screenshot(path=str(OUT / "mobile.png"), full_page=True)
        browser.close()
    assert not errors, errors
    result = {"passed": True, "browser": "Microsoft Edge", "javascript_errors": errors,
              "checks": ["correct winner", "map", "first/next/latest replay", "pause", "single step",
                         "resume", "natural completion", "mobile overflow"], "game": summary}
    (OUT / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("BROWSER CHECKS PASSED", run_id, summary["action_count"], flush=True)


if __name__ == "__main__":
    main()
