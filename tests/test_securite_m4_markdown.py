"""Tranche 1 sécurité, M4 : Markdown -> HTML sans HTML actif.

Données exclusivement fictives (CANARY_TEST_ / @example.test).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from securite_outils import (  # noqa: E402
    _active_html_findings,
    _TempCase,
)


# --- M4 : Markdown -> HTML sans HTML actif ----------------------------------

class TestM4MarkdownSansHtmlActif(_TempCase):

    HOSTILE_MD = (
        "# CANARY_TEST_TITRE {: onclick=\"alert(1)\" }\n\n"
        "<script>alert(\"CANARY_TEST_XSS\")</script>\n\n"
        "<img src=x onerror=\"alert(1)\">\n\n"
        "<iframe src=\"https://evil.example.test/CANARY_TEST\"></iframe>\n\n"
        "Texte <span onmouseover=\"alert(1)\">survol</span> en ligne.\n\n"
        "[js](javascript:alert(1)) [JS](JaVaScRiPt:alert(1)) "
        "[entité](&#106;avascript:alert(1)) [vb](vbscript:msgbox(1)) "
        "[data](data:text/html;base64,PHNjcmlwdD4=)\n\n"
        "- point **important** et [lien sûr](https://example.test/CANARY_TEST)\n\n"
        "| A | B |\n|---|---|\n| CANARY_TEST_1 | contact@example.test |\n"
    )

    def _md_to_html(self) -> str:
        path = self.root / "CANARY_TEST_hostile.md"
        path.write_text(self.HOSTILE_MD, encoding="utf-8")
        res = self.convert(path, "html")
        self.assertTrue(res["success"], msg=res.get("error"))
        return Path(res["output_path"]).read_text(encoding="utf-8")

    def test_markdown_html_output_contains_no_active_content(self):
        html_text = self._md_to_html()
        self.assertEqual(_active_html_findings(html_text), [])
        self.assertIn("&lt;script&gt;", html_text, msg="Le HTML brut doit rester visible en texte")

    def test_markdown_formatting_is_preserved(self):
        html_text = self._md_to_html()
        self.assertIn("<strong>important</strong>", html_text)
        self.assertIn('href="https://example.test/CANARY_TEST"', html_text)
        self.assertIn("<table>", html_text)
        self.assertIn("CANARY_TEST_TITRE", html_text)


if __name__ == "__main__":
    unittest.main()
