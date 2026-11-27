import json
import logging
import os
import sys

# Ensure backend modules are in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src', 'backend'))

import webview
from webview.dom import DOMEventHandler
from app_api import AppAPI

def configure_debug_logging():
    """
    Lancement avec console (« Lancer File Transformer.bat debug » ou python.exe) :
    affiche le détail technique des échecs, que l'interface ne montre jamais.
    Sans console (pythonw.exe), rien n'est configuré.
    """
    if sys.stderr is None:
        return
    logger = logging.getLogger('file_transformer')
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter('[File Transformer] %(levelname)s %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)


def build_drop_script(api, event):
    """
    Le navigateur embarqué n'expose pas le chemin réel des fichiers déposés.
    pywebview le fournit côté Python via 'pywebviewFullPath' : on analyse les
    fichiers ici puis on renvoie au frontend les fichiers retenus et les
    éléments ignorés (dossier, raccourci, nom réservé...), pour qu'aucun dépôt
    ne disparaisse sans explication.
    """
    entries = ((event or {}).get('dataTransfer') or {}).get('files') or []
    if not entries:
        return None
    payload = json.dumps(api._dropped_files_payload(entries))
    return f'window.onNativeFilesDropped && window.onNativeFilesDropped({payload})'


def main():
    configure_debug_logging()
    api = AppAPI()

    frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'src', 'frontend', 'index.html'))

    window = webview.create_window(
        title='File Transformer — Convertisseur de Fichiers',
        url=frontend_path,
        js_api=api,
        width=1120,
        height=780,
        min_size=(900, 620),
        background_color='#202320'
    )

    api.set_window(window)

    def on_drop(event):
        script = build_drop_script(api, event)
        if script:
            window.evaluate_js(script)

    def on_loaded():
        window.dom.body.on('drop', DOMEventHandler(on_drop, prevent_default=True))

    window.events.loaded += on_loaded
    webview.start(debug=False)

if __name__ == '__main__':
    main()
