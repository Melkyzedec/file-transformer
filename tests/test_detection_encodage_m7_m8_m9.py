"""Tranche 2, M7, M8 et M9 : détection HTML/SVG, encodages Unicode, version de Python.

Données exclusivement fictives (CANARY_TEST_ / @example.test).
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from securite_outils import (  # noqa: E402
    REPO_ROOT,
    _TempCase,
)

import format_detector  # noqa: E402

INLINE_ICON = '<svg width="10" height="10"><rect width="10" height="10"/></svg>'


class TestM7HtmlAvecSvgInline(_TempCase):

    def _write(self, name, text) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_html_documents_with_inline_svg_are_detected_as_html(self):
        cases = {
            "doctype": f"<!DOCTYPE html><html><body><p>CANARY_TEST</p>{INLINE_ICON}</body></html>",
            "sans doctype": f"<html><head><title>CANARY_TEST</title></head><body>{INLINE_ICON}</body></html>",
            "icône en tête": f"<!doctype html>\n<html lang=\"fr\"><body>{INLINE_ICON}<p>CANARY_TEST</p></body></html>",
            "fragment": f"<div class=\"carte\">{INLINE_ICON}<p>CANARY_TEST</p></div>",
        }
        for label, text in cases.items():
            with self.subTest(label):
                info = format_detector.detect(str(self._write("CANARY_TEST_page.html", text)))
                self.assertEqual((info["format"], info["category"], info["mismatch"]),
                                 ("html", "document", False))

    def test_html_with_inline_svg_converts_to_pdf(self):
        path = self._write("CANARY_TEST_page.html",
                           f"<!DOCTYPE html><html><body><p>CANARY_TEST_PDF</p>{INLINE_ICON}</body></html>")
        res = self.convert(path, "pdf")
        self.assertTrue(res["success"], msg=res.get("error"))

    def test_real_svg_files_are_still_detected_as_svg(self):
        cases = {
            "simple": '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>',
            "prologue complet": (
                '<?xml version="1.0" encoding="UTF-8"?>\n<!-- CANARY_TEST commentaire <html> -->\n'
                '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n'
                '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>'
            ),
            "sous-ensemble DTD": (
                '<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY ns_svg "http://www.w3.org/2000/svg">]>'
                '<svg xmlns="&ns_svg;" width="8" height="8"/>'
            ),
            "foreignObject html": (
                '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><foreignObject>'
                '<html xmlns="http://www.w3.org/1999/xhtml"><body>CANARY_TEST</body></html>'
                "</foreignObject></svg>"
            ),
        }
        for label, text in cases.items():
            with self.subTest(label):
                info = format_detector.detect(str(self._write("CANARY_TEST_image.svg", text)))
                self.assertEqual(info["format"], "svg")
                # Même contenu mal nommé : la signature texte doit l'emporter.
                disguised = format_detector.detect(str(self._write("CANARY_TEST_image.txt", text)))
                self.assertEqual(disguised["format"], "svg")


class TestM8EncodagesUnicode(_TempCase):

    TEXT = "CANARY_TEST_é ünïcödé € 中文 contact@example.test\nligne 2\n"

    def test_text_files_with_unicode_boms_are_decoded(self):
        for encoding in ("utf-16", "utf-16-be", "utf-32", "utf-32-be", "utf-8-sig"):
            with self.subTest(encoding):
                path = self.root / f"CANARY_TEST_{encoding}.txt"
                bom = {"utf-16-be": b"\xfe\xff", "utf-32-be": b"\x00\x00\xfe\xff"}.get(encoding, b"")
                path.write_bytes(bom + self.TEXT.encode(encoding))
                res = self.convert(path, "html")
                self.assertTrue(res["success"], msg=res.get("error"))
                html_text = Path(res["output_path"]).read_text(encoding="utf-8")
                self.assertIn("CANARY_TEST_é ünïcödé € 中文 contact@example.test\nligne 2", html_text)
                self.assertNotIn("\x00", html_text)
                self.assertNotIn("﻿", html_text)

    def test_utf16_markdown_is_rendered(self):
        path = self.root / "CANARY_TEST_notes.md"
        path.write_bytes("# CANARY_TEST_TITRE é\n\n- **gras**\n".encode("utf-16"))
        res = self.convert(path, "html")
        self.assertTrue(res["success"], msg=res.get("error"))
        html_text = Path(res["output_path"]).read_text(encoding="utf-8")
        self.assertIn("CANARY_TEST_TITRE é</h1>", html_text)
        self.assertIn("<strong>gras</strong>", html_text)

    def test_legacy_and_plain_utf8_files_still_decode(self):
        cases = {
            "cp1252": ("CANARY_TEST café 20 €\r\nfin\r\n".encode("cp1252"), "CANARY_TEST café 20 €\nfin"),
            "utf-8 sans BOM": ("CANARY_TEST 中文 é\nfin\n".encode("utf-8"), "CANARY_TEST 中文 é\nfin"),
            "latin-1": ("CANARY_TEST \x81 é\n".encode("latin-1"), "CANARY_TEST \x81 é"),
        }
        for label, (raw, expected) in cases.items():
            with self.subTest(label):
                path = self.root / "CANARY_TEST_ancien.txt"
                path.write_bytes(raw)
                res = self.convert(path, "md")
                self.assertTrue(res["success"], msg=res.get("error"))
                self.assertIn(expected, Path(res["output_path"]).read_text(encoding="utf-8"))
                Path(res["output_path"]).unlink()


class TestM9VersionPython(unittest.TestCase):
    """numpy 2.5.5 et imagecodecs 2026.11.11 exigent Python 3.12 au minimum."""

    MINIMUM = (3, 12)

    def test_launcher_requires_python_3_12(self):
        bat = (REPO_ROOT / "Lancer File Transformer.bat").read_text(encoding="utf-8")
        probes = re.findall(r"sys\.version_info < \((\d+), (\d+)\)", bat)
        self.assertGreaterEqual(len(probes), 2, msg="Sondes de version introuvables")
        for probe in probes:
            self.assertEqual(tuple(int(v) for v in probe), self.MINIMUM)
        self.assertIn("Python 3.12 ou plus recent est requis", bat)
        self.assertNotRegex(bat, r"3\.1[01]\b")

    def test_readme_announces_python_3_12(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("à partir de la version 3.12", readme)
        self.assertNotRegex(readme, r"version 3\.1[01]\b")


if __name__ == "__main__":
    unittest.main()
