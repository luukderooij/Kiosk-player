"""Tests voor de JavaScript van de webinterface, met node. Zonder node worden ze overgeslagen."""
import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="node is niet geïnstalleerd")


def render(markdown: str) -> str:
    script = ("const { renderMarkdown } = require(process.argv[1]);"
              "let s = ''; process.stdin.on('data', d => s += d);"
              "process.stdin.on('end', () => process.stdout.write(JSON.stringify(renderMarkdown(s))));")
    res = subprocess.run([NODE, "-e", script, os.path.join(ROOT, "app", "static", "markdown.js")],
                         input=markdown.encode(), capture_output=True, check=True)
    return json.loads(res.stdout)


def test_app_js_syntax():
    subprocess.run([NODE, "--check", os.path.join(ROOT, "app", "static", "app.js")], check=True)


def test_changelog_renders():
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        html = render(f.read())
    assert html.startswith("<h2>Changelog</h2>")
    assert "<h4>Toegevoegd</h4>" in html and "<ul><li>" in html
    assert "]: https" not in html  # referentielinks onderaan zijn verwerkt, niet als tekst getoond


@pytest.mark.parametrize("md, must, must_not", [
    ("# <script>x</script>", "&lt;script&gt;", "<script"),
    ("[klik](javascript:alert(1))", "[klik](javascript:alert(1))", "href"),
    ("[ok](https://x.nl/?a=1&b=2)", 'href="https://x.nl/?a=1&amp;b=2"', None),
    ("`<b>` en **vet** en *schuin*", "<code>&lt;b&gt;</code> en <b>vet</b> en <i>schuin</i>", None),
    ("- een\n  vervolg\n- twee", "<li>een vervolg</li><li>twee</li>", None),
    ("Zie [ref].\n\n[ref]: https://voorbeeld.nl", 'href="https://voorbeeld.nl"', "]: https"),
])
def test_markdown_is_safe_and_correct(md, must, must_not):
    html = render(md)
    assert must in html
    if must_not:
        assert must_not not in html
