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
    def __init__(self):
        self._window = None

    def set_window(self, window):
        self._window = window

    def select_files(self):
        """Opens native file dialog for selecting source files."""
        if not self._window:
            return []

        file_types = (
            'Tous les fichiers supportés (*.png;*.jpg;*.jpeg;*.jfif;*.webp;*.svg;*.ico;*.gif;*.bmp;*.tif;*.tiff;*.heic;*.heif;*.jxl;*.pdf;*.docx;*.md;*.html;*.txt)',
            'Images (*.png;*.jpg;*.jpeg;*.jfif;*.webp;*.svg;*.ico;*.gif;*.bmp;*.tif;*.tiff;*.heic;*.heif;*.jxl)',
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
            if not path or not os.path.isfile(path):
                continue
            file_info_list.append(self._file_info(path))
        return file_info_list

    def detect_format(self, path):
        """Exposes content-based format detection to the frontend."""
        if not path or not os.path.isfile(path):
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
            return result[0]
        return None

    def convert_single_file(self, input_path, target_format, options=None, output_dir=None):
        """
        Converts a single file to target_format with options.
        Returns a dict with status, output_path, execution_time, error.
        """
        if options is None:
            options = {}

        if not os.path.exists(input_path):
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

        destination = Path(output_dir or os.path.dirname(input_path) or '.')

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
                final_output = self._publish_outputs(staged_files, destination, output_stem)[first_output]

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

    def open_folder(self, file_path):
        """Opens File Explorer with the specified file selected."""
        if not file_path:
            return False
        try:
            if os.path.exists(file_path):
                subprocess.run(f'explorer /select,"{os.path.abspath(file_path)}"', shell=True)
                return True
            elif os.path.exists(os.path.dirname(file_path)):
                subprocess.run(f'explorer "{os.path.abspath(os.path.dirname(file_path))}"', shell=True)
                return True
        except Exception as e:
            print(f"Error opening folder: {e}")
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
