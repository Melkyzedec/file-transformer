"""Tranche 1 sécurité, C1 : ressources externes HTML / Markdown -> PDF.

Données exclusivement fictives (CANARY_TEST_ / @example.test).
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from securite_outils import (  # noqa: E402
    GREEN,
    REPO_ROOT,
    _save_solid_png,
    _solid_png_data_uri,
    _count_pdf_pixels,
    _TempCase,
)


# --- C1 : ressources externes HTML / Markdown -> PDF ------------------------

class TestC1RessourcesExternesPdf(_TempCase):
    """Aucune lecture locale ni connexion réseau pendant la génération PDF."""

    def setUp(self):
        super().setUp()
        # Le lanceur Windows fait `cd` dans le dossier de l'application : on
        # place l'image « secrète » dans le dossier courant, là où xhtml2pdf
        # l'autoriserait par défaut.
        previous_cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous_cwd)
        self.local_png = _save_solid_png(self.root / "CANARY_TEST_local.png", GREEN)

        self.network_attempts = []

        def _refuse(*args, **_kwargs):
            self.network_attempts.append(repr(args[:1]))
            raise OSError("CANARY_TEST : réseau interdit pendant le test")

        for target in ("socket.create_connection", "socket.getaddrinfo"):
            patcher = mock.patch(target, side_effect=_refuse)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _html_file(self, body: str) -> Path:
        path = self.root / "CANARY_TEST_resources.html"
        path.write_text(
            "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
            f"<body><p>CANARY_TEST_HTML</p>{body}</body></html>",
            encoding="utf-8",
        )
        return path

    def test_html_to_pdf_never_embeds_local_images(self):
        local_png = self.local_png
        for label, fragment in (
            ("chemin absolu", f'<img src="{local_png}" width="40" height="40">'),
            ("chemin relatif", f'<img src="{local_png.name}" width="40" height="40">'),
            ("file://", f'<img src="{local_png.as_uri()}" width="40" height="40">'),
            ("css url()", f'<div style="background-image: url({local_png.name}); height: 40px">x</div>'),
        ):
            with self.subTest(label):
                res = self.convert(self._html_file(fragment), "pdf")
                self.assertTrue(res["success"], msg=res.get("error"))
                self.assertEqual(
                    _count_pdf_pixels(Path(res["output_path"]), GREEN), 0,
                    msg=f"Image locale incrustée dans le PDF ({label})",
                )

    def test_html_to_pdf_never_embeds_files_from_application_folder(self):
        """Le lanceur .bat démarre dans le dossier de l'application : la fixture
        du dépôt ne doit pas être lisible, en absolu comme en relatif."""
        fixture = REPO_ROOT / "tests" / "fixtures" / "exemple.png"
        purple = (167, 102, 178)  # un des quatre aplats de la fixture
        previous_cwd = os.getcwd()
        os.chdir(REPO_ROOT)
        try:
            res = self.convert(self._html_file(
                f'<img src="{fixture}" width="48" height="48">'
                '<img src="tests/fixtures/exemple.png" width="48" height="48">'
            ), "pdf")
        finally:
            os.chdir(previous_cwd)
        self.assertTrue(res["success"], msg=res.get("error"))
        self.assertEqual(_count_pdf_pixels(Path(res["output_path"]), purple, tolerance=25), 0)

    def test_html_to_pdf_never_opens_network_connections(self):
        res = self.convert(self._html_file(
            '<img src="https://tracker.example.test/CANARY_TEST_pixel.png">'
            '<img src="http://93.184.215.14/CANARY_TEST_pixel.png">'
            '<link rel="stylesheet" href="https://cdn.example.test/CANARY_TEST.css">'
        ), "pdf")
        self.assertTrue(res["success"], msg=res.get("error"))
        self.assertEqual(self.network_attempts, [], msg="Connexion réseau tentée pendant HTML -> PDF")

    def test_markdown_to_pdf_never_embeds_local_images_nor_opens_connections(self):
        md_path = self.root / "CANARY_TEST_resources.md"
        md_path.write_text(
            "# CANARY_TEST_MD\n\n"
            f"![local]({self.local_png.name})\n\n"
            f"<img src=\"{self.local_png}\" width=\"40\" height=\"40\">\n\n"
            "![pistage](https://tracker.example.test/CANARY_TEST_pixel.png)\n",
            encoding="utf-8",
        )
        res = self.convert(md_path, "pdf")
        self.assertTrue(res["success"], msg=res.get("error"))
        self.assertEqual(_count_pdf_pixels(Path(res["output_path"]), GREEN), 0)
        self.assertEqual(self.network_attempts, [])

    def test_inline_data_uri_images_are_still_rendered(self):
        """Contrôle positif : le blocage ne doit pas casser les images intégrées."""
        res = self.convert(self._html_file(
            f'<img src="{_solid_png_data_uri(GREEN)}" width="40" height="40">'
        ), "pdf")
        self.assertTrue(res["success"], msg=res.get("error"))
        self.assertGreater(_count_pdf_pixels(Path(res["output_path"]), GREEN), 100)


if __name__ == "__main__":
    unittest.main()
