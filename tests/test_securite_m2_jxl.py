"""Tranche 1 sécurité, M2 : JXL -> plafond de pixels vérifié avant décodage.

Données exclusivement fictives (CANARY_TEST_ / @example.test).
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import imagecodecs
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from securite_outils import (  # noqa: E402
    GREEN,
    _TempCase,
)


# --- M2 : JXL -> plafond de pixels vérifié avant décodage -------------------

class TestM2BombeJxl(_TempCase):

    def _jxl(self, size=(64, 64), color=GREEN) -> Path:
        arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)
        arr[:, :] = color
        path = self.root / "CANARY_TEST_image.jxl"
        path.write_bytes(imagecodecs.jpegxl_encode(arr, lossless=True))
        return path

    def _assert_refused_without_decoding(self, extra_patch=None):
        path = self._jxl()
        patches = [
            mock.patch.object(Image, "MAX_IMAGE_PIXELS", 1000),  # 64 x 64 > 2 x 1000
            mock.patch("imagecodecs.jpegxl_decode", wraps=imagecodecs.jpegxl_decode),
        ]
        if extra_patch:
            patches.append(extra_patch)
        started = [p.start() for p in patches]
        try:
            decode_spy = started[1]
            res = self.convert(path, "png")
        finally:
            for p in reversed(patches):
                p.stop()
        self.assertFalse(res["success"], msg="JXL hors plafond accepté")
        decode_spy.assert_not_called()
        self.assertEqual(list(self.out_dir.iterdir()), [])

    def test_oversized_jxl_rejected_before_decoding(self):
        self._assert_refused_without_decoding()

    def test_oversized_jxl_rejected_before_decoding_in_fallback_path(self):
        # Force le chemin de repli imagecodecs (Image.open en échec).
        self._assert_refused_without_decoding(
            mock.patch("converters.image_converter.Image.open", side_effect=OSError("CANARY_TEST"))
        )

    def test_regular_jxl_still_converts_with_correct_pixels(self):
        res = self.convert(self._jxl(size=(64, 48)), "png")
        self.assertTrue(res["success"], msg=res.get("error"))
        with Image.open(res["output_path"]) as img:
            self.assertEqual(img.size, (64, 48))
            self.assertEqual(img.convert("RGB").getpixel((32, 24)), GREEN)


if __name__ == "__main__":
    unittest.main()
