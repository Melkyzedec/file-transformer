# File Transformer

Application Windows pour convertir des images (PNG, JPEG/JFIF, WebP, JXL, ICO, GIF, BMP, TIFF, HEIC/HEIF, SVG/SVGZ) et des documents (PDF, DOCX, Markdown, HTML, TXT). Le format d’entrée est détecté à partir du contenu du fichier. Des raccourcis permettent notamment de convertir une image PNG en WebP ou d’exporter les pages d’un PDF en images, texte ou HTML.

## Installer et lancer sur Windows

1. Depuis la [page du projet](https://github.com/Melkyzedec/file-transformer), choisissez **Code → Download ZIP** dans votre navigateur habituel.
2. Dans l’Explorateur Windows, cliquez droit sur le ZIP et choisissez **Extraire tout**. Ouvrez le dossier extrait qui contient à la fois `main.py`, `requirements.txt` et `Lancer File Transformer.bat`. Si deux dossiers portent le même nom, ouvrez celui du dedans.
3. Double-cliquez sur **Lancer File Transformer.bat**. Le lanceur réutilise le Python de `.venv` si elle existe. Au premier lancement, il crée cet environnement dans le dossier de l’application, puis installe les dépendances. Laissez la console ouverte pendant cette étape.

### Prérequis

- [Python 3.14 x64](https://www.python.org/downloads/windows/) est la version recommandée. Le lanceur accepte aussi un Python utilisable à partir de la version 3.10. Il peut utiliser un Python standard installé pour votre compte ou un Python déjà disponible dans `.runtime\python\python.exe`.
- [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/#download-section) sert à afficher l’interface Windows.
- Le dossier extrait doit être accessible en écriture et le premier lancement doit pouvoir télécharger les dépendances Python.

### Si le premier lancement échoue

- **Python introuvable**. Installez Python pour votre compte, puis relancez le fichier `.bat`.
- **Environnement `.venv` inutilisable**. Si le dossier de l’application a été déplacé, renommez `.venv` en `.venv-ancienne`, puis relancez le fichier `.bat` pour créer un environnement au nouvel emplacement.
- **Installation des dépendances interrompue**. Relancez le fichier `.bat` une fois la connexion rétablie. La console affiche l’étape et le message en cas d’échec.

## Faire une première conversion

1. Cliquez sur **Ajouter des fichiers** et choisissez l’image fictive `tests\fixtures\exemple.png`.
2. Cliquez sur le raccourci **PNG → WebP**, puis sur **Lancer la conversion**.
3. Ouvrez `tests\fixtures\exemple_converted.webp` et vérifiez que l’image contient les quatre mêmes aplats de couleur. Avec un autre dossier de destination, cherchez le résultat dans ce dossier.

## Signaler un problème ou contribuer

En cas de souci, lancez l’application depuis PowerShell (ou via `Lancer File Transformer.bat debug`) pour afficher le message d’erreur. Ouvrez une issue en indiquant la version de Windows, la version de Python, l’étape concernée et un fichier fictif reproduisant le problème (aucune donnée personnelle). Les propositions d’amélioration sont bienvenues par pull request.

## Licence

Ce projet est distribué sous [licence MIT](LICENSE). Les dépendances Python et le runtime WebView2 s’installent séparément et restent soumis à leurs propres licences. Voir [Dépendances et licences](THIRD_PARTY.md).