"""Suite de tests backend (FT-01 & FT-02) pour File Transformer.

100 % isolée en TemporaryDirectory, 0 USD, sans dépendance externe à pytest.
Données exclusivement fictives (CANARY_TEST_ / @example.test).
"""

import gzip
import io
import os
import re
import shutil
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import docx
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "src" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import format_detector  # noqa: E402
from app_api import AppAPI  # noqa: E402
from converters.document_converter import DocumentConverter  # noqa: E402
from converters.image_converter import ImageConverter  # noqa: E402


class _FakeWindow:
    """Fenêtre pywebview factice pour tester select_output_folder."""

    def __init__(self, dialog_result):
        self._dialog_result = dialog_result

    def create_file_dialog(self, *_args, **_kwargs):
        return self._dialog_result


def _prepare_sample_png(dest_path: Path) -> Path:
    """Copie tests/fixtures/exemple.png si présente, sinon génère un vrai PNG RGBA."""
    fixture = REPO_ROOT / "tests" / "fixtures" / "exemple.png"
    if fixture.is_file():
        shutil.copy2(fixture, dest_path)
        return dest_path
    img = Image.new("RGBA", (64, 64), (32, 128, 224, 200))
    try:
        img.save(dest_path, format="PNG")
    finally:
        img.close()
    return dest_path


def _expected_explorer_path() -> str:
    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    return os.path.normpath(os.path.join(system_root, "explorer.exe"))


class TestFT01OpenFolderSecurity(unittest.TestCase):
    """FT-01 : blocage shell=True, chemin absolu explorer.exe, liste blanche de session."""

    def setUp(self):
        self._tmp = TemporaryDirectory(prefix="canary_ft01_")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.api = AppAPI()
        # Portable hors Windows : un explorer.exe factice sous un SystemRoot
        # temporaire. Popen est toujours remplacé par un mock dans ces tests.
        fake_system_root = self.root / "CANARY_TEST_SystemRoot"
        fake_system_root.mkdir()
        (fake_system_root / "explorer.exe").write_bytes(b"CANARY_TEST")
        patcher = mock.patch.dict(os.environ, {"SystemRoot": str(fake_system_root)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_app_api_source_never_uses_shell_true(self):
        source = (BACKEND_DIR / "app_api.py").read_text(encoding="utf-8")
        self.assertNotIn("shell=True", source)

    def test_open_folder_uses_absolute_explorer_without_shell_for_converted_file(self):
        src_png = _prepare_sample_png(self.root / "CANARY_TEST_source.png")
        out_dir = self.root / "out"
        out_dir.mkdir()

        res = self.api.convert_single_file(str(src_png), "webp", output_dir=str(out_dir))
        self.assertTrue(res["success"], msg=res.get("error"))
        converted = Path(res["output_path"]).resolve()

        with mock.patch("app_api.subprocess.Popen") as mock_popen, \
             mock.patch("app_api.subprocess.run") as mock_run:
            opened = self.api.open_folder(str(converted))

        self.assertTrue(opened)
        mock_run.assert_not_called()
        mock_popen.assert_called_once()
        call_args, call_kwargs = mock_popen.call_args
        cmd = call_args[0]
        self.assertIsInstance(cmd, list)
        self.assertFalse(call_kwargs.get("shell", False))
        self.assertEqual(os.path.normcase(cmd[0]), os.path.normcase(_expected_explorer_path()))
        self.assertTrue(os.path.isabs(cmd[0]))
        self.assertEqual(cmd[1], f"/select,{converted}")

    def test_open_folder_rejects_unauthorized_paths(self):
        unauth_file = self.root / "CANARY_TEST_UNAUTHORIZED.exe"
        unauth_file.write_bytes(b"CANARY_TEST_BINARY")
        unauth_dir = self.root / "CANARY_TEST_UNAUTHORIZED_DIR"
        unauth_dir.mkdir()

        with mock.patch("app_api.subprocess.Popen") as mock_popen, \
             mock.patch("app_api.subprocess.run") as mock_run:
            self.assertFalse(self.api.open_folder(str(unauth_file)))
            self.assertFalse(self.api.open_folder(str(unauth_dir)))
            self.assertFalse(self.api.open_folder(""))
            self.assertFalse(self.api.open_folder(None))

        mock_popen.assert_not_called()
        mock_run.assert_not_called()

    def test_open_folder_allows_directory_from_select_output_folder(self):
        chosen_dir = self.root / "CANARY_TEST_selected_dir"
        chosen_dir.mkdir()
        self.api.set_window(_FakeWindow([str(chosen_dir)]))

        selected = self.api.select_output_folder()
        self.assertEqual(selected, str(chosen_dir))

        with mock.patch("app_api.subprocess.Popen") as mock_popen, \
             mock.patch("app_api.subprocess.run") as mock_run:
            opened = self.api.open_folder(selected)

        self.assertTrue(opened)
        mock_run.assert_not_called()
        mock_popen.assert_called_once()
        call_args, call_kwargs = mock_popen.call_args
        cmd = call_args[0]
        self.assertIsInstance(cmd, list)
        self.assertFalse(call_kwargs.get("shell", False))
        self.assertEqual(os.path.normcase(cmd[0]), os.path.normcase(_expected_explorer_path()))
        self.assertEqual(cmd[1], str(chosen_dir.resolve()))

    def test_open_folder_handles_shell_metacharacters_safely(self):
        tricky_dir = self.root / "CANARY_TEST_a & b %OS% 'quote'"
        tricky_dir.mkdir()
        src_png = _prepare_sample_png(tricky_dir / "CANARY_TEST_file & %TEMP% 'q'.png")

        res = self.api.convert_single_file(str(src_png), "webp", output_dir=str(tricky_dir))
        self.assertTrue(res["success"], msg=res.get("error"))
        converted = Path(res["output_path"]).resolve()

        with mock.patch("app_api.subprocess.Popen") as mock_popen, \
             mock.patch("app_api.subprocess.run") as mock_run:
            opened = self.api.open_folder(str(converted))

        self.assertTrue(opened)
        mock_run.assert_not_called()
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        self.assertIsInstance(cmd, list)
        self.assertFalse(mock_popen.call_args[1].get("shell", False))
        self.assertEqual(cmd[1], f"/select,{converted}")
        self.assertIn("&", cmd[1])
        self.assertIn("%TEMP%", cmd[1])


class TestFT02FormatDetection(unittest.TestCase):
    """FT-02 : détection réelle de format par contenu vs extension."""

    def setUp(self):
        self._tmp = TemporaryDirectory(prefix="canary_ft02_det_")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_detect_real_png(self):
        png_path = _prepare_sample_png(self.root / "CANARY_TEST_real.png")
        info = format_detector.detect(str(png_path))
        self.assertEqual(info["format"], "png")
        self.assertEqual(info["category"], "image")
        self.assertEqual(info["method"], "signature")
        self.assertTrue(info["supported"])
        self.assertFalse(info["mismatch"])

    def test_detect_fake_png_containing_plain_text_and_html(self):
        fake_txt = self.root / "CANARY_TEST_fake_text.png"
        fake_txt.write_text("CANARY_TEST plain text disguised as png\n", encoding="utf-8")
        info_txt = format_detector.detect(str(fake_txt))
        self.assertEqual(info_txt["format"], "txt")
        self.assertEqual(info_txt["category"], "document")
        self.assertEqual(info_txt["method"], "content")
        self.assertTrue(info_txt["supported"])

        fake_html = self.root / "CANARY_TEST_fake_html.png"
        fake_html.write_text("<!DOCTYPE html><html><body>CANARY_TEST</body></html>", encoding="utf-8")
        info_html = format_detector.detect(str(fake_html))
        self.assertEqual(info_html["format"], "html")
        self.assertEqual(info_html["category"], "document")
        self.assertTrue(info_html["mismatch"])

    def test_detect_pdf_docx_svg_md_html(self):
        # PDF
        pdf_path = self.root / "CANARY_TEST_doc.pdf"
        DocumentConverter._html_string_to_pdf(
            "<!DOCTYPE html><html><body><p>CANARY_TEST PDF</p></body></html>",
            str(pdf_path),
        )
        info_pdf = format_detector.detect(str(pdf_path))
        self.assertEqual(info_pdf["format"], "pdf")
        self.assertEqual(info_pdf["method"], "signature")
        self.assertTrue(info_pdf["supported"])

        # DOCX
        docx_path = self.root / "CANARY_TEST_doc.docx"
        document = docx.Document()
        document.add_paragraph("CANARY_TEST_DOCX contact@example.test")
        document.save(str(docx_path))
        info_docx = format_detector.detect(str(docx_path))
        self.assertEqual(info_docx["format"], "docx")
        self.assertEqual(info_docx["method"], "signature")
        self.assertTrue(info_docx["supported"])

        # SVG
        svg_path = self.root / "CANARY_TEST_icon.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">'
            '<rect width="32" height="32" fill="#123456"/></svg>',
            encoding="utf-8",
        )
        info_svg = format_detector.detect(str(svg_path))
        self.assertEqual(info_svg["format"], "svg")
        self.assertEqual(info_svg["category"], "image")
        self.assertTrue(info_svg["supported"])

        # Markdown
        md_path = self.root / "CANARY_TEST_notes.md"
        md_path.write_text("# CANARY_TEST\n\n- item 1\n- **bold**\n", encoding="utf-8")
        info_md = format_detector.detect(str(md_path))
        self.assertEqual(info_md["format"], "md")
        self.assertEqual(info_md["category"], "document")
        self.assertTrue(info_md["supported"])

        # HTML
        html_path = self.root / "CANARY_TEST_page.html"
        html_path.write_text("<!DOCTYPE html><html><body><h1>CANARY_TEST</h1></body></html>", encoding="utf-8")
        info_html = format_detector.detect(str(html_path))
        self.assertEqual(info_html["format"], "html")
        self.assertEqual(info_html["category"], "document")
        self.assertEqual(info_html["method"], "content")
        self.assertTrue(info_html["supported"])


class TestFT02BackendConversionsE2E(unittest.TestCase):
    """FT-02 : conversions réelles E2E images, documents, collisions et fichiers corrompus."""

    def setUp(self):
        self._tmp = TemporaryDirectory(prefix="canary_ft02_e2e_")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.api = AppAPI()

    def test_image_png_conversions_and_collision_handling(self):
        src_png = _prepare_sample_png(self.root / "CANARY_TEST_img.png")
        out_dir = self.root / "img_out"
        out_dir.mkdir()

        expected_pil_formats = {
            "webp": "WEBP",
            "jpg": "JPEG",
            "ico": "ICO",
            "bmp": "BMP",
            "gif": "GIF",
        }
        for target, pil_fmt in expected_pil_formats.items():
            res = self.api.convert_single_file(str(src_png), target, output_dir=str(out_dir))
            self.assertTrue(res["success"], msg=f"PNG->{target} failed: {res.get('error')}")
            out_path = Path(res["output_path"])
            self.assertTrue(out_path.is_file())
            self.assertGreater(out_path.stat().st_size, 0)
            with Image.open(out_path) as img:
                self.assertEqual(img.format, pil_fmt)

        # Collision handling: second conversion to webp must produce *_converted_2.webp
        res_dup = self.api.convert_single_file(str(src_png), "webp", output_dir=str(out_dir))
        self.assertTrue(res_dup["success"], msg=res_dup.get("error"))
        self.assertEqual(res_dup["output_name"], "CANARY_TEST_img_converted_2.webp")
        dup_path = Path(res_dup["output_path"])
        self.assertTrue(dup_path.is_file())
        with Image.open(dup_path) as img:
            self.assertEqual(img.format, "WEBP")

    def test_document_txt_md_html_conversions_and_external_resource_blocking(self):
        out_dir = self.root / "doc_out"
        out_dir.mkdir()

        # TXT -> PDF & HTML
        txt_path = self.root / "CANARY_TEST_note.txt"
        txt_path.write_text("CANARY_TEST_TXT ligne 1 <escaped>\nuser@example.test\n", encoding="utf-8")

        res_txt_pdf = self.api.convert_single_file(str(txt_path), "pdf", output_dir=str(out_dir))
        self.assertTrue(res_txt_pdf["success"], msg=res_txt_pdf.get("error"))
        self.assertTrue(Path(res_txt_pdf["output_path"]).read_bytes().startswith(b"%PDF"))

        res_txt_html = self.api.convert_single_file(str(txt_path), "html", output_dir=str(out_dir))
        self.assertTrue(res_txt_html["success"], msg=res_txt_html.get("error"))
        html_out = Path(res_txt_html["output_path"]).read_text(encoding="utf-8")
        self.assertIn("CANARY_TEST_TXT", html_out)
        self.assertIn("&lt;escaped&gt;", html_out)

        # MD -> HTML & PDF
        md_path = self.root / "CANARY_TEST_doc.md"
        md_path.write_text("# CANARY_TEST_MD\n\n- point **important**\n", encoding="utf-8")

        res_md_html = self.api.convert_single_file(str(md_path), "html", output_dir=str(out_dir))
        self.assertTrue(res_md_html["success"], msg=res_md_html.get("error"))
        md_html_text = Path(res_md_html["output_path"]).read_text(encoding="utf-8")
        self.assertIn("<strong>important</strong>", md_html_text)

        res_md_pdf = self.api.convert_single_file(str(md_path), "pdf", output_dir=str(out_dir))
        self.assertTrue(res_md_pdf["success"], msg=res_md_pdf.get("error"))
        self.assertTrue(Path(res_md_pdf["output_path"]).read_bytes().startswith(b"%PDF"))

        # HTML -> PDF + external/LFI resource blocking verification
        self.assertEqual(
            DocumentConverter._block_external_resource("https://canary.example.test/img.png", ""),
            "",
        )
        self.assertEqual(
            DocumentConverter._block_external_resource("file:///nonexistent_canary_test.txt", ""),
            "",
        )

        html_path = self.root / "CANARY_TEST_page.html"
        html_path.write_text(
            "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>"
            "<p>CANARY_TEST_HTML_PDF</p>"
            "<img src='https://canary.example.test/blocked.png'>"
            "<img src='file:///canary_lfi_blocked.png'>"
            "</body></html>",
            encoding="utf-8",
        )
        blocked_uris = []
        original_blocker = DocumentConverter._block_external_resource

        def _spy_blocker(uri, rel):
            blocked_uris.append(uri)
            return original_blocker(uri, rel)

        with mock.patch.object(DocumentConverter, "_block_external_resource", side_effect=_spy_blocker):
            res_html_pdf = self.api.convert_single_file(str(html_path), "pdf", output_dir=str(out_dir))

        self.assertTrue(res_html_pdf["success"], msg=res_html_pdf.get("error"))
        self.assertTrue(Path(res_html_pdf["output_path"]).read_bytes().startswith(b"%PDF"))
        self.assertTrue(
            any("canary.example.test" in u for u in blocked_uris),
            msg=f"Expected external URI to hit link_callback, got: {blocked_uris}",
        )

    def test_document_docx_and_pdf_conversions(self):
        out_dir = self.root / "office_out"
        out_dir.mkdir()

        # DOCX -> TXT, HTML, PDF
        docx_path = self.root / "CANARY_TEST_sample.docx"
        document = docx.Document()
        document.add_paragraph("CANARY_TEST_DOCX_BODY")
        document.add_paragraph("contact@example.test")
        document.save(str(docx_path))

        res_docx_txt = self.api.convert_single_file(str(docx_path), "txt", output_dir=str(out_dir))
        self.assertTrue(res_docx_txt["success"], msg=res_docx_txt.get("error"))
        self.assertIn("CANARY_TEST_DOCX_BODY", Path(res_docx_txt["output_path"]).read_text(encoding="utf-8"))

        res_docx_html = self.api.convert_single_file(str(docx_path), "html", output_dir=str(out_dir))
        self.assertTrue(res_docx_html["success"], msg=res_docx_html.get("error"))
        self.assertIn("<p>CANARY_TEST_DOCX_BODY</p>", Path(res_docx_html["output_path"]).read_text(encoding="utf-8"))

        res_docx_pdf = self.api.convert_single_file(str(docx_path), "pdf", output_dir=str(out_dir))
        self.assertTrue(res_docx_pdf["success"], msg=res_docx_pdf.get("error"))
        generated_pdf = Path(res_docx_pdf["output_path"])
        self.assertTrue(generated_pdf.read_bytes().startswith(b"%PDF"))

        # PDF -> TXT & PNG
        res_pdf_txt = self.api.convert_single_file(str(generated_pdf), "txt", output_dir=str(out_dir))
        self.assertTrue(res_pdf_txt["success"], msg=res_pdf_txt.get("error"))
        extracted = Path(res_pdf_txt["output_path"]).read_text(encoding="utf-8")
        self.assertIn("CANARY_TEST_DOCX_BODY", extracted)

        res_pdf_png = self.api.convert_single_file(str(generated_pdf), "png", output_dir=str(out_dir))
        self.assertTrue(res_pdf_png["success"], msg=res_pdf_png.get("error"))
        pdf_png_path = Path(res_pdf_png["output_path"])
        self.assertTrue(pdf_png_path.is_file())
        with Image.open(pdf_png_path) as img:
            self.assertEqual(img.format, "PNG")
            self.assertGreater(img.width, 0)
            self.assertGreater(img.height, 0)

    def test_corrupted_and_empty_files_fail_cleanly_without_orphan_temp(self):
        out_dir = self.root / "err_out"
        out_dir.mkdir()

        # 0-byte .png
        empty_png = self.root / "CANARY_TEST_empty.png"
        empty_png.write_bytes(b"")
        res_empty = self.api.convert_single_file(str(empty_png), "webp", output_dir=str(out_dir))
        self.assertFalse(res_empty["success"])
        self.assertEqual(list(out_dir.iterdir()), [])

        # Corrupted PNG (valid header, invalid payload)
        corrupt_png = self.root / "CANARY_TEST_corrupt.png"
        corrupt_png.write_bytes(b"\x89PNG\r\n\x1a\nCORRUPTED_CANARY_PAYLOAD")
        res_corrupt_png = self.api.convert_single_file(str(corrupt_png), "webp", output_dir=str(out_dir))
        self.assertFalse(res_corrupt_png["success"])
        self.assertEqual(list(out_dir.iterdir()), [])

        # Corrupted PDF
        corrupt_pdf = self.root / "CANARY_TEST_corrupt.pdf"
        corrupt_pdf.write_bytes(b"%PDF-1.4\nCORRUPTED_CANARY_BODY")
        res_corrupt_pdf = self.api.convert_single_file(str(corrupt_pdf), "txt", output_dir=str(out_dir))
        self.assertFalse(res_corrupt_pdf["success"])
        self.assertEqual(list(out_dir.iterdir()), [])


class TestFT03ResourceLimitsAndBombs(unittest.TestCase):
    """FT-03 : anti-bombes Gzip/ZIP et bornes strictes dpi / width / height."""

    def setUp(self):
        self._tmp = TemporaryDirectory(prefix="canary_ft03_")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.api = AppAPI()

    def test_svgz_gzip_bomb_rejected_before_oom(self):
        bomb_svgz = self.root / "CANARY_TEST_bomb.svgz"
        # 12 Mo de zéros/espaces compressés (~15 Ko sur disque) > plafond 10 Mo
        payload = b"<svg>" + (b" " * (12 * 1024 * 1024)) + b"</svg>"
        with gzip.open(bomb_svgz, "wb", compresslevel=9) as gz:
            gz.write(payload)

        with self.assertRaises((ValueError, RuntimeError)):
            ImageConverter._read_svg_text(str(bomb_svgz))

        out_dir = self.root / "svg_out"
        out_dir.mkdir()
        res = self.api.convert_single_file(str(bomb_svgz), "png", output_dir=str(out_dir))
        self.assertFalse(res["success"])
        self.assertEqual(list(out_dir.iterdir()), [])

    def test_docx_zip_bomb_rejected_before_python_docx(self):
        bomb_docx = self.root / "CANARY_TEST_bomb.docx"
        # Entrée word/document.xml de 60 Mo de blancs (~60 Ko compressé)
        with zipfile.ZipFile(bomb_docx, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("word/document.xml", " " * (60 * 1024 * 1024))

        out_path = self.root / "CANARY_TEST_bomb.txt"
        with mock.patch("converters.document_converter.docx.Document") as mock_doc:
            with self.assertRaises(ValueError):
                DocumentConverter._convert_docx(str(bomb_docx), str(out_path), "txt", {})
            mock_doc.assert_not_called()

    def test_format_detector_zip_mimetype_read_is_bounded(self):
        bomb_zip = self.root / "CANARY_TEST_mime_bomb.zip"
        with zipfile.ZipFile(bomb_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/epub+zip" + (" " * (2 * 1024 * 1024)))

        source = (BACKEND_DIR / "format_detector.py").read_text(encoding="utf-8")
        self.assertNotIn("zf.read('mimetype')", source)
        self.assertNotIn('zf.read("mimetype")', source)

        info = format_detector.detect(str(bomb_zip))
        self.assertEqual(info["format"], "epub")

    def test_dpi_width_height_bounds_rejected(self):
        src_png = _prepare_sample_png(self.root / "CANARY_TEST_bounds.png")
        out_dir = self.root / "bounds_out"
        out_dir.mkdir()

        # Image width/height out of bounds (<= 0 or > 16384)
        for bad_opts in (
            {"width": -10},
            {"height": -5},
            {"width": 0},
            {"height": 0},
            {"width": 20000},
            {"height": 20000},
        ):
            res = self.api.convert_single_file(str(src_png), "webp", options=bad_opts, output_dir=str(out_dir))
            self.assertFalse(res["success"], msg=f"Expected failure for options={bad_opts}")

        # SVG dpi out of bounds (<= 0 or > 600)
        svg_path = self.root / "CANARY_TEST_dpi.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect width="16" height="16"/></svg>',
            encoding="utf-8",
        )
        for bad_dpi in (0, -72, 601, 5000):
            res = self.api.convert_single_file(str(svg_path), "png", options={"dpi": bad_dpi}, output_dir=str(out_dir))
            self.assertFalse(res["success"], msg=f"Expected SVG failure for dpi={bad_dpi}")

        # PDF dpi out of bounds (> 600)
        pdf_path = self.root / "CANARY_TEST_dpi.pdf"
        DocumentConverter._html_string_to_pdf(
            "<!DOCTYPE html><html><body><p>CANARY_TEST</p></body></html>",
            str(pdf_path),
        )
        for bad_dpi in (0, -10, 601, 5000):
            res = self.api.convert_single_file(str(pdf_path), "png", options={"dpi": bad_dpi}, output_dir=str(out_dir))
            self.assertFalse(res["success"], msg=f"Expected PDF failure for dpi={bad_dpi}")


class TestFT04FrontendCSP(unittest.TestCase):
    """FT-04 : présence d'une balise CSP stricte dans src/frontend/index.html."""

    def test_index_html_has_strict_csp_meta(self):
        html_text = (REPO_ROOT / "src" / "frontend" / "index.html").read_text(encoding="utf-8")
        match = re.search(
            r'<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]+)"',
            html_text,
            flags=re.IGNORECASE,
        )
        self.assertIsNotNone(match, msg="Balise meta Content-Security-Policy absente de index.html")
        csp = match.group(1)
        self.assertIn("default-src 'self'", csp)
        self.assertIn("script-src 'self'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertNotIn("unsafe-eval", csp)
        self.assertNotIn("http://", csp)
        self.assertNotIn("https://", csp)


def _parse_requirements_entries(req_text: str) -> list[str]:
    """Assemble les entrées logiques d'un requirements.txt (continuations '\\')."""
    entries: list[str] = []
    parts: list[str] = []
    for raw_line in req_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            if parts:
                raise AssertionError("Ligne de continuation interrompue par une ligne vide ou un commentaire.")
            continue
        if stripped.endswith("\\"):
            chunk = stripped[:-1].strip()
            if not chunk:
                raise AssertionError("Ligne de continuation vide dans requirements.txt.")
            parts.append(chunk)
        else:
            parts.append(stripped)
            entries.append(" ".join(parts))
            parts.clear()
    if parts:
        raise AssertionError("Continuation '\\' non terminée en fin de requirements.txt.")
    return entries


class TestFT05SupplyChainRequirements(unittest.TestCase):
    """FT-05 : dépendances Python épinglées (==) sur les versions vérifiées."""

    def test_requirements_txt_strictly_pinned(self):
        req_text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        entries = _parse_requirements_entries(req_text)
        self.assertGreaterEqual(len(entries), 11)
        for entry in entries:
            self.assertNotIn(">=", entry, msg=f"Dépendance non épinglée : {entry}")
            spec = entry.split("--hash=", 1)[0].strip()
            self.assertRegex(spec, r"^[A-Za-z0-9_.-]+==[0-9]+(?:\.[0-9]+)*$", msg=f"Format non épinglé : {entry}")


class TestFT06HostileConversionsAndWindowsNames(unittest.TestCase):
    """FT-06 & FT-09 : noms réservés Windows, HTML->TXT sans script/style, DOCX tables, allowlist."""

    def setUp(self):
        self._tmp = TemporaryDirectory(prefix="canary_ft06_")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.api = AppAPI()

    def test_windows_reserved_device_names_rejected_without_disk_access(self):
        reserved_samples = [
            "CON",
            "con.txt",
            "NUL",
            "PRN.png",
            "AUX.pdf",
            "COM1",
            "com9.docx",
            "LPT1.html",
            "lpt9",
            str(self.root / "CON.png"),
            str(self.root / "NUL.txt"),
            str(self.root / "COM3.md"),
        ]

        def _forbid_fs(*_args, **_kwargs):
            raise AssertionError("Accès disque interdit pour un nom réservé Windows")

        with mock.patch("app_api.os.path.isfile", side_effect=_forbid_fs), \
             mock.patch("app_api.os.path.exists", side_effect=_forbid_fs), \
             mock.patch("app_api.format_detector.detect", side_effect=_forbid_fs):
            self.assertEqual(self.api.files_from_paths(reserved_samples), [])
            for sample in reserved_samples:
                res = self.api.convert_single_file(sample, "txt", output_dir=str(self.root))
                self.assertFalse(res["success"], msg=f"Nom réservé non rejeté : {sample}")

    def test_html_to_txt_strips_script_and_style_content(self):
        html_path = self.root / "CANARY_TEST_hostile.html"
        html_path.write_text(
            "<!DOCTYPE html><html><head>"
            "<style>body { color: red; /* CANARY_CSS_SECRET */ }</style>"
            "<script>alert('CANARY_JS_SECRET');</script>"
            "</head><body>"
            "<h1>CANARY_VISIBLE_TITLE</h1>"
            "<p>Texte &amp; entit&eacute;s</p>"
            "<script type='text/javascript'>var x = 'CANARY_INLINE_JS';</script>"
            "</body></html>",
            encoding="utf-8",
        )
        out_dir = self.root / "html_txt_out"
        out_dir.mkdir()

        res = self.api.convert_single_file(str(html_path), "txt", output_dir=str(out_dir))
        self.assertTrue(res["success"], msg=res.get("error"))
        txt = Path(res["output_path"]).read_text(encoding="utf-8")
        self.assertIn("CANARY_VISIBLE_TITLE", txt)
        self.assertIn("Texte & entités", txt)
        self.assertNotIn("CANARY_CSS_SECRET", txt)
        self.assertNotIn("CANARY_JS_SECRET", txt)
        self.assertNotIn("CANARY_INLINE_JS", txt)

    def test_docx_to_txt_and_html_preserves_tables(self):
        docx_path = self.root / "CANARY_TEST_tables.docx"
        document = docx.Document()
        document.add_paragraph("CANARY_PARA_INTRO")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "CANARY_COL_A"
        table.cell(0, 1).text = "CANARY_COL_B"
        table.cell(1, 0).text = "CANARY_VAL_1"
        table.cell(1, 1).text = "CANARY_VAL_2"
        document.save(str(docx_path))

        out_dir = self.root / "docx_tables_out"
        out_dir.mkdir()

        res_txt = self.api.convert_single_file(str(docx_path), "txt", output_dir=str(out_dir))
        self.assertTrue(res_txt["success"], msg=res_txt.get("error"))
        txt_out = Path(res_txt["output_path"]).read_text(encoding="utf-8")
        self.assertIn("CANARY_PARA_INTRO", txt_out)
        self.assertIn("CANARY_COL_A", txt_out)
        self.assertIn("CANARY_VAL_2", txt_out)

        res_html = self.api.convert_single_file(str(docx_path), "html", output_dir=str(out_dir))
        self.assertTrue(res_html["success"], msg=res_html.get("error"))
        html_out = Path(res_html["output_path"]).read_text(encoding="utf-8")
        self.assertIn("CANARY_PARA_INTRO", html_out)
        self.assertIn("CANARY_COL_A", html_out)
        self.assertIn("CANARY_VAL_2", html_out)

    def test_target_format_whitelist_and_symlink_rejection(self):
        src_png = _prepare_sample_png(self.root / "CANARY_TEST_wl.png")
        out_dir = self.root / "wl_out"
        out_dir.mkdir()

        # Format inconnu ou incompatible avec la catégorie image
        res_bad = self.api.convert_single_file(str(src_png), "exe", output_dir=str(out_dir))
        self.assertFalse(res_bad["success"])
        res_cross = self.api.convert_single_file(str(src_png), "txt", output_dir=str(out_dir))
        self.assertFalse(res_cross["success"])

        # Rejet d'un lien symbolique en entrée (mocké pour être indépendant des droits Windows)
        with mock.patch("app_api.os.path.islink", return_value=True):
            res_link = self.api.convert_single_file(str(src_png), "webp", output_dir=str(out_dir))
            self.assertFalse(res_link["success"])
            self.assertEqual(self.api.files_from_paths([str(src_png)]), [])

        # .svgz pris en charge dans SUPPORTED_INPUTS et file_types
        self.assertIn(".svgz", ImageConverter.SUPPORTED_INPUTS)
        api_source = (BACKEND_DIR / "app_api.py").read_text(encoding="utf-8")
        self.assertIn("*.svgz", api_source)


class TestFT07BatchLauncherHardening(unittest.TestCase):
    """FT-07 : chemins absolus where.exe et py.exe dans Lancer File Transformer.bat."""

    def test_bat_uses_systemroot_where_and_no_bare_py_exe(self):
        bat_text = (REPO_ROOT / "Lancer File Transformer.bat").read_text(encoding="utf-8")
        self.assertIn("%SystemRoot%\\System32\\where.exe", bat_text)
        # Aucun appel à where.exe nu (hors %SystemRoot%\System32\where.exe)
        stripped = bat_text.replace("%SystemRoot%\\System32\\where.exe", "")
        self.assertNotRegex(stripped, r"(?i)\bwhere\.exe\b")
        # Aucun appel relatif "py.exe" dans call :probe
        self.assertNotIn('call :probe "py.exe"', bat_text)


class ReleaseHardeningTests(unittest.TestCase):
    """Durcissement de publication : hashes SHA-256, CI épinglée, SECURITY.md, Dependabot."""

    DIRECT_PACKAGES = {
        "pywebview",
        "pillow",
        "pypdfium2",
        "xhtml2pdf",
        "resvg-py",
        "python-docx",
        "markdown",
        "reportlab",
        "pillow-heif",
        "imagecodecs",
        "numpy",
    }

    @staticmethod
    def _normalize_pkg(name: str) -> str:
        return re.sub(r"[-_.]+", "-", name).lower()

    def test_requirements_txt_pins_versions_hashes_and_no_duplicates(self):
        req_text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        for line in req_text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            for forbidden in (">=", "<=", "~=", "!=", "git+", "--index-url", "--extra-index-url", "--find-links"):
                self.assertNotIn(forbidden, stripped, msg=f"Spécification interdite dans requirements.txt : {stripped}")

        entries = _parse_requirements_entries(req_text)
        self.assertGreaterEqual(len(entries), len(self.DIRECT_PACKAGES))

        seen_packages: set[str] = set()
        for entry in entries:
            tokens = entry.split()
            self.assertGreaterEqual(len(tokens), 2, msg=f"Empreinte --hash=sha256 manquante : {entry}")
            spec, hash_tokens = tokens[0], tokens[1:]
            self.assertRegex(
                spec,
                r"^[A-Za-z0-9_.-]+==[0-9]+(?:\.[0-9]+)*$",
                msg=f"Version non strictement épinglée : {spec}",
            )
            pkg_norm = self._normalize_pkg(spec.split("==", 1)[0])
            self.assertNotIn(pkg_norm, seen_packages, msg=f"Dépendance dupliquée dans requirements.txt : {pkg_norm}")
            seen_packages.add(pkg_norm)

            seen_hashes: set[str] = set()
            for token in hash_tokens:
                self.assertRegex(
                    token,
                    r"^--hash=sha256:[0-9a-f]{64}$",
                    msg=f"Jeton --hash=sha256 invalide pour {spec} : {token}",
                )
                self.assertNotIn(token, seen_hashes, msg=f"Empreinte dupliquée pour {spec} : {token}")
                seen_hashes.add(token)

        missing_direct = self.DIRECT_PACKAGES - seen_packages
        self.assertEqual(missing_direct, set(), msg=f"Dépendances directes absentes : {sorted(missing_direct)}")

    def test_ci_workflow_is_read_only_pins_actions_and_runs_all_checks(self):
        workflow_path = REPO_ROOT / ".github" / "workflows" / "tests.yml"
        self.assertTrue(workflow_path.is_file(), msg="Le workflow .github/workflows/tests.yml est manquant.")
        content = workflow_path.read_text(encoding="utf-8")

        self.assertRegex(content, r"(?m)^\s*push:\s*$")
        self.assertRegex(content, r"(?m)^\s*pull_request:\s*$")
        self.assertIn("main", content)
        self.assertIn("runs-on: windows-latest", content)
        self.assertRegex(content, r"python-version:\s*[\"']?3\.14[\"']?")
        self.assertIn("actions/setup-node@", content)
        self.assertRegex(content, r"permissions:\s*\r?\n\s+contents:\s*read\b")
        self.assertNotRegex(content, r":\s*write\b")
        self.assertIn("persist-credentials: false", content)

        uses_refs = re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", content, flags=re.MULTILINE)
        self.assertGreaterEqual(len(uses_refs), 3)
        for ref in uses_refs:
            self.assertRegex(
                ref,
                r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$",
                msg=f"Action non épinglée sur un SHA complet de 40 hex : {ref}",
            )

        self.assertIn("--require-hashes", content)
        self.assertIn("python -B -W default -m unittest discover -s tests -v", content)
        self.assertIn("node tests/frontend-state.cjs", content)

    def test_security_policy_uses_private_github_reporting_without_personal_email(self):
        security_path = REPO_ROOT / "SECURITY.md"
        self.assertTrue(security_path.is_file(), msg="Le fichier SECURITY.md est manquant.")
        content = security_path.read_text(encoding="utf-8")
        self.assertGreater(len(content.strip()), 50)

        lowered = content.lower()
        self.assertIn("advisories", lowered)
        self.assertIn("report a vulnerability", lowered)
        self.assertIn("github", lowered)
        self.assertNotRegex(
            content,
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            msg="SECURITY.md ne doit contenir aucune adresse e-mail personnelle.",
        )

    def test_dependabot_covers_pip_and_github_actions_weekly(self):
        dependabot_path = REPO_ROOT / ".github" / "dependabot.yml"
        self.assertTrue(dependabot_path.is_file(), msg="Le fichier .github/dependabot.yml est manquant.")
        content = dependabot_path.read_text(encoding="utf-8")
        lines = [line for line in content.splitlines() if not line.lstrip().startswith("#")]
        clean = "\n".join(lines)

        self.assertRegex(clean, r"(?m)^version:\s*2\s*$")
        self.assertRegex(clean, r"(?m)^updates:\s*$")

        blocks = re.split(r"(?m)^\s*-\s+package-ecosystem:\s*", clean)[1:]
        self.assertEqual(len(blocks), 2, msg="Dependabot doit déclarer exactement 2 écosystèmes (pip et github-actions).")
        ecosystems: set[str] = set()
        for block in blocks:
            first_line = block.splitlines()[0].strip().strip("'\"")
            ecosystems.add(first_line)
            self.assertRegex(block, r"directory:\s*[\"']?/[\"']?", msg=f"directory '/' manquant pour {first_line}")
            self.assertRegex(block, r"interval:\s*[\"']?weekly[\"']?", msg=f"interval 'weekly' manquant pour {first_line}")

        self.assertEqual(ecosystems, {"pip", "github-actions"})


if __name__ == "__main__":
    unittest.main()
