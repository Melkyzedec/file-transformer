import html
from html.parser import HTMLParser
import logging
import os
import re
import zipfile

import docx
import markdown
import pypdfium2 as pdfium
from xhtml2pdf import pisa
from xhtml2pdf.config.resources import ResourceAccessPolicy
from xhtml2pdf.default import DEFAULT_CSS

logging.getLogger('xhtml2pdf').setLevel(logging.ERROR)


class _HtmlTextExtractor(HTMLParser):
    """Extrait le texte visible d'un document HTML en ignorant script/style/noscript."""

    _SKIP_TAGS = {'script', 'style', 'noscript'}
    _BLOCK_TAGS = {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'section', 'article', 'blockquote'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in self._SKIP_TAGS:
            self._skip_depth += 1
        elif self._skip_depth == 0 and t in self._BLOCK_TAGS:
            self._parts.append('\n')

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif self._skip_depth == 0 and t in self._BLOCK_TAGS:
            self._parts.append('\n')

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        raw = ''.join(self._parts)
        lines = [line.strip() for line in raw.splitlines()]
        return '\n'.join(line for line in lines if line)


class DocumentConverter:
    """
    Handles conversion between document formats:
    PDF, DOCX, Markdown (.md), HTML, TXT, and PDF -> Images.
    """

    MIN_DPI = 1
    MAX_DPI = 600
    MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
    MAX_DOCX_ENTRIES = 2000
    MAX_DOCX_COMPRESSION_RATIO = 100

    SUPPORTED_INPUTS = {'.pdf', '.docx', '.md', '.markdown', '.mdown', '.html', '.htm',
                        '.xhtml', '.txt', '.text', '.log'}
    SUPPORTED_OUTPUTS = {'pdf', 'html', 'txt', 'md', 'png', 'jpg'}

    # Extension -> format canonique, utilisé quand aucune détection n'est fournie.
    EXT_TO_FORMAT = {
        '.pdf': 'pdf', '.docx': 'docx',
        '.md': 'md', '.markdown': 'md', '.mdown': 'md',
        '.html': 'html', '.htm': 'html', '.xhtml': 'html',
        '.txt': 'txt', '.text': 'txt', '.log': 'txt',
    }

    _PDF_BASE_CSS = DEFAULT_CSS + "\n@page { size: a4 portrait; margin: 36pt; }\n"

    # Aucune ressource externe : ni réseau (allow_remote=False), ni fichier local
    # (base_dir=None refuse toute lecture). Les images data: restent rendues.
    _PDF_RESOURCE_POLICY = ResourceAccessPolicy(allow_remote=False, base_dir=None)

    @staticmethod
    def convert(input_path: str, output_path: str, options: dict = None) -> str:
        """
        Converts input document to output format.

        Le format d'entrée provient de options['source_format'] (détection par
        contenu) et retombe sur l'extension du fichier si absent.
        """
        if options is None:
            options = {}

        ext_in = os.path.splitext(input_path)[1].lower()
        ext_out = os.path.splitext(output_path)[1].lower().replace('.', '')

        source_format = (options.get('source_format') or '').lower()
        if not source_format:
            source_format = DocumentConverter.EXT_TO_FORMAT.get(ext_in, '')

        handlers = {
            'pdf': DocumentConverter._convert_pdf,
            'docx': DocumentConverter._convert_docx,
            'md': DocumentConverter._convert_markdown,
            'html': DocumentConverter._convert_html,
            'txt': DocumentConverter._convert_txt,
        }

        handler = handlers.get(source_format)
        if handler:
            return handler(input_path, output_path, ext_out, options)

        raise ValueError(f"Format d'entrée non supporté : {source_format or ext_in}")

    @staticmethod
    def _read_text(input_path: str) -> str:
        """Lit un fichier texte en tolérant les encodages hérités (cp1252, latin-1)."""
        for encoding in ('utf-8-sig', 'cp1252', 'latin-1'):
            try:
                with open(input_path, 'r', encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()

    @staticmethod
    def _save_pdf_page_image(page, dest_path: str, ext_out: str, scale: float, quality: int) -> None:
        bitmap = page.render(scale=scale)
        try:
            img = bitmap.to_pil()
        finally:
            bitmap.close()

        try:
            if ext_out in ('jpg', 'jpeg'):
                if img.mode in ('RGBA', 'LA', 'P'):
                    from PIL import Image
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                img.save(dest_path, format='JPEG', quality=quality)
            else:
                img.save(dest_path, format='PNG')
        finally:
            img.close()

    @staticmethod
    def _extract_page_text(page) -> str:
        textpage = page.get_textpage()
        try:
            return textpage.get_text_range().replace('\r\n', '\n')
        finally:
            textpage.close()

    @staticmethod
    def _convert_pdf(input_path: str, output_path: str, ext_out: str, options: dict) -> str:
        doc = pdfium.PdfDocument(input_path)
        try:
            page_count = len(doc)
            if page_count == 0:
                raise ValueError("Le document PDF ne contient aucune page.")

            if ext_out in ('png', 'jpg', 'jpeg'):
                raw_dpi = options.get('dpi', 150)
                if isinstance(raw_dpi, bool):
                    raise ValueError(f"Le DPI doit être compris entre {DocumentConverter.MIN_DPI} et {DocumentConverter.MAX_DPI}.")
                dpi = int(raw_dpi)
                if dpi < DocumentConverter.MIN_DPI or dpi > DocumentConverter.MAX_DPI:
                    raise ValueError(f"Le DPI doit être compris entre {DocumentConverter.MIN_DPI} et {DocumentConverter.MAX_DPI}.")
                scale = dpi / 72
                quality = int(options.get('quality', 90))

                out_dir = os.path.dirname(output_path)
                base_name = os.path.splitext(os.path.basename(output_path))[0]

                if page_count == 1:
                    page = doc[0]
                    try:
                        DocumentConverter._save_pdf_page_image(page, output_path, ext_out, scale, quality)
                    finally:
                        page.close()
                    return output_path

                created_files = []
                for i in range(page_count):
                    page = doc[i]
                    try:
                        p_path = os.path.join(out_dir, f"{base_name}_page_{i+1}.{ext_out}")
                        DocumentConverter._save_pdf_page_image(page, p_path, ext_out, scale, quality)
                        created_files.append(p_path)
                    finally:
                        page.close()
                return created_files[0] if created_files else output_path

            elif ext_out in ('txt', 'md'):
                full_text = []
                for i in range(page_count):
                    page = doc[i]
                    try:
                        full_text.append(f"--- Page {i+1} ---\n")
                        full_text.append(DocumentConverter._extract_page_text(page))
                    finally:
                        page.close()
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(full_text))
                return output_path

            elif ext_out == 'html':
                sections = []
                for i in range(page_count):
                    page = doc[i]
                    try:
                        page_text = DocumentConverter._extract_page_text(page)
                    finally:
                        page.close()
                    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
                    body_parts = [f"<p>{html.escape(line)}</p>" for line in lines]
                    sections.append(
                        f'<section class="pdf-page" data-page="{i+1}">'
                        + ''.join(body_parts)
                        + '</section>'
                    )
                html_doc = (
                    '<!DOCTYPE html>\n<html>\n<head><meta charset="utf-8"></head>\n<body>\n'
                    + '\n'.join(sections)
                    + '\n</body>\n</html>'
                )
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(html_doc)
                return output_path

            raise ValueError(f"Conversion PDF vers {ext_out} non supportée directement.")
        finally:
            doc.close()

    @staticmethod
    def _validate_docx_archive(input_path: str) -> None:
        """Contrôle anti-bombe ZIP avant ouverture par python-docx."""
        try:
            with zipfile.ZipFile(input_path, 'r') as zf:
                infos = zf.infolist()
                if len(infos) > DocumentConverter.MAX_DOCX_ENTRIES:
                    raise ValueError("Archive DOCX trop complexe (trop d'entrées).")
                total_uncompressed = 0
                for info in infos:
                    normalized = info.filename.replace('\\', '/')
                    if normalized.startswith('/') or '..' in normalized.split('/'):
                        raise ValueError("Archive DOCX invalide (chemin interdit).")
                    total_uncompressed += info.file_size
                    if total_uncompressed > DocumentConverter.MAX_DOCX_UNCOMPRESSED_BYTES:
                        raise ValueError("Archive DOCX trop volumineuse après décompression (plafond 50 Mo dépassé).")
                    if info.file_size > 1024 * 1024 and info.compress_size > 0:
                        if (info.file_size / info.compress_size) > DocumentConverter.MAX_DOCX_COMPRESSION_RATIO:
                            raise ValueError("Ratio de compression suspect détecté dans l'archive DOCX.")
        except zipfile.BadZipFile as exc:
            raise ValueError("Fichier DOCX corrompu ou archive ZIP invalide.") from exc

    @staticmethod
    def _convert_docx(input_path: str, output_path: str, ext_out: str, options: dict) -> str:
        DocumentConverter._validate_docx_archive(input_path)
        doc = docx.Document(input_path)
        paragraphs = [p.text for p in doc.paragraphs]
        tables = [
            [[cell.text.strip() for cell in row.cells] for row in table.rows]
            for table in doc.tables
        ]

        if ext_out in ('txt', 'md'):
            blocks = [p for p in paragraphs if p.strip()]
            for table_rows in tables:
                row_lines = [' | '.join(cells) for cells in table_rows if any(cells)]
                if row_lines:
                    blocks.append('\n'.join(row_lines))
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n\n'.join(blocks))
            return output_path
        elif ext_out in ('html', 'pdf'):
            body_parts = [f"<p>{html.escape(p)}</p>" for p in paragraphs if p.strip()]
            for table_rows in tables:
                if not table_rows:
                    continue
                rows_html = []
                for cells in table_rows:
                    cells_html = ''.join(f"<td>{html.escape(c)}</td>" for c in cells)
                    rows_html.append(f"<tr>{cells_html}</tr>")
                body_parts.append(f"<table>{''.join(rows_html)}</table>")
            body_html = ''.join(body_parts) or '<p>&nbsp;</p>'
            html_content = (
                "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
                f"<body>{body_html}</body></html>"
            )
            if ext_out == 'html':
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                return output_path
            return DocumentConverter._html_string_to_pdf(html_content, output_path)

        raise ValueError(f"Conversion DOCX vers {ext_out} non supportée.")

    @staticmethod
    def _convert_markdown(input_path: str, output_path: str, ext_out: str, options: dict) -> str:
        md_content = DocumentConverter._read_text(input_path)

        html_body = markdown.markdown(md_content, extensions=['extra', 'codehilite', 'tables', 'toc'])
        full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: Helvetica, Arial, sans-serif; line-height: 1.6; padding: 20px; color: #333; }}
pre, code {{ background-color: #f4f4f4; padding: 4px 8px; font-family: Courier, monospace; }}
table {{ width: 100%; margin: 15px 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background-color: #f2f2f2; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

        if ext_out == 'html':
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(full_html)
            return output_path
        elif ext_out == 'txt':
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(md_content)
            return output_path
        elif ext_out == 'pdf':
            return DocumentConverter._html_string_to_pdf(full_html, output_path)

        raise ValueError(f"Conversion Markdown vers {ext_out} non supportée.")

    @staticmethod
    def _convert_html(input_path: str, output_path: str, ext_out: str, options: dict) -> str:
        html_content = DocumentConverter._read_text(input_path)

        if ext_out == 'txt':
            extractor = _HtmlTextExtractor()
            extractor.feed(html_content)
            extractor.close()
            text = extractor.get_text()
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text)
            return output_path
        elif ext_out == 'pdf':
            return DocumentConverter._html_string_to_pdf(html_content, output_path)

        raise ValueError(f"Conversion HTML vers {ext_out} non supportée.")

    @staticmethod
    def _convert_txt(input_path: str, output_path: str, ext_out: str, options: dict) -> str:
        content = DocumentConverter._read_text(input_path)

        if ext_out in ('md', 'markdown'):
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return output_path
        elif ext_out == 'html':
            escaped = html.escape(content)
            html_doc = f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body><pre>{escaped}</pre></body></html>"
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html_doc)
            return output_path
        elif ext_out == 'pdf':
            escaped = html.escape(content)
            body = f"<pre>{escaped}</pre>" if content.strip() else "<p>&nbsp;</p>"
            html_doc = f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>{body}</body></html>"
            return DocumentConverter._html_string_to_pdf(html_doc, output_path)

        raise ValueError(f"Conversion TXT vers {ext_out} non supportée.")

    @staticmethod
    def _block_external_resource(uri: str, rel: str) -> str:
        """Point d'observation des ressources demandées par le HTML.

        Une valeur vide laisse l'URI d'origine à xhtml2pdf : le blocage effectif
        est assuré par _PDF_RESOURCE_POLICY, pas par ce rappel.
        """
        return ''

    @staticmethod
    def _prepare_html_for_pdf(html_str: str) -> str:
        if not html_str or not html_str.strip():
            return '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body><p>&nbsp;</p></body></html>'

        stripped_body = re.search(r'<body[^>]*>(.*?)</body>', html_str, flags=re.IGNORECASE | re.DOTALL)
        if stripped_body and not stripped_body.group(1).strip():
            return re.sub(
                r'</body>',
                '<p>&nbsp;</p></body>',
                html_str,
                count=1,
                flags=re.IGNORECASE,
            )
        return html_str

    @staticmethod
    def _html_string_to_pdf(html_str: str, output_path: str) -> str:
        """Converts an HTML string to a paginated A4 PDF using xhtml2pdf."""
        prepared = DocumentConverter._prepare_html_for_pdf(html_str)
        with open(output_path, 'wb') as out_file:
            status = pisa.CreatePDF(
                prepared,
                dest=out_file,
                encoding='utf-8',
                default_css=DocumentConverter._PDF_BASE_CSS,
                link_callback=DocumentConverter._block_external_resource,
                resource_policy=DocumentConverter._PDF_RESOURCE_POLICY,
            )
        if status.err or not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError(f"Échec de la génération PDF ({status.err} erreur(s)).")
        return output_path
