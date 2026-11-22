import json
import os
import sys

# Ensure backend modules are in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src', 'backend'))

import webview
from webview.dom import DOMEventHandler
from app_api import AppAPI

def main():
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
        """
        Le navigateur embarqué n'expose pas le chemin réel des fichiers déposés.
        pywebview le fournit côté Python via 'pywebviewFullPath' : on analyse les
        fichiers ici puis on renvoie le résultat au frontend.
        """
        files = (event.get('dataTransfer') or {}).get('files') or []
        paths = [f.get('pywebviewFullPath') for f in files if f.get('pywebviewFullPath')]
        if not paths:
            return
        payload = json.dumps(api.files_from_paths(paths))
        window.evaluate_js(
            f'window.onNativeFilesDropped && window.onNativeFilesDropped({payload})'
        )

    def on_loaded():
        window.dom.body.on('drop', DOMEventHandler(on_drop, prevent_default=True))

    window.events.loaded += on_loaded
    webview.start(debug=False)

if __name__ == '__main__':
    main()
