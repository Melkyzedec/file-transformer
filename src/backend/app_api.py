import os
import time
import subprocess
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
import webview
import format_detector
from converters.image_converter import ImageConverter
from converters.document_converter import DocumentConverter

class AppAPI:
    """
    API bridge exposed to the JavaScript frontend via pywebview.
    """
    _WINDOWS_RESERVED_NAMES = frozenset({
        'CON', 'PRN', 'AUX', 'NUL',
        *(f'COM{i}' for i in range(1, 10)),
        *(f'LPT{i}' for i in range(1, 10)),
    })

    def __init__(self):
        self._window = None
        self._allowed_open_paths = set()
        self._allowed_open_dirs = set()

    @classmethod
    def _is_windows_reserved_path(cls, path_value) -> bool:
        """Analyse purement syntaxique : rejette CON/NUL/PRN/AUX/COM1..9/LPT1..9 sans accès disque."""
        if not isinstance(path_value, str) or not path_value.strip():
            return False
        normalized = path_value.replace('\\', '/')
        for segment in normalized.split('/'):
            part = segment.strip()
            if not part or part in ('.', '..'):
                continue
            # Ignore un préfixe lecteur Windows (ex. "C:")
            if len(part) == 2 and part[1] == ':' and part[0].isalpha():
                continue
            base = part.split('.', 1)[0].rstrip(' .').upper()
            if base in cls._WINDOWS_RESERVED_NAMES:
                return True
        return False

    def set_window(self, window):
        self._window = window

    def select_files(self):
        """Opens native file dialog for selecting source files."""
        if not self._window:
            return []

        file_types = (
            'Tous les fichiers supportés (*.png;*.jpg;*.jpeg;*.jfif;*.webp;*.svg;*.svgz;*.ico;*.gif;*.bmp;*.tif;*.tiff;*.heic;*.heif;*.jxl;*.pdf;*.docx;*.md;*.html;*.txt)',
            'Images (*.png;*.jpg;*.jpeg;*.jfif;*.webp;*.svg;*.svgz;*.ico;*.gif;*.bmp;*.tif;*.tiff;*.heic;*.heif;*.jxl)',
            'Documents (*.pdf;*.docx;*.md;*.html;*.txt)',
            'Tous les fichiers (*.*)'
        )

        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=file_types
        )
        if not result:
            return []

        return self.files_from_paths(list(result))

    def files_from_paths(self, paths):
        """
        Builds the file descriptors sent to the frontend, with automatic
        format detection based on file content (not just the extension).
        Also used by the native drag & drop handler.
        """
        file_info_list = []
        for path in paths or []:
            if not isinstance(path, str) or not path.strip():
                continue
            if self._is_windows_reserved_path(path):
                continue
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            file_info_list.append(self._file_info(path))
        return file_info_list

    def detect_format(self, path):
        """Exposes content-based format detection to the frontend."""
        if not isinstance(path, str) or not path.strip():
            return None
        if self._is_windows_reserved_path(path):
            return None
        if os.path.islink(path) or not os.path.isfile(path):
            return None
        return format_detector.detect(path)

    def _file_info(self, path):
        detection = format_detector.detect(path)
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0

        return {
            'path': path,
            'name': os.path.basename(path),
            'ext': os.path.splitext(path)[1].lower(),
            'size': size,
            'category': detection['category'],
            'format': detection['format'],
            'format_label': detection['label'],
            'format_ext': detection['ext'],
            'mime': detection['mime'],
            'detection_method': detection['method'],
            'mismatch': detection['mismatch'],
            'supported': detection['supported'],
        }

    def select_output_folder(self):
        """Opens native folder dialog for selecting output directory."""
        if not self._window:
            return None
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            self._register_allowed_open_dir(result[0])
            return result[0]
        return None

    def convert_single_file(self, input_path, target_format, options=None, output_dir=None):
        """
        Converts a single file to target_format with options.
        Returns a dict with status, output_path, execution_time, error.
        """
        if options is None:
            options = {}

        if not isinstance(input_path, str) or not input_path.strip():
            return {'success': False, 'error': "Chemin d'entrée invalide."}

        if self._is_windows_reserved_path(input_path):
            return {'success': False, 'input_path': input_path, 'error': "Nom de périphérique Windows réservé interdit."}

        if output_dir is not None:
            if not isinstance(output_dir, str) or not output_dir.strip() or self._is_windows_reserved_path(output_dir):
                return {'success': False, 'input_path': input_path, 'error': "Dossier de destination invalide."}
            if os.path.islink(output_dir):
                return {'success': False, 'input_path': input_path, 'error': "Les liens symboliques ne sont pas autorisés en destination."}

        if os.path.islink(input_path):
            return {'success': False, 'input_path': input_path, 'error': "Les liens symboliques ne sont pas autorisés en entrée."}

        if not os.path.isfile(input_path):
            return {'success': False, 'error': f"Fichier introuvable : {input_path}"}

        detection = format_detector.detect(input_path)
        if not isinstance(target_format, str) or not target_format.replace('.', '').isalnum():
            return {'success': False, 'input_path': input_path, 'error': 'Format de sortie invalide.'}
        target_format = target_format.lower().replace('.', '')

        if not detection['format']:
            return {
                'success': False,
                'input_path': input_path,
                'error': "Format du fichier non reconnu."
            }

        if not detection['supported']:
            return {
                'success': False,
                'input_path': input_path,
                'error': f"Format reconnu ({detection['label']}) mais non pris en charge en entrée."
            }

        allowed_outputs = (
            ImageConverter.SUPPORTED_OUTPUTS
            if detection['category'] == 'image'
            else DocumentConverter.SUPPORTED_OUTPUTS
            if detection['category'] == 'document'
            else frozenset()
        )
        if target_format not in allowed_outputs:
            return {
                'success': False,
                'input_path': input_path,
                'error': f"Format de sortie non autorisé : {target_format}"
            }

        destination = Path(output_dir or os.path.dirname(input_path) or '.')
        if not destination.is_dir():
            return {'success': False, 'input_path': input_path, 'error': "Dossier de destination introuvable."}

        base_name = os.path.splitext(os.path.basename(input_path))[0]
        output_stem = f"{base_name}_converted"
        output_filename = f"{output_stem}.{target_format}"

        # Les convertisseurs se fient au format détecté, pas à l'extension.
        options = dict(options)
        options['source_format'] = detection['format']

        start_time = time.time()
        try:
            if detection['category'] == 'image':
                convert = ImageConverter.convert
            elif detection['category'] == 'document':
                convert = DocumentConverter.convert
            else:
                return {'success': False, 'error': f"Format d'entrée non supporté : {detection['label']}"}

            with TemporaryDirectory(prefix='.file-transformer-', dir=destination) as directory:
                staging = Path(directory)
                first_output = Path(convert(input_path, str(staging / output_filename), options))
                if not first_output.is_file():
                    raise OSError('La conversion n’a produit aucun fichier.')
                staged_files = sorted(staging.iterdir())
                published = self._publish_outputs(staged_files, destination, output_stem)
                final_output = published[first_output]

            for output_file in published.values():
                self._register_allowed_open_path(output_file)

            duration = round(time.time() - start_time, 2)

            return {
                'success': True,
                'input_path': input_path,
                'output_path': str(final_output),
                'output_name': final_output.name,
                'duration': duration,
                'size': final_output.stat().st_size
            }
        except Exception as e:
            return {
                'success': False,
                'input_path': input_path,
                'error': str(e)
            }

    @staticmethod
    def _publish_outputs(staged_files, destination, stem):
        """Use one suffix for a whole conversion and never replace an existing file."""
        windows = os.name == 'nt'
        for sequence in count(1):
            unique_stem = stem if sequence == 1 else f'{stem}_{sequence}'
            targets = {source: destination / (unique_stem + source.name[len(stem):])
                       for source in staged_files}
            for target in targets.values():
                if target.is_dir():
                    raise IsADirectoryError(f'Un dossier occupe la sortie : {target.name}')
            if any(os.path.lexists(target) for target in targets.values()):
                continue

            moved = {}
            try:
                for source, target in targets.items():
                    # Windows rename refuses to replace. POSIX rename would overwrite.
                    if windows:
                        source.rename(target)
                    else:
                        os.link(source, target)
                    moved[source] = target
            except OSError as error:
                leftovers = []
                for source, target in reversed(list(moved.items())):
                    try:
                        if windows:
                            target.rename(source)
                        else:
                            target.unlink()
                    except OSError:
                        leftovers.append(target.name)
                if leftovers:
                    raise OSError(f'Sorties partielles : {", ".join(leftovers)}') from error
                if not isinstance(error, FileExistsError):
                    raise
            else:
                return targets

    @staticmethod
    def _normalize_path_key(path_value):
        return os.path.normcase(str(Path(path_value).resolve()))

    def _register_allowed_open_dir(self, dir_path):
        try:
            self._allowed_open_dirs.add(self._normalize_path_key(dir_path))
        except (OSError, ValueError):
            pass

    def _register_allowed_open_path(self, file_path):
        try:
            resolved = Path(file_path).resolve()
            self._allowed_open_paths.add(os.path.normcase(str(resolved)))
            self._allowed_open_dirs.add(os.path.normcase(str(resolved.parent)))
        except (OSError, ValueError):
            pass

    def _is_allowed_open_path(self, resolved_path):
        key = os.path.normcase(str(resolved_path))
        return key in self._allowed_open_paths or key in self._allowed_open_dirs

    @staticmethod
    def _resolve_explorer_executable():
        system_root = os.environ.get('SystemRoot') or r'C:\Windows'
        explorer_exe = os.path.normpath(os.path.join(system_root, 'explorer.exe'))
        if os.path.isfile(explorer_exe):
            return explorer_exe
        return None

    def open_folder(self, file_path):
        """Opens Windows Explorer on an authorized session file or folder without shell."""
        if not isinstance(file_path, str) or not file_path.strip():
            return False
        try:
            resolved = Path(file_path).resolve()
        except (OSError, ValueError):
            return False

        if not self._is_allowed_open_path(resolved):
            return False

        explorer_exe = self._resolve_explorer_executable()
        if not explorer_exe:
            return False

        key = os.path.normcase(str(resolved))
        try:
            if key in self._allowed_open_paths and resolved.is_file():
                subprocess.Popen([explorer_exe, f"/select,{resolved}"], shell=False)
                return True
            if key in self._allowed_open_dirs and resolved.is_dir():
                subprocess.Popen([explorer_exe, str(resolved)], shell=False)
                return True
            parent_key = os.path.normcase(str(resolved.parent))
            if parent_key in self._allowed_open_dirs and resolved.parent.is_dir():
                subprocess.Popen([explorer_exe, str(resolved.parent)], shell=False)
                return True
        except OSError:
            return False
        return False

    def get_supported_formats(self):
        """Returns dictionary of supported conversion targets per category."""
        return {
            'image': {
                'inputs': sorted(ImageConverter.SUPPORTED_INPUTS),
                'outputs': [
                    {'ext': 'png', 'name': 'PNG (Image avec transparence)'},
                    {'ext': 'jpg', 'name': 'JPG/JPEG (Compressé)'},
                    {'ext': 'jfif', 'name': 'JFIF (JPEG/JFIF)'},
                    {'ext': 'webp', 'name': 'WebP (Web haute efficacité)'},
                    {'ext': 'jxl', 'name': 'JPEG XL (Nouvelle génération haute compression)'},
                    {'ext': 'ico', 'name': 'ICO (Icône Windows/Favicon)'},
                    {'ext': 'gif', 'name': 'GIF (Image/Animation)'},
                    {'ext': 'bmp', 'name': 'BMP (Bitmap non compressé)'}
                ]
            },
            'document': {
                'inputs': sorted(DocumentConverter.SUPPORTED_INPUTS),
                'outputs': [
                    {'ext': 'pdf', 'name': 'PDF (Document portable)'},
                    {'ext': 'html', 'name': 'HTML (Page Web)'},
                    {'ext': 'txt', 'name': 'TXT (Texte brut)'},
                    {'ext': 'md', 'name': 'Markdown (.md)'},
                    {'ext': 'png', 'name': 'PNG (Export de pages PDF en image)'},
                    {'ext': 'jpg', 'name': 'JPG (Export de pages PDF en image)'}
                ]
            }
        }
