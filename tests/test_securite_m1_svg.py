"""Tranche 1 sécurité, M1 : SVG -> image sans lecture de fichiers locaux.

Données exclusivement fictives (CANARY_TEST_ / @example.test).
"""

import os
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from securite_outils import (  # noqa: E402
    GREEN,
    RED,
    _save_solid_png,
    _solid_png_data_uri,
    _TempCase,
)


# --- M1 : SVG -> image sans lecture de fichiers locaux ----------------------

class TestM1SvgSansRessourcesLocales(_TempCase):

    def setUp(self):
        super().setUp()
        other = self.root / "ailleurs"
        other.mkdir()
        self.secret = _save_solid_png(other / "CANARY_TEST_secret.png", RED, size=(50, 50))
        self.svg_dir = self.root / "svg"
        self.svg_dir.mkdir()
        previous_cwd = os.getcwd()
        os.chdir(self.svg_dir)
        self.addCleanup(os.chdir, previous_cwd)

    def _render_center(self, svg_text: str):
        path = self.svg_dir / "CANARY_TEST_image.svg"
        path.write_text(svg_text, encoding="utf-8")
        res = self.convert(path, "png", dpi=72)
        self.assertTrue(res["success"], msg=res.get("error"))
        with Image.open(res["output_path"]) as img:
            return img.convert("RGBA").getpixel((25, 25))

    @staticmethod
    def _svg(inner: str, doctype: str = "") -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>' + doctype +
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            'width="50" height="50">' + inner + "</svg>"
        )

    def test_svg_never_embeds_local_image_files(self):
        secret = self.secret
        relative = os.path.relpath(secret, self.svg_dir).replace(os.sep, "/")
        cases = {
            "href absolu": self._svg(f'<image href="{secret}" width="50" height="50"/>'),
            "xlink:href absolu": self._svg(f'<image xlink:href="{secret}" width="50" height="50"/>'),
            "href relatif": self._svg(f'<image href="{relative}" width="50" height="50"/>'),
            "file://": self._svg(f'<image href="{secret.as_uri()}" width="50" height="50"/>'),
            "entité XML": self._svg(
                "&canary;",
                doctype=(
                    "<!DOCTYPE svg [<!ENTITY canary '<image xmlns=\"http://www.w3.org/2000/svg\" "
                    f"href=\"{secret}\" width=\"50\" height=\"50\"/>'>]>"
                ),
            ),
        }
        for label, svg_text in cases.items():
            with self.subTest(label):
                pixel = self._render_center(svg_text)
                self.assertNotEqual(pixel[:3], RED, msg=f"Image locale incrustée ({label})")

    def test_svg_inline_data_uri_and_internal_references_still_render(self):
        """Contrôle positif : data: et références internes (#id) restent permises."""
        data_uri = _solid_png_data_uri(GREEN, size=(50, 50))
        self.assertEqual(
            self._render_center(self._svg(f'<image href="{data_uri}" width="50" height="50"/>'))[:3],
            GREEN,
        )
        self.assertEqual(
            self._render_center(self._svg(
                '<defs><rect id="CANARY_TEST_r" width="50" height="50" fill="#00ff00"/></defs>'
                '<use xlink:href="#CANARY_TEST_r"/>'
            ))[:3],
            GREEN,
        )


if __name__ == "__main__":
    unittest.main()
