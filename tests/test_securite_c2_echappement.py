"""Tranche 1 sécurité, C2 : échappement HTML des sorties DOCX / PDF / TXT.

Données exclusivement fictives (CANARY_TEST_ / @example.test).
"""

import sys
import unittest
from pathlib import Path

import docx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from securite_outils import (  # noqa: E402
    XSS_PAYLOAD,
    _active_html_findings,
    _TempCase,
)


# --- C2 : échappement HTML des sorties DOCX / PDF / TXT -----------------------

class TestC2EchappementSorties(_TempCase):
    """Le contenu hostile ressort comme du texte, jamais comme des balises."""

    def _docx_with_payload(self) -> Path:
        path = self.root / "CANARY_TEST_payload.docx"
        document = docx.Document()
        document.add_paragraph(f"CANARY_TEST_PARA {XSS_PAYLOAD}")
        table = document.add_table(rows=1, cols=1)
        table.cell(0, 0).text = f"CANARY_TEST_CELL {XSS_PAYLOAD}"
        document.save(str(path))
        return path

    def _txt_with_payload(self) -> Path:
        path = self.root / "CANARY_TEST_payload.txt"
        path.write_text(f"CANARY_TEST_TXT {XSS_PAYLOAD}\ncontact@example.test\n", encoding="utf-8")
        return path

    def _pdf_text(self, pdf_path: Path) -> str:
        res = self.api.convert_single_file(str(pdf_path), "txt", output_dir=str(self.out_dir))
        self.assertTrue(res["success"], msg=res.get("error"))
        return Path(res["output_path"]).read_text(encoding="utf-8")

    def assertEscaped(self, html_text: str):
        self.assertEqual(_active_html_findings(html_text), [])
        self.assertIn("&lt;script&gt;", html_text)

    def test_docx_to_html_escapes_paragraphs_and_table_cells(self):
        res = self.convert(self._docx_with_payload(), "html")
        self.assertTrue(res["success"], msg=res.get("error"))
        html_text = Path(res["output_path"]).read_text(encoding="utf-8")
        self.assertEscaped(html_text)
        self.assertEqual(html_text.count("&lt;script&gt;"), 2)

    def test_docx_to_pdf_keeps_payload_as_literal_text(self):
        res = self.convert(self._docx_with_payload(), "pdf")
        self.assertTrue(res["success"], msg=res.get("error"))
        text = self._pdf_text(Path(res["output_path"]))
        # Paragraphe et cellule : la charge doit apparaître deux fois, telle quelle.
        self.assertEqual(text.count("<img src=x onerror=alert(1)>"), 2, msg=text)
        self.assertEqual(text.count('<script>alert("CANARY_TEST_XSS")</script>'), 2, msg=text)

    def test_txt_to_html_and_pdf_keep_payload_as_literal_text(self):
        txt = self._txt_with_payload()
        res_html = self.convert(txt, "html")
        self.assertTrue(res_html["success"], msg=res_html.get("error"))
        self.assertEscaped(Path(res_html["output_path"]).read_text(encoding="utf-8"))

        res_pdf = self.convert(txt, "pdf")
        self.assertTrue(res_pdf["success"], msg=res_pdf.get("error"))
        self.assertIn("<img src=x onerror=alert(1)>", self._pdf_text(Path(res_pdf["output_path"])))

    def test_pdf_to_html_escapes_extracted_text(self):
        res_pdf = self.convert(self._txt_with_payload(), "pdf")
        self.assertTrue(res_pdf["success"], msg=res_pdf.get("error"))
        res_html = self.api.convert_single_file(res_pdf["output_path"], "html", output_dir=str(self.out_dir))
        self.assertTrue(res_html["success"], msg=res_html.get("error"))
        self.assertEscaped(Path(res_html["output_path"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
