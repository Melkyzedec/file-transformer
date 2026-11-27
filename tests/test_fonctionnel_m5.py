"""Tranche 2, M5 : les conversions produisent le bon contenu, pas seulement un fichier.

Fixture à quatre aplats (tests/fixtures/exemple.png, celle du README) et
images générées à motifs connus. Données exclusivement fictives
(CANARY_TEST_ / @example.test).
"""

import sys
import unittest
from pathlib import Path

import imagecodecs
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from securite_outils import (  # noqa: E402
    REPO_ROOT,
    _minimal_pdf,
    _TempCase,
)

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "exemple.png"
NAVY, YELLOW, PURPLE, GREEN = (37, 61, 91), (255, 225, 137), (167, 102, 178), (110, 195, 154)
QUADRANTS = (NAVY, YELLOW, PURPLE, GREEN)  # haut-gauche, haut-droite, bas-gauche, bas-droite


def _quadrant_image(size=(64, 32)) -> Image.Image:
    width, height = size
    half_w, half_h = width // 2, height // 2
    img = Image.new("RGB", size)
    boxes = ((0, 0, half_w, half_h), (half_w, 0, width, half_h),
             (0, half_h, half_w, height), (half_w, half_h, width, height))
    for box, color in zip(boxes, QUADRANTS):
        img.paste(color, box)
    return img


class _PixelCase(_TempCase):

    def assertQuadrants(self, path, tolerance=2, size=None):
        with Image.open(path) as img:
            if size is not None:
                self.assertEqual(img.size, size)
            rgb = img.convert("RGB")
            width, height = rgb.size
            centers = ((width // 4, height // 4), (3 * width // 4, height // 4),
                       (width // 4, 3 * height // 4), (3 * width // 4, 3 * height // 4))
            for center, expected in zip(centers, QUADRANTS):
                actual = rgb.getpixel(center)
                self.assertTrue(
                    all(abs(a - e) <= tolerance for a, e in zip(actual, expected)),
                    msg=f"{Path(path).name} {center} : {actual} au lieu de {expected}",
                )

    def png(self, name="CANARY_TEST_quadrants.png", size=(64, 32)) -> Path:
        path = self.root / name
        with _quadrant_image(size) as img:
            img.save(path, format="PNG")
        return path


class TestM5ImagesPixels(_PixelCase):

    def test_readme_fixture_to_every_raster_format_keeps_the_four_colors(self):
        lossless = {"png": 0, "bmp": 0, "gif": 0, "ico": 0, "jxl": 2}
        lossy = {"webp": 40, "jpg": 40, "jfif": 40}
        for target, tolerance in {**lossless, **lossy}.items():
            with self.subTest(target):
                res = self.convert(FIXTURE, target)
                self.assertTrue(res["success"], msg=res.get("error"))
                self.assertQuadrants(res["output_path"], tolerance=tolerance, size=(48, 48))

    def test_transparent_png_to_jpg_uses_white_background(self):
        path = self.root / "CANARY_TEST_transparent.png"
        with Image.new("RGBA", (16, 16), (0, 0, 0, 0)) as img:
            img.save(path, format="PNG")
        res = self.convert(path, "jpg")
        self.assertTrue(res["success"], msg=res.get("error"))
        with Image.open(res["output_path"]) as out:
            self.assertTrue(all(c >= 245 for c in out.convert("RGB").getpixel((8, 8))))

    def test_quality_option_changes_jpeg_output(self):
        path = self.root / "CANARY_TEST_bruit.png"
        rng = np.random.default_rng(20261126)
        with Image.fromarray(rng.integers(0, 256, (128, 128, 3), dtype=np.uint8)) as img:
            img.save(path, format="PNG")
        sizes = {}
        for quality in (10, 95):
            res = self.convert(path, "jpg", quality=quality)
            self.assertTrue(res["success"], msg=res.get("error"))
            sizes[quality] = res["size"]
            Path(res["output_path"]).unlink()
        self.assertLess(sizes[10], sizes[95] * 0.6, msg=sizes)

    def test_resize_width_height_and_keep_aspect_ratio(self):
        source = self.png(size=(64, 32))
        cases = (
            ({"width": 32}, (32, 16)),
            ({"height": 8}, (16, 8)),
            ({"width": 32, "keep_aspect_ratio": True}, (32, 16)),
            ({"width": 32, "height": 32, "keep_aspect_ratio": True}, (32, 16)),
            ({"width": 32, "height": 32, "keep_aspect_ratio": False}, (32, 32)),
            ({"width": 20, "keep_aspect_ratio": False}, (20, 32)),
        )
        for options, expected in cases:
            with self.subTest(options):
                res = self.convert(source, "png", **options)
                self.assertTrue(res["success"], msg=res.get("error"))
                self.assertQuadrants(res["output_path"], tolerance=30, size=expected)

    def test_input_formats_jxl_tiff_jfif_webp_convert_back_to_png(self):
        with Image.open(FIXTURE) as fixture:
            rgb = fixture.convert("RGB")
            sources = {}
            jxl = self.root / "CANARY_TEST_in.jxl"
            jxl.write_bytes(imagecodecs.jpegxl_encode(np.asarray(rgb), lossless=True))
            sources["jxl"] = (jxl, 2)
            for fmt, ext, kwargs, tolerance in (
                ("tiff", "tiff", {"format": "TIFF"}, 0),
                ("jfif", "jfif", {"format": "JPEG", "quality": 95}, 30),
                ("webp", "webp", {"format": "WEBP", "lossless": True}, 0),
            ):
                path = self.root / f"CANARY_TEST_in.{ext}"
                rgb.save(path, **kwargs)
                sources[fmt] = (path, tolerance)
        for fmt, (path, tolerance) in sources.items():
            with self.subTest(fmt):
                self.assertEqual(self.api.detect_format(str(path))["format"], fmt)
                # Détection par signature : le contenu prime sur une extension trompeuse.
                disguised = path.with_name(f"CANARY_TEST_{fmt}_deguise.png")
                disguised.write_bytes(path.read_bytes())
                detection = self.api.detect_format(str(disguised))
                self.assertEqual((detection["format"], detection["mismatch"]), (fmt, True))
                res = self.convert(path, "png")
                self.assertTrue(res["success"], msg=res.get("error"))
                self.assertQuadrants(res["output_path"], tolerance=tolerance, size=(48, 48))

    def test_heic_input_converts_back_to_png(self):
        # Écrit avec l'API de pillow_heif, sans enregistrer de greffon Pillow :
        # la lecture prouve que le convertisseur a bien enregistré le sien.
        import pillow_heif

        path = self.root / "CANARY_TEST_in.heic"
        try:
            with Image.open(FIXTURE) as fixture:
                pillow_heif.from_pillow(fixture.convert("RGB")).save(str(path), quality=-1)  # sans perte
        except (OSError, ValueError, RuntimeError) as exc:
            self.skipTest(f"Encodeur HEIF indisponible ici : {exc}")
        self.assertEqual(self.api.detect_format(str(path))["format"], "heic")
        res = self.convert(path, "png")
        self.assertTrue(res["success"], msg=res.get("error"))
        self.assertQuadrants(res["output_path"], tolerance=4, size=(48, 48))

    def test_svg_renders_its_shapes_and_honours_dpi(self):
        svg = self.root / "CANARY_TEST_quadrants.svg"
        rects = "".join(
            f'<rect x="{x}" y="{y}" width="20" height="20" fill="rgb{color}"/>'
            for (x, y), color in zip(((0, 0), (20, 0), (0, 20), (20, 20)), QUADRANTS)
        )
        svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">{rects}</svg>',
                       encoding="utf-8")
        for dpi, size in ((72, (40, 40)), (144, (80, 80))):
            with self.subTest(dpi=dpi):
                res = self.convert(svg, "png", dpi=dpi)
                self.assertTrue(res["success"], msg=res.get("error"))
                self.assertQuadrants(res["output_path"], tolerance=2, size=size)


class TestM5PdfExports(_PixelCase):

    def _pdf(self, **kwargs) -> Path:
        path = self.root / "CANARY_TEST_doc.pdf"
        path.write_bytes(_minimal_pdf(**kwargs))
        return path

    def test_pdf_dpi_scales_the_rendered_page(self):
        pdf = self._pdf(media_box=(0, 0, 595, 842))
        for dpi, expected in ((72, (595, 842)), (144, (1190, 1684))):
            with self.subTest(dpi=dpi):
                res = self.convert(pdf, "png", dpi=dpi)
                self.assertTrue(res["success"], msg=res.get("error"))
                with Image.open(res["output_path"]) as img:
                    self.assertTrue(all(abs(a - e) <= 1 for a, e in zip(img.size, expected)), msg=img.size)

    def test_three_page_pdf_exports_one_file_per_page_with_shared_suffix(self):
        pdf = self._pdf(media_box=(0, 0, 100, 100), pages=3)
        res = self.convert(pdf, "png", dpi=72)
        self.assertTrue(res["success"], msg=res.get("error"))
        self.assertEqual(res["output_name"], "CANARY_TEST_doc_converted_page_1.png")
        expected = {f"CANARY_TEST_doc_converted_page_{n}.png" for n in (1, 2, 3)}
        self.assertEqual({p.name for p in self.out_dir.iterdir()}, expected)
        for path in self.out_dir.iterdir():
            with Image.open(path) as img:
                self.assertEqual(img.size, (100, 100))

        # Deuxième export : un seul suffixe pour toute la conversion.
        again = self.convert(pdf, "png", dpi=72)
        self.assertTrue(again["success"], msg=again.get("error"))
        self.assertEqual(again["output_name"], "CANARY_TEST_doc_converted_2_page_1.png")
        self.assertEqual(len(list(self.out_dir.iterdir())), 6)

    def test_pdf_to_html_wraps_each_page_and_line(self):
        txt = self.root / "CANARY_TEST_lignes.txt"
        txt.write_text("CANARY_TEST_LIGNE_1\nCANARY_TEST_LIGNE_2 contact@example.test\n", encoding="utf-8")
        res_pdf = self.convert(txt, "pdf")
        self.assertTrue(res_pdf["success"], msg=res_pdf.get("error"))
        res_html = self.api.convert_single_file(res_pdf["output_path"], "html", output_dir=str(self.out_dir))
        self.assertTrue(res_html["success"], msg=res_html.get("error"))
        html_text = Path(res_html["output_path"]).read_text(encoding="utf-8")
        self.assertIn('<section class="pdf-page" data-page="1">', html_text)
        self.assertIn("<p>CANARY_TEST_LIGNE_1</p>", html_text)
        self.assertIn("<p>CANARY_TEST_LIGNE_2 contact@example.test</p>", html_text)


if __name__ == "__main__":
    unittest.main()
