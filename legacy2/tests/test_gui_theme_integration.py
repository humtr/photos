from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TEST_TMP_ROOT = ROOT / ".test-tmp" / "gui-theme"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from photos.gui import build_theme_stylesheet, load_theme_stylesheet, parse_design_tokens  # noqa: E402
from photos.services import PhotoOrganizerService  # noqa: E402


def new_db_path() -> Path:
    return TEST_TMP_ROOT / f"{uuid.uuid4().hex}.sqlite"


class TestGuiThemeIntegration(unittest.TestCase):
    def test_parse_design_tokens_and_alias_resolution(self) -> None:
        css = """
        :root {
            --bg: #ffffff;
            --surface: var(--bg);
            --fg: #111111;
        }
        """
        tokens = parse_design_tokens(css)
        self.assertEqual("#ffffff", tokens["bg"])
        stylesheet = build_theme_stylesheet(tokens)
        self.assertIn("background-color: #ffffff;", stylesheet)
        self.assertIn("color: #111111;", stylesheet)

    def test_load_theme_stylesheet_falls_back_when_missing(self) -> None:
        stylesheet = load_theme_stylesheet("theme-does-not-exist")
        self.assertIn("background-color: #f7f7f8;", stylesheet)
        self.assertIn("background-color: #2f6feb;", stylesheet)

    def test_load_theme_stylesheet_reads_open_design_tokens(self) -> None:
        stylesheet = load_theme_stylesheet("professional")
        self.assertIn("background-color: #f5f8ff;", stylesheet)
        self.assertIn("background-color: #2563eb;", stylesheet)

    def test_theme_persistence_in_app_state(self) -> None:
        db = new_db_path()
        service = PhotoOrganizerService(db)
        try:
            service.set_theme_preset("minimal")
            self.assertEqual("minimal", service.get_theme_preset())
            service.close()

            reopened = PhotoOrganizerService(db)
            try:
                self.assertEqual("minimal", reopened.get_theme_preset())
            finally:
                reopened.close()
        finally:
            db.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
