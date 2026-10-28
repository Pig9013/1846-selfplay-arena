"""Build web/human.html: inline human.css and human.js into the shell.

Edit web/human_shell.html, web/human.css or web/human.js, then run:

    python build_web.py

The arena server serves /human.html as a single request, so the page embeds its
styles and script instead of relying on extra routes.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"


def main():
    shell = (WEB / "human_shell.html").read_text(encoding="utf-8")
    css = (WEB / "human.css").read_text(encoding="utf-8")
    js = (WEB / "human.js").read_text(encoding="utf-8")
    html = shell.replace('<link rel="stylesheet" href="/human.css">', "<style>\n" + css + "\n</style>")
    html = html.replace('<script src="/human.js"></script>', "<script>\n" + js + "\n</script>")
    if "<style>" not in html or "<script>" not in html:
        raise SystemExit("human_shell.html must keep the css/js placeholders")
    (WEB / "human.html").write_text(html, encoding="utf-8")
    print(f"wrote {WEB / 'human.html'} ({len(html)} bytes)")


if __name__ == "__main__":
    main()
