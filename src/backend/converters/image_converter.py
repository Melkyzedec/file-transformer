import gzip
import io
import os
import xml.etree.ElementTree as ET
from PIL import Image
import resvg_py

from converters.options import parse_keep_aspect_ratio, parse_quality

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pass

def _check_jxl_dimensions(data: bytes) -> None:
    """Refuse un JPEG XL trop grand en lisant son en-tête, avant tout décodage.

    Le décodeur imagecodecs alloue l'image entière : le contrôle anti-bombe de
    Pillow, appliqué après coup, ne protège pas ce format. Même plafond que
    Pillow pour les autres formats (2 x Image.MAX_IMAGE_PIXELS).
    """
    import imagecodecs
    try:
        info = imagecodecs.jpegxl_info(data)
    except Exception as exc:
        raise ValueError("En-tête JPEG XL illisible.") from exc
    shape = tuple(info.get('shape') or ())
    frames = max(1, int(info.get('frames') or 1))
    if frames > 1 and len(shape) >= 3 and shape[0] == frames:
        height, width = shape[1], shape[2]
    elif len(shape) >= 2:
        height, width = shape[0], shape[1]
    else:
        raise ValueError("En-tête JPEG XL illisible.")
    pixels = int(width) * int(height) * frames
    limit = Image.MAX_IMAGE_PIXELS
    if limit and pixels > 2 * limit:
        raise Image.DecompressionBombError(
            f"Image JPEG XL trop grande ({width} x {height} pixels, {frames} image(s)) : "
            f"plafond de {2 * limit} pixels dépassé."
        )


try:
    from PIL import ImageFile
    import imagecodecs
    import numpy as np

    class JxlImageFile(ImageFile.ImageFile):
        format = "JXL"
        format_description = "JPEG XL image"

        def _open(self):
            data = self.fp.read()
            _check_jxl_dimensions(data)
            arr = imagecodecs.jpegxl_decode(data)
            if arr.dtype == np.uint16:
                arr = (arr / 256).astype(np.uint8)
            elif arr.dtype in (np.float32, np.float64):
                arr = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
            img = Image.fromarray(arr)
            self._size = img.size
            self._mode = img.mode
            self.im = img.im

    def _accept_jxl(prefix):
        return prefix.startswith(b'\xff\x0a') or prefix.startswith(b'\x00\x00\x00\x0cJXL \r\n\x87\n')

    Image.register_open('JXL', JxlImageFile, _accept_jxl)
    Image.register_extension('JXL', '.jxl')
    Image.register_mime('JXL', 'image/jxl')
except Exception:
    pass


_SVG_NAMESPACE = 'http://www.w3.org/2000/svg'
_XLINK_NAMESPACE = 'http://www.w3.org/1999/xlink'
ET.register_namespace('', _SVG_NAMESPACE)
ET.register_namespace('xlink', _XLINK_NAMESPACE)


class ImageConverter:
    """
    Handles conversion between various image formats:
    PNG, JPG/JPEG/JFIF, WEBP, ICO, GIF, BMP, TIFF, HEIC/HEIF, JXL, SVG (input), etc.
    Supports resizing and quality compression.
    """

    MAX_SVG_BYTES = 10 * 1024 * 1024
    MIN_DPI = 1
    MAX_DPI = 600
    MIN_DIMENSION = 1
    MAX_DIMENSION = 16384

    SUPPORTED_INPUTS = {
        '.png', '.jpg', '.jpeg', '.jfif', '.jfi', '.jpe', '.jif',
        '.webp', '.ico', '.gif', '.bmp', '.dib', '.svg', '.svgz', '.tif', '.tiff',
        '.heic', '.heif', '.jxl'
    }
    SUPPORTED_OUTPUTS = {'png', 'jpg', 'jpeg', 'jfif', 'webp', 'ico', 'gif', 'bmp', 'jxl'}

    # Extension de sortie -> format Pillow
    PIL_FORMATS = {
        'png': 'PNG',
        'jpg': 'JPEG', 'jpeg': 'JPEG', 'jfif': 'JPEG', 'jfi': 'JPEG', 'jpe': 'JPEG',
        'webp': 'WEBP',
        'ico': 'ICO',
        'gif': 'GIF',
        'bmp': 'BMP', 'dib': 'BMP',
        'tif': 'TIFF', 'tiff': 'TIFF',
        'jxl': 'JXL',
    }

    # Formats de sortie sans canal alpha
    JPEG_OUTPUTS = {'jpg', 'jpeg', 'jfif', 'jfi', 'jpe'}

    # Formats de sortie acceptant un paramètre de qualité
    LOSSY_OUTPUTS = JPEG_OUTPUTS | {'webp', 'jxl'}

    @staticmethod
    def convert(input_path: str, output_path: str, options: dict = None) -> str:
        """
        Converts image from input_path to output_path based on options.
        Options may include:
          - quality (int 1-100)
          - width (int)
          - height (int)
          - keep_aspect_ratio (bool)
          - source_format (str) : format réel détecté, prioritaire sur l'extension
        Returns output_path on success.
        """
        if options is None:
            options = {}

        ext_out = os.path.splitext(output_path)[1].lower().replace('.', '')
        parse_quality(options)
        parse_keep_aspect_ratio(options)

        if ImageConverter._is_svg_source(input_path, options):
            return ImageConverter._convert_svg(input_path, output_path, options)

        # Open image with Pillow or fallback
        with ImageConverter._open_image(input_path, options) as img:
            # Handle RGBA to RGB for formats that don't support alpha (like JPEG)
            if ext_out in ImageConverter.JPEG_OUTPUTS and img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            elif ext_out in ImageConverter.JPEG_OUTPUTS and img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            elif ext_out not in ImageConverter.JPEG_OUTPUTS and img.mode != 'RGBA' and img.mode != 'RGB':
                img = img.convert('RGBA')

            img = ImageConverter._resize_image(img, options)
            ImageConverter._save(img, output_path, ext_out, options)

        return output_path

    @staticmethod
    def _parse_dimension(value, label: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"La {label} doit être un entier compris entre {ImageConverter.MIN_DIMENSION} et {ImageConverter.MAX_DIMENSION} pixels.")
        try:
            dim = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"La {label} est invalide.") from exc
        if dim < ImageConverter.MIN_DIMENSION or dim > ImageConverter.MAX_DIMENSION:
            raise ValueError(
                f"La {label} doit être comprise entre {ImageConverter.MIN_DIMENSION} et {ImageConverter.MAX_DIMENSION} pixels."
            )
        return dim

    @staticmethod
    def _resize_image(img: Image.Image, options: dict) -> Image.Image:
        width = options.get('width')
        height = options.get('height')
        keep_aspect = parse_keep_aspect_ratio(options)

        if width is not None or height is not None:
            orig_w, orig_h = img.size
            new_w = ImageConverter._parse_dimension(width, "largeur") if width is not None else orig_w
            new_h = ImageConverter._parse_dimension(height, "hauteur") if height is not None else orig_h

            if keep_aspect:
                if width is not None and height is None:
                    new_h = max(1, int(orig_h * (new_w / orig_w)))
                elif height is not None and width is None:
                    new_w = max(1, int(orig_w * (new_h / orig_h)))
                else:
                    img = img.copy()
                    img.thumbnail((new_w, new_h), Image.Resampling.LANCZOS)
                    new_w, new_h = img.size

            if new_w > ImageConverter.MAX_DIMENSION or new_h > ImageConverter.MAX_DIMENSION:
                raise ValueError(
                    f"Les dimensions calculées dépassent le plafond de {ImageConverter.MAX_DIMENSION} pixels."
                )

            img = img.resize((max(1, new_w), max(1, new_h)), Image.Resampling.LANCZOS)
        return img

    @staticmethod
    def _open_image(input_path: str, options: dict = None) -> Image.Image:
        try:
            return Image.open(input_path)
        except Exception as e:
            source_format = (options or {}).get('source_format')
            ext = os.path.splitext(input_path)[1].lower()
            if source_format == 'jxl' or ext == '.jxl':
                with open(input_path, 'rb') as f:
                    data = f.read()
                _check_jxl_dimensions(data)
                try:
                    import imagecodecs
                    import numpy as np
                    arr = imagecodecs.jpegxl_decode(data)
                    if arr.dtype == np.uint16:
                        arr = (arr / 256).astype(np.uint8)
                    elif arr.dtype in (np.float32, np.float64):
                        arr = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
                    return Image.fromarray(arr)
                except Exception:
                    pass
            raise e

    @staticmethod
    def _is_svg_source(input_path: str, options: dict) -> bool:
        """Le format détecté prime sur l'extension du fichier."""
        source_format = (options or {}).get('source_format')
        if source_format:
            return str(source_format).lower() == 'svg'
        return os.path.splitext(input_path)[1].lower() in ('.svg', '.svgz')

    @staticmethod
    def _read_svg_text(input_path: str) -> str:
        """Lit un fichier SVG ou SVGZ compressé de manière bornée (anti-bombe gzip)."""
        max_bytes = ImageConverter.MAX_SVG_BYTES
        with open(input_path, 'rb') as f:
            magic = f.read(2)
            f.seek(0)
            if magic == b'\x1f\x8b':
                chunks = []
                total = 0
                with gzip.GzipFile(fileobj=f, mode='rb') as gz:
                    while True:
                        chunk = gz.read(65536)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise ValueError("Fichier SVGZ trop volumineux après décompression (plafond 10 Mo dépassé).")
                        chunks.append(chunk)
                raw = b''.join(chunks)
            else:
                raw = f.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise ValueError("Fichier SVG trop volumineux (plafond 10 Mo dépassé).")

        for encoding in ('utf-8-sig', 'cp1252', 'latin-1'):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode('utf-8', errors='replace')

    @staticmethod
    def _strip_external_svg_references(svg_text: str) -> str:
        """Retire tout href qui n'est ni interne (#id) ni intégré (data:).

        resvg lit sinon les fichiers locaux désignés par <image href="...">.
        Le document est analysé (entités internes développées, entités externes
        non chargées) puis resérialisé : aucune référence ne peut se cacher dans
        une entité.
        """
        try:
            root = ET.fromstring(svg_text)
        except ET.ParseError as exc:
            raise ValueError(f"SVG invalide : {exc}") from exc
        for element in root.iter():
            for name in list(element.attrib):
                if name.rsplit('}', 1)[-1] != 'href':
                    continue
                value = element.attrib[name].strip()
                if not (value.startswith('#') or value[:5].lower() == 'data:'):
                    del element.attrib[name]
        return ET.tostring(root, encoding='unicode')

    @staticmethod
    def _save(img: Image.Image, output_path: str, ext_out: str, options: dict) -> None:
        """Enregistre l'image dans le format demandé avec les bonnes options."""
        if ext_out == 'jxl':
            try:
                import imagecodecs
                import numpy as np
                quality = parse_quality(options)
                arr = np.array(img)
                data = imagecodecs.jpegxl_encode(arr, level=quality)
                with open(output_path, 'wb') as f:
                    f.write(data)
                return
            except Exception:
                pass

        pil_format = ImageConverter.PIL_FORMATS.get(ext_out)
        save_args = {}

        if ext_out in ImageConverter.LOSSY_OUTPUTS:
            save_args['quality'] = parse_quality(options)
            if ext_out in ImageConverter.JPEG_OUTPUTS:
                save_args['progressive'] = True

        if ext_out == 'ico':
            max_side = min(img.size)
            sizes = [(s, s) for s in (16, 32, 48, 64, 128, 256) if s <= max(max_side, 16)]
            img.save(output_path, format='ICO', sizes=sizes or [(16, 16)])
        elif ext_out == 'png':
            img.save(output_path, format='PNG', optimize=True)
        elif pil_format:
            img.save(output_path, format=pil_format, **save_args)
        else:
            img.save(output_path)

    @staticmethod
    def _convert_svg(input_path: str, output_path: str, options: dict) -> str:
        """Converts SVG or SVGZ to raster image formats using resvg-py (MIT / Apache-2.0)."""
        raw_dpi = options.get('dpi', 150)
        if isinstance(raw_dpi, bool):
            raise ValueError(f"Le DPI doit être compris entre {ImageConverter.MIN_DPI} et {ImageConverter.MAX_DPI}.")
        dpi = int(raw_dpi)
        if dpi < ImageConverter.MIN_DPI or dpi > ImageConverter.MAX_DPI:
            raise ValueError(f"Le DPI doit être compris entre {ImageConverter.MIN_DPI} et {ImageConverter.MAX_DPI}.")
        zoom = dpi / 72

        try:
            svg_text = ImageConverter._strip_external_svg_references(
                ImageConverter._read_svg_text(input_path)
            )
            png_bytes = resvg_py.svg_to_bytes(svg_string=svg_text, zoom=zoom)
            with Image.open(io.BytesIO(png_bytes)) as img:
                img = ImageConverter._resize_image(img, options)
                return ImageConverter.convert_image_obj(img, output_path, options)
        except Exception as e:
            raise RuntimeError(f"Échec de conversion SVG : {e}") from e

    @staticmethod
    def convert_image_obj(img: Image.Image, output_path: str, options: dict) -> str:
        ext_out = os.path.splitext(output_path)[1].lower().replace('.', '')
        if ext_out in ImageConverter.JPEG_OUTPUTS and img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background

        ImageConverter._save(img, output_path, ext_out, options or {})
        return output_path
