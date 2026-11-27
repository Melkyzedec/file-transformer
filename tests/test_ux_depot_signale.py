"""Correctif UX 3 (Majeur) : aucun dépôt ignoré en silence.

Un dossier, un raccourci, un nom réservé ou un élément sans chemin déposé dans
la fenêtre est signalé au frontend avec une raison, sans chemin complet.

Données exclusivement fictives (CANARY_TEST_).
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from securite_outils import REPO_ROOT, _TempCase  # noqa: E402

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestUxDepotSignale(_TempCase):

    def setUp(self):
        super().setUp()
        self.png = self.root / "CANARY_TEST_ok.png"
        with Image.new("RGB", (4, 4), (10, 200, 10)) as img:
            img.save(self.png, format="PNG")
        self.folder = self.root / "CANARY_TEST_dossier"
        self.folder.mkdir()
        self.shortcut = self.root / "CANARY_TEST_raccourci.lnk"
        self.shortcut.write_bytes(b"L\x00\x00\x00CANARY_TEST_")

    def assertNoDirectory(self, payload):
        text = json.dumps(payload["ignored"], ensure_ascii=False)
        for directory in (str(self.root), str(self.root).replace("\\", "\\\\")):
            self.assertNotIn(directory, text)

    def test_chaque_element_ignore_est_signale_avec_sa_raison(self):
        payload = self.api._analyze_paths([
            str(self.png), str(self.folder), str(self.shortcut),
            "C:\\CANARY_TEST\\NUL.txt", str(self.root / "CANARY_TEST_absent.png"), "", None,
        ])
        self.assertEqual([f["name"] for f in payload["files"]], ["CANARY_TEST_ok.png"])
        self.assertEqual(payload["ignored"], [
            {"name": "CANARY_TEST_dossier", "reason": "folder"},
            {"name": "CANARY_TEST_raccourci.lnk", "reason": "shortcut"},
            {"name": "NUL.txt", "reason": "reserved"},
            {"name": "CANARY_TEST_absent.png", "reason": "missing"},
            {"name": "", "reason": "invalid"},
            {"name": "", "reason": "invalid"},
        ])
        self.assertNoDirectory(payload)

    def test_nom_reserve_signale_sans_acces_disque(self):
        def forbidden(*_args, **_kwargs):
            raise AssertionError("Accès disque interdit pour un nom réservé Windows")
        with mock.patch("os.path.isfile", forbidden), mock.patch("os.path.isdir", forbidden), \
                mock.patch("os.path.islink", forbidden), mock.patch("os.path.exists", forbidden):
            payload = self.api._analyze_paths(["\\\\.\\PhysicalDrive0", "D:/CANARY_TEST/COM1"])
        self.assertEqual([i["reason"] for i in payload["ignored"]], ["reserved", "reserved"])

    def test_lien_symbolique_signale_comme_raccourci(self):
        link = self.root / "CANARY_TEST_lien.png"
        try:
            os.symlink(self.png, link)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Liens symboliques indisponibles ici : {exc}")
        payload = self.api._analyze_paths([str(link)])
        self.assertEqual(payload, {"files": [], "ignored": [{"name": "CANARY_TEST_lien.png", "reason": "shortcut"}]})

    def test_files_from_paths_reste_une_simple_liste(self):
        files = self.api.files_from_paths([str(self.png), str(self.folder)])
        self.assertIsInstance(files, list)
        self.assertEqual([f["name"] for f in files], ["CANARY_TEST_ok.png"])

    def test_selecteur_de_fichiers_signale_aussi_les_elements_ignores(self):
        window = mock.Mock()
        window.create_file_dialog.return_value = [str(self.png), str(self.shortcut)]
        self.api.set_window(window)
        payload = self.api.select_files()
        self.assertEqual([f["name"] for f in payload["files"]], ["CANARY_TEST_ok.png"])
        self.assertEqual(payload["ignored"], [{"name": "CANARY_TEST_raccourci.lnk", "reason": "shortcut"}])

    def test_depot_natif_un_element_sans_chemin_est_signale(self):
        import main  # noqa: E402  (n'ouvre aucune fenêtre à l'import)
        event = {"dataTransfer": {"files": [
            {"name": "CANARY_TEST_inconnu"},
            {"name": "CANARY_TEST_dossier", "pywebviewFullPath": str(self.folder)},
            {"name": "CANARY_TEST_ok.png", "pywebviewFullPath": str(self.png)},
        ]}}
        script = main.build_drop_script(self.api, event)
        self.assertTrue(script.startswith("window.onNativeFilesDropped && window.onNativeFilesDropped("))
        payload = json.loads(script[script.index("(", script.index("&&")) + 1:-1])
        self.assertEqual([f["name"] for f in payload["files"]], ["CANARY_TEST_ok.png"])
        self.assertEqual(payload["ignored"], [
            {"name": "CANARY_TEST_dossier", "reason": "folder"},
            {"name": "CANARY_TEST_inconnu", "reason": "invalid"},
        ])
        self.assertIsNone(main.build_drop_script(self.api, {"dataTransfer": {"files": []}}))


    def test_aucune_nouvelle_methode_exposee_au_javascript(self):
        # pywebview expose au JavaScript toute méthode publique d'AppAPI.
        public = {name for name in dir(type(self.api)) if not name.startswith("_")}
        self.assertEqual(public, {
            "set_window", "select_files", "files_from_paths", "detect_format",
            "select_output_folder", "convert_single_file", "open_folder", "get_supported_formats",
        })


if __name__ == "__main__":
    unittest.main()
