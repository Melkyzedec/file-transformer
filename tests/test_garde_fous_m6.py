"""Tranche 2, M6 : tests comportementaux des garde-fous anti-bombe et anti-lien.

Données exclusivement fictives (CANARY_TEST_ / @example.test).
"""

import os
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from securite_outils import (  # noqa: E402
    _TempCase,
)

import format_detector  # noqa: E402

_CONTENT_TYPES = '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'


class TestM6DocxHostiles(_TempCase):

    def _docx(self, entries) -> Path:
        path = self.root / "CANARY_TEST_hostile.docx"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
            zf.writestr("word/document.xml", "<w:document/>")
            for name, data in entries:
                zf.writestr(name, data)
        return path

    def assertRefusedBeforeParsing(self, path, message):
        self.assertEqual(format_detector.detect(str(path))["format"], "docx")
        with mock.patch("converters.document_converter.docx.Document") as parser:
            res = self.convert(path, "txt")
        self.assertFalse(res["success"])
        self.assertIn(message, res["error"])
        parser.assert_not_called()
        self.assertEqual(list(self.out_dir.iterdir()), [])

    def test_docx_with_too_many_entries_is_refused(self):
        path = self._docx((f"word/media/CANARY_TEST_{i}.xml", "x") for i in range(2000))  # 2002 entrées
        self.assertRefusedBeforeParsing(path, "trop d'entrées")

    def test_docx_entry_names_escaping_the_archive_are_refused(self):
        for name in ("../CANARY_TEST_evasion.xml", "word/../../CANARY_TEST.xml",
                     "/CANARY_TEST_absolu.xml", "..\\CANARY_TEST_windows.xml"):
            with self.subTest(name):
                self.assertRefusedBeforeParsing(self._docx([(name, "CANARY_TEST")]), "chemin interdit")

    def test_docx_with_suspicious_compression_ratio_is_refused(self):
        # 2 Mio de zéros (> 1 Mio) compressés environ 1000 fois : ratio > 100, total < 50 Mo.
        path = self._docx([("word/media/CANARY_TEST_zeros.bin", b"\0" * (2 * 1024 * 1024))])
        self.assertRefusedBeforeParsing(path, "Ratio de compression suspect")


class TestM6DetectionBornee(_TempCase):

    def test_zip_mimetype_entry_is_read_with_a_bound(self):
        path = self.root / "CANARY_TEST_mimetype.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/epub+zip" + " " * (2 * 1024 * 1024))
        returned = []
        original_read = zipfile.ZipExtFile.read

        def _counting_read(self, n=-1):
            data = original_read(self, n)
            returned.append(len(data))
            return data

        with mock.patch.object(zipfile.ZipExtFile, "read", _counting_read):
            info = format_detector.detect(str(path))
        self.assertEqual(info["format"], "epub")
        self.assertTrue(returned, msg="mimetype jamais lu")
        self.assertLessEqual(sum(returned), 4096, msg=f"Lecture non bornée : {sum(returned)} octets")


class TestM6LiensSymboliques(_TempCase):

    def setUp(self):
        super().setUp()
        self.source = self.root / "CANARY_TEST_source.png"
        with Image.new("RGB", (4, 4), (10, 20, 30)) as img:
            img.save(self.source, format="PNG")
        probe = self.root / "CANARY_TEST_probe_link"
        try:
            os.symlink(self.source, probe)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Liens symboliques indisponibles ici : {exc}")
        probe.unlink()

    def test_real_symlink_as_input_is_refused_everywhere(self):
        link = self.root / "CANARY_TEST_lien.png"
        os.symlink(self.source, link)
        self.assertEqual(self.api.files_from_paths([str(link)]), [])
        self.assertIsNone(self.api.detect_format(str(link)))
        res = self.convert(link, "webp")
        self.assertFalse(res["success"])
        self.assertEqual(list(self.out_dir.iterdir()), [])

    def test_real_symlink_as_output_folder_is_refused(self):
        target = self.root / "CANARY_TEST_vraie_sortie"
        target.mkdir()
        link = self.root / "CANARY_TEST_sortie_liee"
        os.symlink(target, link, target_is_directory=True)
        res = self.api.convert_single_file(str(self.source), "webp", output_dir=str(link))
        self.assertFalse(res["success"])
        self.assertEqual(list(target.iterdir()), [])


class TestM6HtmlVersTexte(_TempCase):

    def test_noscript_content_is_not_extracted(self):
        path = self.root / "CANARY_TEST_noscript.html"
        path.write_text(
            "<!DOCTYPE html><html><body><p>CANARY_TEST_VISIBLE</p>"
            "<noscript>CANARY_TEST_NOSCRIPT_CACHE</noscript></body></html>",
            encoding="utf-8",
        )
        res = self.convert(path, "txt")
        self.assertTrue(res["success"], msg=res.get("error"))
        text = Path(res["output_path"]).read_text(encoding="utf-8")
        self.assertIn("CANARY_TEST_VISIBLE", text)
        self.assertNotIn("CANARY_TEST_NOSCRIPT_CACHE", text)


if __name__ == "__main__":
    unittest.main()
