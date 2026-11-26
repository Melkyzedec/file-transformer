"""Outils partagés par les tests de sécurité de la tranche 1 (C1, C2, M1, M2, M3, M4).

Chaque test vérifie un comportement observable (pixels rendus, connexions
tentées, balises produites, appels au décodeur) plutôt qu'un détail
d'implémentation. Données exclusivement fictives (CANARY_TEST_ / @example.test).
"""

import base64
import html as html_lib
import io
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pypdfium2 as pdfium
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "src" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app_api import AppAPI  # noqa: E402
from converters.document_converter import DocumentConverter  # noqa: E402

__all__ = [
    "REPO_ROOT", "AppAPI", "DocumentConverter", "GREEN", "RED", "XSS_PAYLOAD",
    "_save_solid_png", "_solid_png_data_uri", "_count_pdf_pixels", "_minimal_pdf",
    "_active_html_findings", "_TempCase",
]

GREEN = (0, 255, 0)
RED = (255, 0, 0)
XSS_PAYLOAD = '<script>alert("CANARY_TEST_XSS")</script><img src=x onerror=alert(1)>'


# --- Outils ---------------------------------------------------------------

def _save_solid_png(path: Path, color, size=(40, 40)) -> Path:
    with Image.new("RGB", size, color) as img:
        img.save(path, format="PNG")
    return path


def _solid_png_data_uri(color, size=(40, 40)) -> str:
    buffer = io.BytesIO()
    with Image.new("RGB", size, color) as img:
        img.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _count_pdf_pixels(pdf_path: Path, color, tolerance: int = 60) -> int:
    """Rend toutes les pages et compte les pixels à moins de `tolerance` de `color`."""
    doc = pdfium.PdfDocument(str(pdf_path))
    total = 0
    try:
        for index in range(len(doc)):
            page = doc[index]
            try:
                bitmap = page.render(scale=1)
                try:
                    pixels = np.asarray(bitmap.to_pil().convert("RGB"), dtype=np.int16)
                finally:
                    bitmap.close()
            finally:
                page.close()
            close = np.all(np.abs(pixels - np.array(color, dtype=np.int16)) < tolerance, axis=-1)
            total += int(close.sum())
    finally:
        doc.close()
    return total


def _minimal_pdf(media_box=(0, 0, 595, 842), pages=1) -> bytes:
    """PDF valide minimal : `pages` pages vides de format `media_box` (points)."""
    kids = " ".join(f"{3 + i} 0 R" for i in range(pages))
    box = " ".join(str(v) for v in media_box)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode(),
    ]
    objects += [f"<< /Type /Page /Parent 2 0 R /MediaBox [{box}] >>".encode()] * pages
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


class _TagCollector(HTMLParser):
    """Relève les balises et attributs réellement produits dans un HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag.lower(), [(k.lower(), v or "") for k, v in attrs]))

    handle_startendtag = handle_starttag


def _active_html_findings(html_text: str) -> list:
    """Liste les éléments ou attributs HTML capables d'exécuter du code."""
    collector = _TagCollector()
    collector.feed(html_text)
    findings = []
    for tag, attrs in collector.tags:
        if tag in ("script", "iframe", "object", "embed", "base", "meta", "link"):
            if tag == "meta" and all(k == "charset" for k, _ in attrs):
                continue
            findings.append(f"<{tag}>")
        for key, value in attrs:
            if key.startswith("on"):
                findings.append(f"{tag}[{key}]")
            normalized = "".join(ch for ch in html_lib.unescape(value) if ch > " ").lower()
            if key in ("href", "src", "action", "formaction", "xlink:href") and (
                normalized.startswith(("javascript:", "vbscript:", "data:text"))
            ):
                findings.append(f"{tag}[{key}={value}]")
    return findings


class _TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory(prefix="canary_tranche1_")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.out_dir = self.root / "out"
        self.out_dir.mkdir()
        self.api = AppAPI()

    def convert(self, path, target, **options):
        return self.api.convert_single_file(str(path), target, options=options or None,
                                            output_dir=str(self.out_dir))
