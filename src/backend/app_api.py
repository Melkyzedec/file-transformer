import errno
import logging
import os
import re
import time
import subprocess
import traceback
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
import webview
import format_detector
from converters.image_converter import ImageConverter
from converters.document_converter import DocumentConverter
from PIL import Image

# Détail technique des échecs (bibliothèque, chemin complet) : journal de
# débogage seulement, jamais affiché dans l'interface.
logger = logging.getLogger('file_transformer')
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

_ACTION_RETRY = "Réessayez ; si le problème continue, choisissez un autre format de sortie."

# Messages écrits par nos convertisseurs, reformulés en « cause + action » sans
# jargon. Les mots-clés vérifiés par les tests de sécurité restent présents.
_OWN_MESSAGE_REWRITES = (
    ("trop d'entrées", "Ce document Word est trop complexe (trop d'entrées internes) : il n'a pas été ouvert, "
                       "par précaution. Réenregistrez-le depuis Word, puis réessayez."),
    ("chemin interdit", "Ce document Word contient un chemin interdit : il n'a pas été ouvert, par précaution. "
                        "Réenregistrez-le depuis Word, puis réessayez."),
    ("Ratio de compression suspect", "Ce document Word n'a pas été ouvert, par précaution. Ratio de compression "
                                     "suspect : une fois décompressé, il serait anormalement gros. "
                                     "Réenregistrez-le depuis Word, puis réessayez."),
    ("trop volumineuse après décompression", "Ce document Word dépasse 50 Mo une fois décompressé : il n'a pas "
                                             "été ouvert. Réduisez la taille des images qu'il contient, puis réessayez."),
    ("Fichier DOCX corrompu", "Ce document Word n'a pas pu être ouvert : il est peut-être abîmé. "
                              "Ouvrez-le dans Word et réenregistrez-le, puis réessayez."),
    ("Échec de la génération PDF", "Le PDF n'a pas pu être créé à partir de ce document. "
                                   "Réessayez avec une autre sortie (HTML ou TXT)."),
    ("ne contient aucune page", "Ce PDF ne contient aucune page : il n'y a rien à convertir. Retirez-le de la liste."),
    ("aucun fichier", "La conversion n'a produit aucun fichier. " + _ACTION_RETRY),
    ("En-tête JPEG XL illisible", None),  # même message qu'un fichier abîmé
)
_OWN_MESSAGE_ACTIONS = (
    ("l'export en images est limité", " Exportez-le plutôt en texte (TXT) ou découpez-le en plusieurs PDF."),
    ("plafond 10 Mo", " Simplifiez le dessin ou exportez-le en PNG depuis son logiciel, puis réessayez."),
    ("trop grande", " Réduisez ses dimensions dans un autre logiciel, puis réessayez."),
    ("Un dossier occupe la sortie", " Renommez ce dossier ou choisissez un autre dossier de destination."),
    ("Sorties partielles", " Retirez ces fichiers du dossier de destination, puis réessayez."),
    ("doit être", " Corrigez la valeur dans les réglages avancés, puis réessayez."),
    ("est invalide", " Corrigez la valeur dans les réglages avancés, puis réessayez."),
)

class AppAPI:
    """
    API bridge exposed to the JavaScript frontend via pywebview.
    """
    # Liste de la documentation Windows (« Naming Files, Paths, and Namespaces ») :
    # COM0/LPT0 et les chiffres en exposant ¹ ² ³ sont aussi des périphériques.
    _WINDOWS_RESERVED_NAMES = frozenset({
        'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$',
        *(f'COM{i}' for i in '0123456789¹²³'),
        *(f'LPT{i}' for i in '0123456789¹²³'),
    })

    def __init__(self):
        self._window = None
        self._allowed_open_paths = set()
        self._allowed_open_dirs = set()

    @classmethod
    def _is_windows_reserved_path(cls, path_value) -> bool:
        """Analyse purement syntaxique, sans accès disque : noms de périphériques Windows et espace \\\\.\\."""
        if not isinstance(path_value, str) or not path_value.strip():
            return False
        normalized = path_value.replace('\\', '/')
        # Espace de noms des périphériques Win32 (\\.\PhysicalDrive0, \\.\pipe\...).
        # Le préfixe \\?\ des chemins longs reste permis.
        if normalized.startswith('//./'):
            return True
        for segment in normalized.split('/'):
            part = segment.strip()
            if not part or part in ('.', '..'):
                continue
            # Ignore un préfixe lecteur Windows (ex. "C:")
            if len(part) == 2 and part[1] == ':' and part[0].isalpha():
                continue
            # "NUL:" et "CON.txt:flux" : le nom précède un éventuel flux NTFS.
            name = part.split(':', 1)[0]
            base = name.split('.', 1)[0].rstrip(' .').upper()
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

        return self._analyze_paths(list(result))

    # Raccourcis Windows : ce sont des fichiers ordinaires pour le système.
    _SHORTCUT_EXTENSIONS = frozenset({'.lnk', '.url'})

    @staticmethod
    def _display_name(path_value) -> str:
        """Dernier segment du chemin, par simple analyse de texte (aucun accès disque)."""
        if not isinstance(path_value, str):
            return ''
        return path_value.replace('\\', '/').rstrip('/').rsplit('/', 1)[-1].strip()

    def _analyze_paths(self, paths):
        """
        Sépare les fichiers convertibles des éléments ignorés, pour que rien ne
        disparaisse en silence : {'files': [...], 'ignored': [{'name', 'reason'}]}.
        reason : folder, shortcut, reserved, missing ou invalid. Seul le nom est
        renvoyé pour un élément ignoré, jamais son dossier.
        """
        files, ignored = [], []
        for path in paths or []:
            name = self._display_name(path)
            if not isinstance(path, str) or not path.strip():
                reason = 'invalid'
            elif self._is_windows_reserved_path(path):
                reason = 'reserved'
            elif os.path.islink(path):
                reason = 'shortcut'
            elif os.path.isdir(path):
                reason = 'folder'
            elif not os.path.isfile(path):
                reason = 'missing' if not os.path.exists(path) else 'invalid'
            elif os.path.splitext(path)[1].lower() in self._SHORTCUT_EXTENSIONS:
                reason = 'shortcut'
            else:
                files.append(self._file_info(path))
                continue
            ignored.append({'name': name, 'reason': reason})
        return {'files': files, 'ignored': ignored}

    def _dropped_files_payload(self, entries):
        """Analyse les fichiers d'un dépôt natif (dataTransfer.files de pywebview)."""
        paths, unnamed = [], []
        for entry in entries or []:
            entry = entry if isinstance(entry, dict) else {}
            path = entry.get('pywebviewFullPath')
            if isinstance(path, str) and path.strip():
                paths.append(path)
            else:
                unnamed.append({'name': self._display_name(entry.get('name')), 'reason': 'invalid'})
        payload = self._analyze_paths(paths)
        payload['ignored'].extend(unnamed)
        return payload

    def files_from_paths(self, paths):
        """
        Builds the file descriptors sent to the frontend, with automatic
        format detection based on file content (not just the extension).
        Les éléments ignorés sont décrits par _analyze_paths().
        """
        return self._analyze_paths(paths)['files']

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
            return {'success': False, 'error': "Ce fichier n'a pas pu être trouvé (chemin vide). Ajoutez-le à nouveau à la liste."}

        if self._is_windows_reserved_path(input_path):
            return {'success': False, 'input_path': input_path, 'error': (
                "Ce nom est réservé par Windows (CON, NUL, COM1…) et ne peut pas être utilisé. "
                "Renommez le fichier ou son dossier, puis ajoutez-le à nouveau.")}

        if output_dir is not None:
            if not isinstance(output_dir, str) or not output_dir.strip() or self._is_windows_reserved_path(output_dir):
                return {'success': False, 'input_path': input_path, 'error': (
                    "Le dossier de destination n'est pas utilisable. Choisissez-en un autre.")}
            if os.path.islink(output_dir):
                return {'success': False, 'input_path': input_path, 'error': (
                    "Le dossier de destination est un raccourci ou un lien. Choisissez directement le dossier réel.")}

        if os.path.islink(input_path):
            return {'success': False, 'input_path': input_path, 'error': (
                "Les raccourcis et liens ne sont pas pris en charge. Ajoutez directement le fichier d'origine.")}

        if not os.path.isfile(input_path):
            return {'success': False, 'error': (
                f"Fichier introuvable : {os.path.basename(input_path)}. Il a peut-être été déplacé ou supprimé ; "
                "ajoutez-le à nouveau à la liste.")}

        detection = format_detector.detect(input_path)
        if not isinstance(target_format, str) or not target_format.replace('.', '').isalnum():
            return {'success': False, 'input_path': input_path, 'error': (
                "Format de sortie non reconnu. Choisissez un format dans la liste.")}
        target_format = target_format.lower().replace('.', '')

        if not detection['format']:
            return {
                'success': False,
                'input_path': input_path,
                'error': ("Le type de ce fichier n'a pas été reconnu : il ne peut pas être converti ici. "
                          "Retirez-le de la liste."),
            }

        if not detection['supported']:
            return {
                'success': False,
                'input_path': input_path,
                'error': (f"Ce fichier ({detection['label']}) ne peut pas être converti ici. "
                          "Enregistrez-le en PDF depuis son logiciel, puis ajoutez ce PDF."),
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
                'error': (f"La sortie {target_format.upper()} n'est pas disponible pour ce fichier. "
                          "Choisissez une autre sortie dans la liste."),
            }

        if detection['category'] == 'document':
            possible = DocumentConverter.OUTPUTS_BY_SOURCE.get(detection['format'], ())
            if target_format not in possible:
                return {
                    'success': False,
                    'input_path': input_path,
                    'error': (
                        f"La conversion {detection['label']} vers {target_format.upper()} n'est pas disponible. "
                        f"Choisissez plutôt : {', '.join(fmt.upper() for fmt in possible)}."
                    ),
                }

        destination = Path(output_dir or os.path.dirname(input_path) or '.')
        if not destination.is_dir():
            return {'success': False, 'input_path': input_path, 'error': (
                "Le dossier de destination n'existe plus. Choisissez-en un autre.")}

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
                return {'success': False, 'error': (
                    f"Ce fichier ({detection['label']}) ne peut pas être converti ici. Retirez-le de la liste.")}

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
            logger.debug("Échec de conversion de %s vers %s", input_path, target_format, exc_info=e)
            return {
                'success': False,
                'input_path': input_path,
                'error': self._public_error(
                    e, (os.path.dirname(os.path.abspath(input_path)), destination),
                    input_name=os.path.basename(input_path), source_format=detection['format'],
                )
            }

    @staticmethod
    def _raised_by_app(error) -> bool:
        """Vrai si le message a été écrit par nos convertisseurs (en français).

        L'exception doit venir d'une instruction « raise Xxx(...) » de src/backend
        et ne pas recopier le message brut d'une bibliothèque.
        """
        frames = traceback.extract_tb(error.__traceback__)
        if not frames:
            return False
        last = frames[-1]
        line = (last.line or '').strip()
        if not os.path.abspath(last.filename).startswith(_BACKEND_DIR + os.sep):
            return False
        if not line.startswith('raise ') or re.fullmatch(r'raise\s+\w+', line):
            return False
        cause = error.__cause__
        return not (cause is not None and str(cause).strip() and str(cause).strip() in str(error))

    @staticmethod
    def _unreadable_message(name, source_format) -> str:
        if source_format == 'pdf':
            return (f"Le PDF « {name} » n'a pas pu être ouvert : il est peut-être abîmé ou protégé par un mot "
                    "de passe. Ouvrez-le dans un lecteur PDF pour vérifier, puis réessayez.")
        if source_format == 'docx':
            return (f"Le document Word « {name} » n'a pas pu être lu : il est peut-être abîmé. "
                    "Ouvrez-le dans Word et réenregistrez-le, puis réessayez.")
        if source_format == 'svg':
            return (f"Le dessin SVG « {name} » n'a pas pu être lu : il est peut-être abîmé, incomplet ou vide. "
                    "Ouvrez-le dans son logiciel pour vérifier, puis réessayez.")
        if source_format in format_detector.FORMATS and format_detector.FORMATS[source_format]['category'] == 'image':
            return (f"L'image « {name} » n'a pas pu être lue : elle est peut-être abîmée ou incomplète. "
                    "Ouvrez-la dans un autre logiciel pour vérifier, puis réessayez ou retirez-la de la liste.")
        return (f"Le fichier « {name} » n'a pas pu être lu : il est peut-être abîmé ou contient un élément non "
                "pris en charge. Ouvrez-le dans son logiciel habituel pour vérifier, puis réessayez.")

    @classmethod
    def _friendly_message(cls, error, input_name, source_format) -> str:
        """Cause probable + action, en français, à partir d'une exception quelconque."""
        name = input_name or 'ce fichier'
        if cls._raised_by_app(error) and str(error).strip():
            message = str(error).strip()
            for keyword, rewrite in _OWN_MESSAGE_REWRITES:
                if keyword in message:
                    return rewrite or cls._unreadable_message(name, source_format)
            for keyword, action in _OWN_MESSAGE_ACTIONS:
                if keyword in message:
                    return message + action
            return message
        if isinstance(error, MemoryError):
            return "Mémoire insuffisante pour cette conversion. Réduisez la taille ou la résolution."
        if isinstance(error, OSError) and error.errno is not None:
            target = os.path.basename(str(error.filename)) if error.filename else name
            if isinstance(error, PermissionError):
                return (f"Accès refusé à « {target} ». Fermez ce fichier s'il est ouvert dans un autre logiciel, "
                        "ou choisissez un autre dossier de destination.")
            if error.errno == errno.ENOSPC:
                return (f"Espace disque insuffisant pour créer « {target} ». Libérez de la place ou choisissez "
                        "un autre dossier de destination.")
            if isinstance(error, FileNotFoundError):
                return (f"Fichier introuvable : « {target} ». Il a peut-être été déplacé ou supprimé ; "
                        "ajoutez-le à nouveau à la liste.")
            return (f"« {target} » n'a pas pu être lu ou écrit. Vérifiez que le dossier de destination est "
                    "accessible, ou choisissez-en un autre.")
        if isinstance(error, (Image.DecompressionBombError, Image.DecompressionBombWarning)):
            return (f"L'image « {name} » est trop grande pour être convertie sans risque. "
                    "Réduisez ses dimensions dans un autre logiciel, puis réessayez.")
        return cls._unreadable_message(name, source_format)

    @classmethod
    def _public_error(cls, error, directories, input_name=None, source_format=None):
        """Message d'erreur affichable : français clair, sans dossier complet, jamais vide."""
        message = cls._friendly_message(error, input_name, source_format).strip()
        if not message:
            message = f"Erreur inattendue pendant la conversion. {_ACTION_RETRY}"
        prefixes = set()
        for directory in directories:
            for variant in (str(directory), os.path.abspath(str(directory))):
                variant = variant.rstrip('\\/')
                if len(variant) > 3:  # jamais une simple racine (« / », « C: »)
                    prefixes.add(variant)
        # Du plus long au plus court, y compris la forme échappée des repr() Windows.
        for prefix in sorted(prefixes, key=len, reverse=True):
            for form in (prefix, prefix.replace('\\', '\\\\')):
                for separator in ('\\\\', '\\', '/'):
                    message = message.replace(form + separator, '')
                message = message.replace(form, '…')
        return message

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
