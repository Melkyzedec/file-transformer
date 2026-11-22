# Dépendances et licences

Les paquets listés dans `requirements.txt` et le runtime Microsoft Edge WebView2 sont installés séparément par l’utilisateur. Ce dépôt contient uniquement les sources de File Transformer (licence MIT) et une image de test synthétique.

## Dépendances directes (`requirements.txt`)

| Dépendance directe | Version vérifiée (Windows Python 3.14) | Licence déclarée |
| --- | --- | --- |
| pywebview | 6.2.1 | BSD-3-Clause |
| Pillow | 13.0.0 | MIT-CMU |
| pypdfium2 | 5.15.2 | Apache-2.0 / BSD-3-Clause (PDFium et dépendances permissives de la roue) |
| xhtml2pdf | 0.2.28 | Apache-2.0 |
| resvg-py | 0.5.0 | MIT (encapsule `resvg`, Apache-2.0 / MIT) |
| python-docx | 1.2.0 | MIT |
| Markdown | 3.11.3 | BSD-3-Clause |
| reportlab | 5.1.0 | BSD |
| pillow-heif | 1.8.1 | BSD-3-Clause (la roue embarque `libheif`, LGPL-3.0) |
| imagecodecs | 2026.11.11 | BSD-3-Clause |
| NumPy | 2.5.5 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |

## Dépendances transitives notables

Les paquets suivants sont installés séparément par `pip` comme dépendances transitives :

- `svglib` 2.4.0 (`LGPL-3.0-or-later`), dépendance transitive de `xhtml2pdf` (non importée directement par File Transformer).
- `pypdf` 7.1.1 (`BSD-3-Clause`), `html5lib` 1.1 (`MIT`), `arabic-reshaper` 3.1.0 (`MIT`), dépendances transitives de `xhtml2pdf`.
- `lxml` 6.1.3 (`BSD-3-Clause`), dépendance transitive de `python-docx` et `svglib`.
- `pythonnet` 3.2.1 (`MIT`), `bottle` 0.13.4 (`MIT`), dépendances transitives de `pywebview` sous Windows.

Aucune dépendance sous licence GPL ou AGPL (notamment PyMuPDF) n’est utilisée ou requise.