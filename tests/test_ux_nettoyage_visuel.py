"""Correctif UX 5 (XS) : nettoyage visuel et accessibilité de l'écran principal.

Contrôles « code pur » sur index.html, styles.css et app.js : aucune
décoration superflue, texte d'au moins 12 px, contrastes d'au moins 4,5:1,
curseur DPI qui atteint vraiment 300, raccourcis cohérents avec le README.
"""

import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from securite_outils import REPO_ROOT  # noqa: E402

FRONTEND = REPO_ROOT / "src" / "frontend"
HTML = (FRONTEND / "index.html").read_text(encoding="utf-8")
CSS = (FRONTEND / "styles.css").read_text(encoding="utf-8")
JS = (FRONTEND / "app.js").read_text(encoding="utf-8")
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

# Emoji et pictogrammes (dont les flèches « ➔ » U+2794).
EMOJI = re.compile("[☀-➿⬀-⯿\U0001f300-\U0001faff]")
DARK = "#202320"
DARK_CONTEXT = {".subtitle": 4.5, ".logo-icon": 3.0}           # en-tête sombre
ICONS = {".dropzone-icon", ".empty-state", ".btn-icon"}         # 3:1 suffit (WCAG 1.4.11)


def _variables():
    return dict(re.findall(r"--([\w-]+):(#[0-9a-fA-F]{3,6})", CSS))


def _color(value, variables):
    value = value.strip().split()[0] if value.strip() else ""
    match = re.fullmatch(r"var\(--([\w-]+)\)", value)
    if match:
        return variables.get(match.group(1))
    return value if re.fullmatch(r"#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}", value) else None


def _luminance(hex_color):
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a, b):
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _rules():
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS):
        selector = selector.strip()
        if selector.startswith("@"):
            continue
        declarations = {}
        for item in body.split(";"):
            if ":" in item:
                key, value = item.split(":", 1)
                declarations[key.strip()] = value.strip()
        yield selector, declarations


class _Headings(HTMLParser):
    def __init__(self):
        super().__init__()
        self.levels = []

    def handle_starttag(self, tag, attrs):
        if re.fullmatch(r"h[1-6]", tag):
            self.levels.append(int(tag[1]))


class TestNettoyageVisuel(unittest.TestCase):

    def test_decorations_superflues_retirees(self):
        for text in ("badge-tag", "APPLICATION DESKTOP", "eyebrow", "VOTRE ATELIER", "Les mêmes idées",
                     "Un autre format.", "step-number", ">02<"):
            with self.subTest(text):
                self.assertFalse(text in HTML, msg=f"Encore présent : {text}")
        for name, source in (("index.html", HTML), ("app.js", JS), ("styles.css", CSS)):
            with self.subTest(name):
                self.assertEqual(EMOJI.findall(source), [], msg=f"Emoji dans {name}")

    def test_code_mort_jfif_jpg_retire_et_raccourcis_coherents(self):
        self.assertNotIn("jfif-jpg", JS + HTML)
        html_presets = set(re.findall(r'data-preset="([\w-]+)"', HTML))
        js_presets = set(re.findall(r"'([\w-]+)': \{ target:", JS))
        self.assertEqual(html_presets, js_presets)
        self.assertIn("png-webp", html_presets)

    def test_parcours_du_readme_toujours_possible(self):
        labels = re.findall(r"raccourci \*\*(.+?)\*\*", README)
        self.assertTrue(labels, msg="Le README ne cite plus de raccourci")
        chips = re.findall(r'<button class="chip" data-preset="[\w-]+">([^<]+)</button>', HTML)
        for label in labels:
            self.assertIn(label, chips)
        self.assertIn("Lancer la conversion", HTML)
        self.assertIn("Ajouter des fichiers", HTML)

    def test_hierarchie_des_titres_sans_saut(self):
        parser = _Headings()
        parser.feed(HTML)
        self.assertEqual(parser.levels[0], 1)
        for previous, current in zip(parser.levels, parser.levels[1:]):
            self.assertLessEqual(current, previous + 1, msg=f"Saut de titre : {parser.levels}")

    def test_texte_d_au_moins_12_px(self):
        sizes = re.findall(r"font-size:\s*(\d+(?:\.\d+)?)px", CSS + HTML + JS)
        sizes += re.findall(r"font:\s*(?:[\w-]+\s+)*?(\d+(?:\.\d+)?)px", CSS)
        self.assertTrue(sizes)
        small = sorted({float(s) for s in sizes if float(s) < 12})
        self.assertEqual(small, [], msg="Tailles de texte sous 12 px")

    def test_contrastes_d_au_moins_4_5(self):
        variables = _variables()
        backgrounds = (variables["paper"], variables["surface"])
        failures = []
        for selector, declarations in _rules():
            fg = _color(declarations.get("color", ""), variables)
            if not fg or selector == "body":
                continue
            bg = _color(declarations.get("background", declarations.get("background-color", "")), variables)
            if bg:
                checks = [(bg, 4.5)]
            elif selector in DARK_CONTEXT:
                checks = [(DARK, DARK_CONTEXT[selector])]
            elif selector in ICONS:
                checks = [(b, 3.0) for b in backgrounds]
            else:
                checks = [(b, 4.5) for b in backgrounds]
                if selector.startswith(".dropzone"):
                    checks.append(("#ecefe3", 4.5))
            for background, minimum in checks:
                ratio = _ratio(fg, background)
                if ratio < minimum:
                    failures.append(f"{selector} {fg} sur {background} : {ratio:.2f}")
        self.assertEqual(failures, [])

    def test_curseur_dpi_atteint_300(self):
        match = re.search(r'<input[^>]*id="opt-dpi"[^>]*>', HTML)
        self.assertIsNotNone(match)
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', match.group(0)))
        low, high, step, value = (int(attrs[k]) for k in ("min", "max", "step", "value"))
        self.assertEqual(high, 300)
        self.assertGreaterEqual(low, 72)
        self.assertEqual((high - low) % step, 0, msg="300 inatteignable avec ce pas")
        self.assertEqual((value - low) % step, 0, msg="Valeur par défaut hors du pas")
        self.assertIn(f">{value} DPI<", HTML)


if __name__ == "__main__":
    unittest.main()
