# File Transformer

Application Windows pour convertir des images (PNG, JPEG/JFIF, WebP, JXL, ICO, GIF, BMP, TIFF, HEIC/HEIF, SVG/SVGZ) et des documents (PDF, DOCX, Markdown, HTML, TXT). Le format d’entrée est détecté à partir du contenu du fichier. Des raccourcis permettent notamment de convertir une image PNG en WebP ou d’exporter les pages d’un PDF en images, texte ou HTML.

## Préparer Windows

Les instructions ci-dessous ont été vérifiées avec Python 3.14 x64 (compatible Python 3.10+). Installez [Python](https://www.python.org/downloads/windows/) avec le lanceur `py` et une version récente du [runtime Microsoft Edge WebView2](https://developer.microsoft.com/microsoft-edge/webview2/#download-section).

Extrayez tout le ZIP (ou clonez le dépôt). Dans PowerShell, ouvert dans le dossier `file-transformer`, créez un environnement isolé et installez les dépendances :

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Si vous installez les dépendances dans le Python par défaut du système, vous pouvez aussi démarrer en double-cliquant sur `Lancer File Transformer.bat`.

## Faire une première conversion

1. Cliquez sur **Ajouter des fichiers** et choisissez l’image fictive `tests\fixtures\exemple.png`.
2. Cliquez sur le raccourci **PNG → WebP**, puis sur **Lancer la conversion**.
3. Ouvrez `tests\fixtures\exemple_converted.webp` et vérifiez que l’image contient les quatre mêmes aplats de couleur. Avec un autre dossier de destination, cherchez le résultat dans ce dossier.

## Signaler un problème ou contribuer

En cas de souci, lancez l’application depuis PowerShell (ou via `Lancer File Transformer.bat debug`) pour afficher le message d’erreur. Ouvrez une issue en indiquant la version de Windows, la version de Python, l’étape concernée et un fichier fictif reproduisant le problème (aucune donnée personnelle). Les propositions d’amélioration sont bienvenues par pull request.

## Licence

Ce projet est distribué sous [licence MIT](LICENSE). Les dépendances Python et le runtime WebView2 s’installent séparément et restent soumis à leurs propres licences. Voir [Dépendances et licences](THIRD_PARTY.md).