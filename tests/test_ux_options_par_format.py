"""Correctif UX 1 (Critique) : zéro option morte.

Le test croise la table de l'interface (src/frontend/app.js, exécutée par Node)
avec le moteur Python réel (AppAPI.convert_single_file) : chaque format de
sortie proposé pour un format d'entrée doit aboutir, et aucune sortie qui
fonctionne ne doit manquer. Une option morte ne peut donc plus revenir sans
faire échouer ce test.

Données exclusivement fictives (CANARY_TEST_).
"""

import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import docx
import imagecodecs
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from securite_outils import REPO_ROOT, _TempCase, _minimal_pdf  # noqa: E402

import format_detector  # noqa: E402
from converters.document_converter import DocumentConverter  # noqa: E402
from converters.image_converter import ImageConverter  # noqa: E402

NODE = shutil.which("node")
TABLES_SCRIPT = REPO_ROOT / "tests" / "frontend-tables.cjs"

# Toutes les valeurs de sortie que l'interface peut proposer (liste globale comprise).
ALL_CANDIDATES = sorted({"pdf", "html", "txt", "md", "png", "jpg", "jfif", "webp", "jxl", "ico", "gif", "bmp"})


def frontend_targets(sources):
    """Formats proposés par app.js pour chaque (catégorie, format) d'entrée."""
    if not NODE:
        if os.environ.get("CI"):
            raise AssertionError("Node.js est requis pour croiser app.js avec le moteur.")
        raise unittest.SkipTest("Node.js absent : croisement app.js / moteur impossible ici.")
    proc = subprocess.run(
        [NODE, str(TABLES_SCRIPT), json.dumps(sources)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    if proc.returncode != 0:
        raise AssertionError(f"frontend-tables.cjs a échoué : {proc.stderr}")
    return {(r["category"], r["format"]): r["targets"] for r in json.loads(proc.stdout)}


def _rgb(size=(12, 10)):
    return Image.new("RGB", size, (30, 160, 90))


def _save_bytes(img, fmt, **kw):
    buffer = io.BytesIO()
    img.save(buffer, format=fmt, **kw)
    return buffer.getvalue()


def _jpeg_without_jfif():
    data = _save_bytes(_rgb(), "JPEG")
    assert data[2:4] == b"\xff\xe0"  # segment APP0 « JFIF » écrit par Pillow
    length = int.from_bytes(data[4:6], "big")
    return data[:2] + data[4 + length:]


def _heic():
    import pillow_heif
    pillow_heif.register_heif_opener()
    return _save_bytes(_rgb(), "HEIF")


IMAGE_FIXTURES = {
    "png": lambda: _save_bytes(_rgb(), "PNG"),
    "jfif": lambda: _save_bytes(_rgb(), "JPEG"),
    "jpeg": _jpeg_without_jfif,
    "webp": lambda: _save_bytes(_rgb(), "WEBP"),
    "gif": lambda: _save_bytes(_rgb(), "GIF"),
    "bmp": lambda: _save_bytes(_rgb(), "BMP"),
    "ico": lambda: _save_bytes(_rgb((16, 16)), "ICO"),
    "tiff": lambda: _save_bytes(_rgb(), "TIFF"),
    "heic": _heic,
    "jxl": lambda: bytes(imagecodecs.jpegxl_encode(np.full((10, 12, 3), 120, np.uint8))),
    "svg": lambda: (b'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="10">'
                    b'<rect width="12" height="10" fill="#1e9f5a"/></svg>'),
}


def _docx_bytes():
    document = docx.Document()
    document.add_paragraph("CANARY_TEST_ paragraphe")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


DOCUMENT_FIXTURES = {
    "pdf": lambda: _minimal_pdf(media_box=(0, 0, 60, 60)),
    "docx": _docx_bytes,
    "md": lambda: "# CANARY_TEST_ titre\n\nTexte fictif.\n".encode("utf-8"),
    "html": lambda: b"<!DOCTYPE html><html><body><p>CANARY_TEST_ page</p></body></html>",
    "txt": lambda: b"CANARY_TEST_ texte brut\n",
}


class TestZeroOptionMorte(_TempCase):

    def _fixture(self, fmt, factory):
        path = self.root / f"CANARY_TEST_source_{fmt}.{format_detector.FORMATS[fmt]['ext'].lstrip('.')}"
        path.write_bytes(factory())
        detection = format_detector.detect(str(path))
        self.assertEqual(detection["format"], fmt, msg=f"Fixture {fmt} mal détectée : {detection}")
        return path, detection["category"]

    def _engine_outputs(self, path):
        """Sorties que le moteur réel produit vraiment pour ce fichier."""
        working = set()
        for target in ALL_CANDIDATES:
            out = self.root / f"out_{path.stem}_{target}"
            out.mkdir()
            res = self.api.convert_single_file(str(path), target, options=None, output_dir=str(out))
            if res["success"]:
                working.add(target)
        return working

    def _check(self, fixtures):
        sources = {}
        for fmt, factory in fixtures.items():
            with self.subTest(fixture=fmt):
                try:
                    sources[fmt] = self._fixture(fmt, factory)
                except Exception as exc:  # encodeur absent sur cette machine
                    self.skipTest(f"Impossible de créer la fixture {fmt} : {exc}")
        offered = frontend_targets([{"category": cat, "format": fmt} for fmt, (_, cat) in sources.items()])
        dead_total = 0
        for fmt, (path, category) in sources.items():
            proposed = offered[(category, fmt)]
            with self.subTest(source=fmt):
                self.assertEqual(len(proposed), len(set(proposed)), msg=f"Doublons pour {fmt} : {proposed}")
                working = self._engine_outputs(path)
                dead = sorted(set(proposed) - working)
                hidden = sorted(working - set(proposed))
                dead_total += len(dead)
                self.assertEqual(dead, [], msg=f"Options mortes proposées pour {fmt} : {dead}")
                self.assertEqual(hidden, [], msg=f"Sorties fonctionnelles absentes de l'interface pour {fmt} : {hidden}")
        return dead_total

    def test_documents_chaque_option_proposee_aboutit_et_aucune_ne_manque(self):
        self._check(DOCUMENT_FIXTURES)

    def test_images_chaque_option_proposee_aboutit_et_aucune_ne_manque(self):
        self._check(IMAGE_FIXTURES)

    def test_tous_les_formats_d_entree_pris_en_charge_ont_une_table(self):
        supported = [(info["category"], fmt) for fmt, info in format_detector.FORMATS.items() if info["supported"]]
        self.assertEqual(set(fmt for _, fmt in supported), set(IMAGE_FIXTURES) | set(DOCUMENT_FIXTURES),
                         msg="Nouveau format d'entrée : ajoutez sa fixture et sa table de sorties.")
        offered = frontend_targets([{"category": c, "format": f} for c, f in supported])
        for key in supported:
            with self.subTest(source=key):
                self.assertTrue(offered[key], msg=f"Aucune sortie proposée pour {key}")

    def test_format_non_pris_en_charge_ou_inconnu_sans_option(self):
        unsupported = [{"category": info["category"], "format": fmt}
                       for fmt, info in format_detector.FORMATS.items() if not info["supported"]]
        unsupported.append({"category": "unknown", "format": None})
        offered = frontend_targets(unsupported)
        for key, targets in offered.items():
            with self.subTest(source=key):
                self.assertEqual(targets, [], msg=f"Options proposées pour un format non pris en charge : {key}")

    def test_table_du_moteur_alignee_sur_les_convertisseurs(self):
        """La table publique du moteur reste un sous-ensemble des sorties autorisées."""
        table = DocumentConverter.OUTPUTS_BY_SOURCE
        self.assertEqual(set(table), {"pdf", "docx", "md", "html", "txt"})
        for source, outputs in table.items():
            with self.subTest(source=source):
                self.assertTrue(set(outputs) <= DocumentConverter.SUPPORTED_OUTPUTS)
        self.assertTrue({"png", "jpg", "jfif", "webp", "jxl", "ico", "gif", "bmp"} <= ImageConverter.SUPPORTED_OUTPUTS)

    def test_paire_non_proposee_refusee_avant_conversion_avec_message_clair(self):
        html_file = self.root / "CANARY_TEST_page.html"
        html_file.write_bytes(DOCUMENT_FIXTURES["html"]())
        res = self.convert(html_file, "png")
        self.assertFalse(res["success"])
        self.assertIn("HTML", res["error"])
        self.assertIn("PNG", res["error"])
        self.assertNotIn("non supportée", res["error"])  # ancien message brut du moteur
        self.assertEqual(list(self.out_dir.iterdir()), [], msg="Aucun fichier temporaire ne doit rester")


if __name__ == "__main__":
    unittest.main()
