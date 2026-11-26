"""Tranche 1 sécurité, M3 : PDF -> image, plafond de pixels et de pages avant rendu.

Données exclusivement fictives (CANARY_TEST_ / @example.test).
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from securite_outils import (  # noqa: E402
    DocumentConverter,
    _minimal_pdf,
    _TempCase,
)


# --- M3 : PDF -> image, plafond de pixels et de pages avant rendu -------------

class TestM3BombePdf(_TempCase):

    def _pdf(self, **kwargs) -> Path:
        path = self.root / "CANARY_TEST_bomb.pdf"
        path.write_bytes(_minimal_pdf(**kwargs))
        return path

    def test_huge_page_rejected_before_rendering(self):
        pdf = self._pdf(media_box=(0, 0, 14400, 14400))  # 333 octets, 30 000 px de côté à 150 DPI
        with mock.patch.object(DocumentConverter, "_save_pdf_page_image") as render:
            res = self.convert(pdf, "png", dpi=150)
        self.assertFalse(res["success"])
        render.assert_not_called()
        self.assertIn("pixels", res["error"])

    def test_tall_or_oversized_pages_rejected_before_rendering(self):
        cases = {
            "page haute et étroite": ((0, 0, 10, 14400), 150),   # 21 x 30 000 px
            "page large et basse": ((0, 0, 14400, 10), 150),     # 30 000 x 21 px
            "budget de pixels": ((0, 0, 14000, 14000), 72),      # 14 000 px de côté, 196 Mpx
        }
        for label, (media_box, dpi) in cases.items():
            with self.subTest(label):
                pdf = self._pdf(media_box=media_box)
                with mock.patch.object(DocumentConverter, "_save_pdf_page_image") as render:
                    res = self.convert(pdf, "png", dpi=dpi)
                self.assertFalse(res["success"], msg=label)
                render.assert_not_called()

    def test_too_many_pages_rejected_before_rendering(self):
        limit = getattr(DocumentConverter, "MAX_PDF_IMAGE_PAGES", 500)
        pdf = self._pdf(media_box=(0, 0, 10, 10), pages=limit + 1)
        with mock.patch.object(DocumentConverter, "_save_pdf_page_image") as render:
            res = self.convert(pdf, "png", dpi=72)
        self.assertFalse(res["success"])
        render.assert_not_called()
        self.assertIn("pages", res["error"])

    def test_a4_at_max_dpi_is_still_allowed(self):
        """Contrôle positif : une page A4 à 600 DPI reste sous le plafond."""
        def _fake_render(_page, dest_path, *_args):
            Path(dest_path).write_bytes(b"CANARY_TEST")

        pdf = self._pdf(media_box=(0, 0, 595, 842))
        with mock.patch.object(DocumentConverter, "_save_pdf_page_image", side_effect=_fake_render) as render:
            res = self.convert(pdf, "png", dpi=600)
        self.assertTrue(res["success"], msg=res.get("error"))
        render.assert_called_once()

    def test_memory_error_reports_a_clear_message(self):
        pdf = self._pdf()
        with mock.patch.object(DocumentConverter, "_save_pdf_page_image", side_effect=MemoryError()):
            res = self.convert(pdf, "png", dpi=150)
        self.assertFalse(res["success"])
        self.assertIn("mémoire", res["error"].lower())


if __name__ == "__main__":
    unittest.main()
