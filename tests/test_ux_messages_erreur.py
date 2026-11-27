"""Correctif UX 4 (Majeur) : messages d'erreur en français clair, sans chemin.

Chaque échec affiché à l'écran donne une cause probable et une action, en
français, avec au plus le nom du fichier. Le détail technique brut (souvent en
anglais) ne part que dans le journal de débogage « file_transformer ».

Données exclusivement fictives (CANARY_TEST_).
"""

import errno
import io
import os
import re
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import imagecodecs
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from securite_outils import _TempCase  # noqa: E402

from converters.image_converter import ImageConverter  # noqa: E402

# Fragments de messages bruts des bibliothèques (Pillow, PDFium, lxml, resvg, imagecodecs).
RAW_MARKERS = (
    "truncated", "cannot identify", "decoder object", "JxlDecoder", "Failed to load", "PDFium",
    "has no attribute", "unclosed token", "decompression bomb", "exceeds limit",
    "invalid size", "Traceback", "Errno", "Permission denied", "No space",
)
ACTIONS = ("Ouvrez", "Réessayez", "Choisissez", "Retirez", "Réduisez", "Réenregistrez",
           "Renommez", "Ajoutez", "Enregistrez", "Fermez", "Libérez", "Exportez")
PRIVATE = "C:\\Users\\CANARY_TEST_prive"


def _bytes(img, fmt):
    buffer = io.BytesIO()
    img.save(buffer, format=fmt)
    return buffer.getvalue()


class _MessagesCase(_TempCase):

    def assertFriendly(self, res, name=None):
        self.assertFalse(res["success"])
        message = res["error"]
        self.assertTrue(message.strip(), msg="Message vide")
        for marker in RAW_MARKERS:
            self.assertNotIn(marker.lower(), message.lower(), msg=f"Message brut : {message}")
        self.assertTrue(any(action in message for action in ACTIONS), msg=f"Aucune action proposée : {message}")
        for directory in (str(self.root), str(self.out_dir), PRIVATE, "C:\\", "/tmp/", "/home/"):
            self.assertNotIn(directory, message, msg=f"Chemin affiché : {message}")
        if name:
            self.assertIn(name, message)
        return message


class TestFichiersAbimes(_MessagesCase):

    def _file(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_fichiers_abimes_message_clair_avec_nom_et_action(self):
        noise = Image.effect_noise((160, 160), 60).convert("RGB")
        docx_buffer = io.BytesIO()
        with zipfile.ZipFile(docx_buffer, "w") as zf:
            zf.writestr("[Content_Types].xml", "<x/>")
            zf.writestr("word/document.xml", "<CANARY_TEST_casse")
        cases = [
            ("CANARY_TEST_tronque.png", _bytes(noise, "PNG")[:3000], "webp"),
            ("CANARY_TEST_casse.png", b"\x89PNG\r\n\x1a\n" + b"CANARY_TEST_" * 10, "webp"),
            ("CANARY_TEST_tronque.jpg", _bytes(noise, "JPEG")[:2000], "png"),
            ("CANARY_TEST_tronque.webp", _bytes(noise, "WEBP")[:300], "png"),
            ("CANARY_TEST_tronque.jxl", bytes(imagecodecs.jpegxl_encode(np.asarray(noise)))[:200], "png"),
            ("CANARY_TEST_casse.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><rect', "png"),
            ("CANARY_TEST_vide.svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0"></svg>', "png"),
            ("CANARY_TEST_tronque.pdf", b"%PDF-1.4\n1 0 obj<<>>\n", "png"),
            ("CANARY_TEST_casse.docx", docx_buffer.getvalue(), "pdf"),
        ]
        for name, data, target in cases:
            with self.subTest(name):
                with self.assertLogs("file_transformer", level="DEBUG") as logs:
                    res = self.convert(self._file(name, data), target)
                self.assertFriendly(res, name)
                self.assertTrue(logs.output, msg="Le détail technique doit rester dans le journal de débogage")
        self.assertEqual(list(self.out_dir.iterdir()), [])

    def test_image_trop_grande(self):
        png = self._file("CANARY_TEST_geante.png", _bytes(Image.new("RGB", (100, 100)), "PNG"))
        with mock.patch.object(Image, "MAX_IMAGE_PIXELS", 1000):
            res = self.convert(png, "webp")
        message = self.assertFriendly(res, "CANARY_TEST_geante.png")
        self.assertIn("trop grande", message)

    def test_erreur_inconnue_de_bibliotheque_sans_detail_brut(self):
        png = self._file("CANARY_TEST_inconnue.png", _bytes(Image.new("RGB", (4, 4)), "PNG"))
        with mock.patch.object(ImageConverter, "convert",
                               side_effect=RuntimeError(f"CANARY_TEST internal glitch in {PRIVATE}\\lib.dll")):
            with self.assertLogs("file_transformer", level="DEBUG") as logs:
                res = self.convert(png, "webp")
        message = self.assertFriendly(res, "CANARY_TEST_inconnue.png")
        self.assertNotIn("glitch", message)
        self.assertIn("glitch", "\n".join(logs.output))

    def test_acces_refuse_et_disque_plein(self):
        png = self._file("CANARY_TEST_droits.png", _bytes(Image.new("RGB", (4, 4)), "PNG"))
        target = str(self.out_dir / "CANARY_TEST_droits_converted.webp")
        for error, expected in (
            (PermissionError(errno.EACCES, "Permission denied", target), "Fermez"),
            (OSError(errno.ENOSPC, "No space left on device", target), "Libérez"),
        ):
            with self.subTest(expected):
                with mock.patch.object(ImageConverter, "convert", side_effect=error):
                    res = self.convert(png, "webp")
                message = self.assertFriendly(res)
                self.assertIn(expected, message)
                self.assertRegex(message, r"CANARY_TEST_droits(_converted\.webp|\.png)")


class TestControlesAvantConversion(_MessagesCase):

    def test_nom_reserve_sans_jargon(self):
        res = self.api.convert_single_file("C:\\CANARY_TEST\\NUL.png", "webp")
        message = self.assertFriendly(res)
        self.assertNotIn("périphérique", message)
        self.assertIn("réservé par Windows", message)

    def test_lien_symbolique_en_entree(self):
        png = self.root / "CANARY_TEST_lien.png"
        with Image.new("RGB", (4, 4)) as img:
            img.save(png, format="PNG")
        with mock.patch("os.path.islink", return_value=True):
            res = self.convert(png, "webp")
        self.assertIn("raccourci", self.assertFriendly(res))

    def test_format_non_pris_en_charge_propose_une_solution(self):
        path = self.root / "CANARY_TEST_tableur.xlsx"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("[Content_Types].xml", "<x/>")
            zf.writestr("xl/workbook.xml", "<workbook/>")
        message = self.assertFriendly(self.convert(path, "pdf"))
        self.assertIn("PDF", message)

    def test_format_inconnu_et_sortie_invalide(self):
        unknown = self.root / "CANARY_TEST_inconnu.bin"
        unknown.write_bytes(b"\x00\x01CANARY_TEST_\x02\x03" * 8)
        self.assertFriendly(self.convert(unknown, "pdf"))
        png = self.root / "CANARY_TEST_sortie.png"
        with Image.new("RGB", (4, 4)) as img:
            img.save(png, format="PNG")
        for target in ("exe", "../x", "pdf"):
            with self.subTest(target):
                self.assertFriendly(self.convert(png, target))

    def test_destination_disparue(self):
        png = self.root / "CANARY_TEST_dest.png"
        with Image.new("RGB", (4, 4)) as img:
            img.save(png, format="PNG")
        res = self.api.convert_single_file(str(png), "webp", output_dir=str(self.root / "CANARY_TEST_absent"))
        self.assertFriendly(res)

    def test_garde_fous_docx_expliques_avec_action(self):
        # Les mots-clés vérifiés par test_garde_fous_m6 restent présents.
        path = self.root / "CANARY_TEST_bombe.docx"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", "<x/>")
            zf.writestr("word/media/CANARY_TEST_zeros.bin", b"\0" * (2 * 1024 * 1024))
        message = self.assertFriendly(self.convert(path, "txt"), "Ratio de compression suspect")
        self.assertIn("Réenregistrez", message)

    def test_pdf_trop_de_pages_propose_une_alternative(self):
        from securite_outils import _minimal_pdf
        pdf = self.root / "CANARY_TEST_long.pdf"
        pdf.write_bytes(_minimal_pdf(media_box=(0, 0, 20, 20), pages=501))
        message = self.assertFriendly(self.convert(pdf, "png", dpi=72), "pages")
        self.assertIn("TXT", message)


if __name__ == "__main__":
    unittest.main()
