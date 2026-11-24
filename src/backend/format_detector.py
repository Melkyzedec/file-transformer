"""
Détection automatique du format réel d'un fichier.

La détection se base d'abord sur le contenu (signature binaire / sniffing texte)
et ne retombe sur l'extension que si le contenu ne permet pas de conclure.
Cela permet de traiter correctement les fichiers mal nommés (un .png qui est en
réalité un JPEG, un .txt qui est un PDF, un .jfif renommé en .jpg, etc.).
"""

import json
import os
import re
import zipfile

# --- Table des formats connus -------------------------------------------------
# supported = l'application sait convertir ce format en entrée.
FORMATS = {
    # Images
    'png':  {'ext': '.png',  'label': 'PNG',              'mime': 'image/png',     'category': 'image',    'supported': True},
    'jpeg': {'ext': '.jpg',  'label': 'JPEG',             'mime': 'image/jpeg',    'category': 'image',    'supported': True},
    'jfif': {'ext': '.jfif', 'label': 'JPEG (JFIF)',      'mime': 'image/jpeg',    'category': 'image',    'supported': True},
    'webp': {'ext': '.webp', 'label': 'WebP',             'mime': 'image/webp',    'category': 'image',    'supported': True},
    'gif':  {'ext': '.gif',  'label': 'GIF',              'mime': 'image/gif',     'category': 'image',    'supported': True},
    'bmp':  {'ext': '.bmp',  'label': 'BMP',              'mime': 'image/bmp',     'category': 'image',    'supported': True},
    'ico':  {'ext': '.ico',  'label': 'ICO',              'mime': 'image/x-icon',  'category': 'image',    'supported': True},
    'tiff': {'ext': '.tiff', 'label': 'TIFF',             'mime': 'image/tiff',    'category': 'image',    'supported': True},
    'svg':  {'ext': '.svg',  'label': 'SVG',              'mime': 'image/svg+xml', 'category': 'image',    'supported': True},
    # Images reconnues mais non prises en charge (message d'erreur explicite)
    'avif': {'ext': '.avif', 'label': 'AVIF',             'mime': 'image/avif',    'category': 'image',    'supported': False},
    'heic': {'ext': '.heic', 'label': 'HEIC / HEIF',      'mime': 'image/heic',    'category': 'image',    'supported': True},
    'jxl':  {'ext': '.jxl',  'label': 'JPEG XL',          'mime': 'image/jxl',     'category': 'image',    'supported': True},
    'jp2':  {'ext': '.jp2',  'label': 'JPEG 2000',        'mime': 'image/jp2',     'category': 'image',    'supported': False},
    'psd':  {'ext': '.psd',  'label': 'Photoshop PSD',    'mime': 'image/vnd.adobe.photoshop', 'category': 'image', 'supported': False},
    'cur':  {'ext': '.cur',  'label': 'Curseur Windows',  'mime': 'image/x-icon',  'category': 'image',    'supported': False},

    # Documents
    'pdf':  {'ext': '.pdf',  'label': 'PDF',              'mime': 'application/pdf', 'category': 'document', 'supported': True},
    'docx': {'ext': '.docx', 'label': 'Word DOCX',        'mime': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'category': 'document', 'supported': True},
    'html': {'ext': '.html', 'label': 'HTML',             'mime': 'text/html',     'category': 'document', 'supported': True},
    'md':   {'ext': '.md',   'label': 'Markdown',         'mime': 'text/markdown', 'category': 'document', 'supported': True},
    'txt':  {'ext': '.txt',  'label': 'Texte brut',       'mime': 'text/plain',    'category': 'document', 'supported': True},
    # Documents reconnus mais non pris en charge
    'doc':  {'ext': '.doc',  'label': 'Word 97-2003',     'mime': 'application/msword', 'category': 'document', 'supported': False},
    'rtf':  {'ext': '.rtf',  'label': 'RTF',              'mime': 'application/rtf', 'category': 'document', 'supported': False},
    'odt':  {'ext': '.odt',  'label': 'OpenDocument Texte', 'mime': 'application/vnd.oasis.opendocument.text', 'category': 'document', 'supported': False},
    'xlsx': {'ext': '.xlsx', 'label': 'Excel XLSX',       'mime': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'category': 'document', 'supported': False},
    'pptx': {'ext': '.pptx', 'label': 'PowerPoint PPTX',  'mime': 'application/vnd.openxmlformats-officedocument.presentationml.presentation', 'category': 'document', 'supported': False},
    'epub': {'ext': '.epub', 'label': 'EPUB',             'mime': 'application/epub+zip', 'category': 'document', 'supported': False},
    'json': {'ext': '.json', 'label': 'JSON',             'mime': 'application/json', 'category': 'document', 'supported': False},
    'xml':  {'ext': '.xml',  'label': 'XML',              'mime': 'application/xml', 'category': 'document', 'supported': False},
    'csv':  {'ext': '.csv',  'label': 'CSV',              'mime': 'text/csv',      'category': 'document', 'supported': False},
    'zip':  {'ext': '.zip',  'label': 'Archive ZIP',      'mime': 'application/zip', 'category': 'unknown', 'supported': False},
}

# Extension déclarée -> format canonique (utilisé en dernier recours).
EXT_TO_FORMAT = {
    '.png': 'png',
    '.jpg': 'jpeg', '.jpeg': 'jpeg', '.jpe': 'jpeg', '.jif': 'jpeg',
    '.jfif': 'jfif', '.jfi': 'jfif',
    '.webp': 'webp', '.gif': 'gif', '.bmp': 'bmp', '.dib': 'bmp',
    '.ico': 'ico', '.cur': 'cur',
    '.tif': 'tiff', '.tiff': 'tiff',
    '.svg': 'svg', '.svgz': 'svg',
    '.avif': 'avif', '.heic': 'heic', '.heif': 'heic',
    '.jxl': 'jxl',
    '.jp2': 'jp2', '.j2k': 'jp2', '.psd': 'psd',
    '.pdf': 'pdf', '.docx': 'docx', '.doc': 'doc', '.rtf': 'rtf', '.odt': 'odt',
    '.xlsx': 'xlsx', '.pptx': 'pptx', '.epub': 'epub',
    '.html': 'html', '.htm': 'html', '.xhtml': 'html',
    '.md': 'md', '.markdown': 'md', '.mdown': 'md',
    '.txt': 'txt', '.text': 'txt', '.log': 'txt',
    '.json': 'json', '.xml': 'xml', '.csv': 'csv', '.tsv': 'csv',
    '.zip': 'zip',
}

# Formats interchangeables : ne pas signaler d'incohérence entre eux.
_FAMILIES = {
    'jpeg': 'jpeg', 'jfif': 'jpeg',
    'ico': 'ico', 'cur': 'ico',
    'heic': 'heic', 'avif': 'heic',
}

# Formats textuels : le sniffing y est moins fiable que sur du binaire.
_TEXT_FORMATS = {'txt', 'md', 'html', 'svg', 'json', 'xml', 'csv'}

# Sniffing texte fiable : on ose contredire l'extension pour ceux-là.
_STRONG_TEXT_FORMATS = {'svg', 'html', 'json'}

_HEAD_SIZE = 8192


def family(fmt):
    """Regroupe les formats équivalents (jpeg/jfif, ico/cur...)."""
    return _FAMILIES.get(fmt, fmt)


def detect(path):
    """
    Analyse un fichier et renvoie un dictionnaire décrivant son format réel.

    Clés renvoyées :
      format       identifiant canonique ('png', 'jfif', 'pdf'...) ou None
      label        libellé lisible
      ext          extension canonique du format détecté
      mime         type MIME
      category     'image' | 'document' | 'unknown'
      supported    True si l'application sait convertir ce format
      method       'signature' | 'content' | 'extension' | 'unknown'
      declared_ext extension du nom de fichier
      mismatch     True si le contenu contredit l'extension
    """
    declared_ext = os.path.splitext(path)[1].lower()
    declared_fmt = EXT_TO_FORMAT.get(declared_ext)

    head = b''
    try:
        with open(path, 'rb') as f:
            head = f.read(_HEAD_SIZE)
    except OSError:
        pass

    # Un fichier vide ne révèle un format texte que si son extension le déclare.
    if not head and declared_fmt not in _TEXT_FORMATS:
        declared_fmt = None

    fmt = _detect_signature(head, path)
    method = 'signature' if fmt else None

    strong_text = False
    if not fmt:
        fmt, strong_text = _detect_text(head, path)
        method = 'content' if fmt else None

    # Sniffing texte peu concluant : l'extension est plus précise (.md, .csv...)
    if fmt and method == 'content' and not strong_text and declared_fmt in _TEXT_FORMATS:
        fmt, method = declared_fmt, 'extension'

    if not fmt and declared_fmt:
        fmt, method = declared_fmt, 'extension'

    if not fmt:
        return {
            'format': None,
            'label': 'Format inconnu',
            'ext': declared_ext,
            'mime': 'application/octet-stream',
            'category': 'unknown',
            'supported': False,
            'method': 'unknown',
            'declared_ext': declared_ext,
            'mismatch': False,
        }

    info = FORMATS.get(fmt, {})
    mismatch = bool(
        declared_fmt
        and method != 'extension'
        and family(fmt) != family(declared_fmt)
        and (method == 'signature' or fmt in _STRONG_TEXT_FORMATS)
    )

    return {
        'format': fmt,
        'label': info.get('label', fmt.upper()),
        'ext': info.get('ext', declared_ext),
        'mime': info.get('mime', 'application/octet-stream'),
        'category': info.get('category', 'unknown'),
        'supported': info.get('supported', False),
        'method': method,
        'declared_ext': declared_ext,
        'mismatch': mismatch,
    }


# --- Signatures binaires ------------------------------------------------------

def _detect_signature(head, path):
    if len(head) < 2:
        return None

    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if head.startswith(b'\xff\xd8\xff'):
        return _jpeg_variant(head)
    if head.startswith(b'\xff\x0a'):
        return 'jxl'
    if head.startswith(b'\x00\x00\x00\x0cJXL \r\n\x87\n'):
        return 'jxl'
    if head[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    if head.startswith(b'RIFF') and head[8:12] == b'WEBP':
        return 'webp'
    if head.startswith(b'BM') and len(head) > 6:
        return 'bmp'
    if head.startswith(b'\x00\x00\x01\x00'):
        return 'ico'
    if head.startswith(b'\x00\x00\x02\x00'):
        return 'cur'
    if head[:4] in (b'II*\x00', b'MM\x00*'):
        return 'tiff'
    if head.startswith(b'%PDF'):
        return 'pdf'
    if head.startswith(b'8BPS'):
        return 'psd'
    if head.startswith(b'\x00\x00\x00\x0cjP  \r\n\x87\n') or head[:4] == b'\xff\x4f\xff\x51':
        return 'jp2'
    if head[4:8] == b'ftyp':
        return _ftyp_variant(head[8:12])
    if head.startswith(b'{\\rtf'):
        return 'rtf'
    if head.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
        return 'doc'  # conteneur OLE2 (Word/Excel/PowerPoint 97-2003)
    if head.startswith(b'\x1f\x8b'):
        return 'svg' if path.lower().endswith('.svgz') else None
    if head[:2] == b'PK' and head[2:4] in (b'\x03\x04', b'\x05\x06', b'\x07\x08'):
        return _zip_variant(path)
    return None


def _jpeg_variant(head):
    """Distingue un JPEG/JFIF (marqueur APP0 'JFIF') d'un JPEG Exif classique."""
    i = 2
    limit = min(len(head), 4096)
    while i + 4 <= limit:
        if head[i] != 0xFF:
            break
        marker = head[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = int.from_bytes(head[i + 2:i + 4], 'big')
        if seg_len < 2:
            break
        payload = head[i + 4:i + 2 + seg_len]
        if marker == 0xE0 and payload.startswith(b'JFIF\x00'):
            return 'jfif'
        if marker in (0xDA, 0xC0, 0xC2):  # début des données d'image
            break
        i += 2 + seg_len
    return 'jpeg'


def _ftyp_variant(brand):
    if brand in (b'avif', b'avis'):
        return 'avif'
    if brand in (b'heic', b'heix', b'hevc', b'hevx', b'mif1', b'msf1', b'heim', b'heis'):
        return 'heic'
    if brand in (b'jxl ', b'jxlp'):
        return 'jxl'
    return None


def _zip_variant(path):
    """Un conteneur ZIP peut être un DOCX, XLSX, PPTX, ODT, EPUB..."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if 'mimetype' in names:
                try:
                    with zf.open('mimetype') as mf:
                        mime = mf.read(256).decode('ascii', 'ignore').strip()
                except Exception:
                    mime = ''
                if mime == 'application/epub+zip':
                    return 'epub'
                if mime.startswith('application/vnd.oasis.opendocument'):
                    return 'odt'
            if any(n.startswith('word/') for n in names):
                return 'docx'
            if any(n.startswith('xl/') for n in names):
                return 'xlsx'
            if any(n.startswith('ppt/') for n in names):
                return 'pptx'
    except (zipfile.BadZipFile, OSError):
        return 'zip'
    return 'zip'


# --- Sniffing texte -----------------------------------------------------------

_BOMS = (
    (b'\xef\xbb\xbf', 'utf-8-sig'),
    (b'\xff\xfe\x00\x00', 'utf-32-le'),
    (b'\x00\x00\xfe\xff', 'utf-32-be'),
    (b'\xff\xfe', 'utf-16-le'),
    (b'\xfe\xff', 'utf-16-be'),
)

_MD_PATTERNS = (
    re.compile(r'^#{1,6}\s+\S', re.M),
    re.compile(r'^\s*[-*+]\s+\S', re.M),
    re.compile(r'^\s*\d+\.\s+\S', re.M),
    re.compile(r'^>\s+\S', re.M),
    re.compile(r'^\s*```', re.M),
    re.compile(r'!?\[[^\]]*\]\([^)]+\)'),
    re.compile(r'(\*\*|__)\S.*?\1'),
    re.compile(r'^\s*\|.+\|\s*$', re.M),
)


def _decode(head):
    for bom, enc in _BOMS:
        if head.startswith(bom):
            try:
                return head.decode(enc, 'ignore')
            except LookupError:
                return None
    if b'\x00' in head[:512]:
        return None
    try:
        text = head.decode('utf-8')
    except UnicodeDecodeError:
        # Fichier tronqué au milieu d'un caractère multi-octets ?
        try:
            text = head[:-4].decode('utf-8')
        except UnicodeDecodeError:
            text = head.decode('cp1252', 'ignore')
    # Trop d'octets de contrôle => binaire
    ctrl = sum(1 for c in text if ord(c) < 9 or 13 < ord(c) < 32)
    if text and ctrl / len(text) > 0.05:
        return None
    return text


def _detect_text(head, path):
    """Renvoie (format, fiable) pour un contenu textuel."""
    if not head:
        return (None, False)

    text = _decode(head)
    if text is None:
        return (None, False)

    stripped = text.lstrip()
    if not stripped:
        return ('txt', False)

    low = stripped[:2048].lower()

    if '<svg' in low:
        return ('svg', True)
    if low.startswith('<!doctype html') or low.startswith('<html') or '<html' in low[:512]:
        return ('html', True)
    if stripped[0] in '{[' and _is_json(path):
        return ('json', True)
    if low.startswith('<?xml'):
        return ('xml', True)
    if stripped[0] == '<' and re.match(r'<[a-zA-Z!/]', stripped):
        return ('html', False)

    matches = sum(1 for pattern in _MD_PATTERNS if pattern.search(text))
    if matches >= 2:
        return ('md', False)

    if _looks_like_csv(text):
        return ('csv', False)

    return ('txt', False)


def _is_json(path):
    try:
        if os.path.getsize(path) > 8 * 1024 * 1024:
            return False
        with open(path, 'r', encoding='utf-8', errors='strict') as f:
            json.load(f)
        return True
    except (OSError, ValueError, UnicodeDecodeError):
        return False


def _looks_like_csv(text):
    lines = [line for line in text.splitlines()[:20] if line.strip()]
    if len(lines) < 2:
        return False
    for sep in (',', ';', '\t'):
        counts = [line.count(sep) for line in lines]
        if counts[0] >= 1 and len(set(counts)) == 1:
            return True
    return False
