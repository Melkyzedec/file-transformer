"""Tranche 2, mineurs : m1, m2, m5, m7 et m8 (m11 est couvert par frontend-state.cjs).

Données exclusivement fictives (CANARY_TEST_ / @example.test).
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from securite_outils import (  # noqa: E402
    AppAPI,
    _minimal_pdf,
    _TempCase,
)

from converters.image_converter import ImageConverter  # noqa: E402


class TestM1ExplorerPortable(unittest.TestCase):
    """La résolution d'explorer.exe se teste sur toute plateforme."""

    def test_explorer_is_resolved_from_systemroot_as_absolute_path(self):
        with mock.patch.dict(os.environ, {"SystemRoot": os.path.join(os.sep, "CANARY_TEST_Windows")}):
            with mock.patch("app_api.os.path.isfile", return_value=True) as isfile:
                resolved = AppAPI._resolve_explorer_executable()
        expected = os.path.normpath(os.path.join(os.sep, "CANARY_TEST_Windows", "explorer.exe"))
        self.assertEqual(resolved, expected)
        self.assertTrue(os.path.isabs(resolved))
        isfile.assert_called_once_with(expected)

    def test_missing_explorer_disables_open_folder(self):
        with mock.patch("app_api.os.path.isfile", return_value=False):
            self.assertIsNone(AppAPI._resolve_explorer_executable())


class TestM2NomsReservesWindows(unittest.TestCase):

    RESERVED = [
        "CONIN$", "conout$.txt", "COM0", "lpt0.log", "COM¹", "com².png", "COM³", "LPT¹", "lpt²", "LPT³.pdf",
        "nul:", "NUL:CANARY_TEST_flux", "con.txt:CANARY_TEST_flux", "aux .txt", "PRN. .md",
        "\\\\.\\PhysicalDrive0", "//./pipe/CANARY_TEST", "\\\\.\\C:", "C:\\CANARY_TEST\\COM4\\x.png",
    ]
    ALLOWED = [
        "console.txt", "CONFIG.png", "COM10.txt", "LPT10", "nul_CANARY_TEST.txt", "COM.png", "auxiliaire.md",
        "\\\\?\\C:\\CANARY_TEST\\image.png", "C:\\CANARY_TEST\\COMPTES\\x.png", "C:\\CANARY_TEST\\image.png",
        "\\\\serveur.example.test\\partage\\CANARY_TEST.png",
    ]

    def test_all_windows_device_names_are_rejected(self):
        for name in self.RESERVED:
            with self.subTest(name):
                self.assertTrue(AppAPI._is_windows_reserved_path(name))

    def test_ordinary_names_are_still_accepted(self):
        for name in self.ALLOWED:
            with self.subTest(name):
                self.assertFalse(AppAPI._is_windows_reserved_path(name))

    def test_reserved_names_are_rejected_without_touching_the_disk(self):
        api = AppAPI()

        def _forbid(*_args, **_kwargs):
            raise AssertionError("Accès disque interdit pour un nom réservé")

        with mock.patch("app_api.os.path.isfile", side_effect=_forbid), \
             mock.patch("app_api.os.path.islink", side_effect=_forbid), \
             mock.patch("app_api.format_detector.detect", side_effect=_forbid):
            self.assertEqual(api.files_from_paths(self.RESERVED), [])
            for name in self.RESERVED:
                self.assertFalse(api.convert_single_file(name, "png")["success"])


class TestM5OptionsValidees(_TempCase):

    def setUp(self):
        super().setUp()
        self.png = self.root / "CANARY_TEST_options.png"
        with Image.new("RGB", (8, 6), (200, 30, 30)) as img:
            img.save(self.png, format="PNG")
        self.pdf = self.root / "CANARY_TEST_options.pdf"
        self.pdf.write_bytes(_minimal_pdf(media_box=(0, 0, 50, 50)))

    def test_quality_must_be_an_integer_between_1_and_100(self):
        for bad in (0, 101, -5, 1000, True, False, "50", 50.5):
            for source, target in ((self.png, "jpg"), (self.png, "webp"), (self.png, "png"), (self.pdf, "jpg")):
                with self.subTest(quality=bad, target=target, source=source.suffix):
                    res = self.convert(source, target, quality=bad)
                    self.assertFalse(res["success"], msg=f"quality={bad!r} acceptée")
                    self.assertIn("qualité", res["error"].lower())
        self.assertEqual(list(self.out_dir.iterdir()), [])

    def test_quality_bounds_are_accepted(self):
        for good in (1, 100):
            with self.subTest(good):
                res = self.convert(self.png, "jpg", quality=good)
                self.assertTrue(res["success"], msg=res.get("error"))

    def test_keep_aspect_ratio_must_be_a_boolean(self):
        for bad in ("false", "true", 0, 1, "non"):
            with self.subTest(bad):
                res = self.convert(self.png, "png", width=4, keep_aspect_ratio=bad)
                self.assertFalse(res["success"], msg=f"keep_aspect_ratio={bad!r} accepté")
        for good, expected in ((True, (4, 3)), (False, (4, 6))):
            with self.subTest(good):
                res = self.convert(self.png, "png", width=4, keep_aspect_ratio=good)
                self.assertTrue(res["success"], msg=res.get("error"))
                with Image.open(res["output_path"]) as img:
                    self.assertEqual(img.size, expected)


class TestM7MessagesErreur(_TempCase):

    def assertNoDirectoryLeak(self, message):
        for directory in (str(self.root), str(self.out_dir), str(self.root).replace("\\", "\\\\")):
            self.assertNotIn(directory, message)

    def test_missing_file_error_names_the_file_only(self):
        res = self.api.convert_single_file(str(self.root / "CANARY_TEST_absent.png"), "webp")
        self.assertFalse(res["success"])
        self.assertIn("CANARY_TEST_absent.png", res["error"])
        self.assertNoDirectoryLeak(res["error"])

    def test_library_errors_do_not_expose_directories(self):
        corrupt = self.root / "CANARY_TEST_corrompu.png"
        corrupt.write_bytes(b"\x89PNG\r\n\x1a\nCANARY_TEST_CORROMPU")
        res = self.convert(corrupt, "webp")
        self.assertFalse(res["success"])
        self.assertTrue(res["error"].strip())
        self.assertNoDirectoryLeak(res["error"])

    def test_memory_and_silent_errors_get_a_clear_message(self):
        png = self.root / "CANARY_TEST_memoire.png"
        with Image.new("RGB", (4, 4)) as img:
            img.save(png, format="PNG")
        with mock.patch.object(ImageConverter, "convert", side_effect=MemoryError()):
            res = self.convert(png, "webp")
        self.assertFalse(res["success"])
        self.assertIn("mémoire", res["error"].lower())
        with mock.patch.object(ImageConverter, "convert", side_effect=RuntimeError()):
            res = self.convert(png, "webp")
        self.assertFalse(res["success"])
        self.assertTrue(res["error"].strip(), msg="Message d'erreur vide")


class TestM8HtmlVersTexteMasque(_TempCase):

    def _txt(self, html_text: str) -> str:
        path = self.root / "CANARY_TEST_masque.html"
        path.write_text(html_text, encoding="utf-8")
        res = self.convert(path, "txt")
        self.assertTrue(res["success"], msg=res.get("error"))
        return Path(res["output_path"]).read_text(encoding="utf-8")

    def test_non_visible_elements_are_not_extracted(self):
        text = self._txt(
            "<!DOCTYPE html><html><head><title>CANARY_TEST_TITRE</title>"
            "<meta name='description' content='x'></head><body>"
            "<p>CANARY_TEST_VISIBLE</p>"
            "<template>CANARY_TEST_TEMPLATE</template>"
            "<svg><text>CANARY_TEST_SVG</text></svg>"
            "<iframe>CANARY_TEST_IFRAME</iframe>"
            "<p>CANARY_TEST_FIN</p></body></html>"
        )
        self.assertIn("CANARY_TEST_VISIBLE", text)
        self.assertIn("CANARY_TEST_FIN", text)
        for hidden in ("TITRE", "TEMPLATE", "SVG", "IFRAME"):
            self.assertNotIn(f"CANARY_TEST_{hidden}", text)

    def test_unclosed_head_does_not_swallow_the_body(self):
        for label, html_text in {
            "sans </head>": "<html><head><title>CANARY_TEST_TITRE</title><body><p>CANARY_TEST_CORPS</p></body></html>",
            "sans <body>": "<head><title>CANARY_TEST_TITRE</title><p>CANARY_TEST_CORPS</p>",
        }.items():
            with self.subTest(label):
                text = self._txt(html_text)
                self.assertIn("CANARY_TEST_CORPS", text)
                self.assertNotIn("CANARY_TEST_TITRE", text)


if __name__ == "__main__":
    unittest.main()
