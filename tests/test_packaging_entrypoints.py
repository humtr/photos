from __future__ import annotations

import ast
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from photos import __version__, cli, gui


ROOT = Path(__file__).resolve().parents[1]


def assigned_call(tree: ast.Module, name: str) -> ast.Call:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            if isinstance(node.value, ast.Call):
                return node.value
    raise AssertionError(f"missing call assignment: {name}")


class PackagingEntrypointTests(unittest.TestCase):
    def test_gui_launcher_lazily_routes_to_root_main(self) -> None:
        root_main = mock.Mock(return_value=0)
        with mock.patch.object(
            gui.importlib,
            "import_module",
            return_value=SimpleNamespace(main=root_main),
        ) as import_module:
            self.assertEqual(gui.launch(), 0)

        import_module.assert_called_once_with("photo_organizer_app")
        root_main.assert_called_once_with()

    def test_photos_gui_command_routes_through_gui_adapter(self) -> None:
        with mock.patch.object(gui, "launch", return_value=0) as launch:
            self.assertEqual(cli.main(["gui"]), 0)
        launch.assert_called_once_with()

    def test_gui_adapter_does_not_import_backend_internals(self) -> None:
        tree = ast.parse((ROOT / "src" / "photos" / "gui.py").read_text(encoding="utf-8"))
        modules = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        modules.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        self.assertTrue(
            modules.isdisjoint(
                {
                    "photos.database",
                    "photos.scanner",
                    "photos.execution",
                    "photos.services",
                    "database",
                    "scanner",
                    "execution",
                    "services",
                }
            )
        )

    def test_gui_launcher_classifies_missing_root_and_tkinter(self) -> None:
        for missing, message in (
            ("photo_organizer_app", "GUI module is not installed"),
            ("tkinter", "Tkinter is unavailable"),
            ("_tkinter", "Tkinter is unavailable"),
        ):
            error = ModuleNotFoundError(f"No module named {missing!r}")
            error.name = missing
            with self.subTest(missing=missing), mock.patch.object(
                gui.importlib,
                "import_module",
                side_effect=error,
            ):
                with self.assertRaisesRegex(RuntimeError, message):
                    gui.launch()

    def test_root_module_exposes_main_and_preserves_direct_execution(self) -> None:
        tree = ast.parse((ROOT / "photo_organizer_app.py").read_text(encoding="utf-8"))
        main = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        calls = [ast.unparse(node.func) for node in ast.walk(main) if isinstance(node, ast.Call)]
        self.assertIn("PhotoOrganizerApp", calls)
        self.assertIn("app.mainloop", calls)

        guard = next(
            node
            for node in tree.body
            if isinstance(node, ast.If) and ast.unparse(node.test) == "__name__ == '__main__'"
        )
        self.assertEqual(ast.unparse(guard.body[0]), "raise SystemExit(main())")

    def test_project_metadata_packages_root_gui_and_installed_routes(self) -> None:
        with (ROOT / "pyproject.toml").open("rb") as handle:
            config = tomllib.load(handle)

        project = config["project"]
        self.assertEqual(project["version"], "0.2.0")
        self.assertEqual(__version__, project["version"])
        self.assertEqual(project["scripts"]["photos"], "photos.cli:main")
        self.assertEqual(project["scripts"]["photo-organizer"], "photos.gui:launch")
        self.assertEqual(config["tool"]["setuptools"]["py-modules"], ["photo_organizer_app"])
        self.assertEqual(
            config["tool"]["setuptools"]["package-dir"],
            {"": ".", "photos": "src/photos"},
        )
        gui_dependencies = project["optional-dependencies"]["gui"]
        self.assertTrue(any(item.startswith("Pillow") for item in gui_dependencies))
        self.assertFalse(any("PySide6" in item for item in gui_dependencies))

    def test_pyinstaller_specs_include_vendor_and_backend_paths(self) -> None:
        for filename in ("PhotoOrganizer.spec", "PhotoOrganizerFast.spec"):
            with self.subTest(filename=filename):
                tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
                analysis = assigned_call(tree, "a")
                keywords = {item.arg: ast.literal_eval(item.value) for item in analysis.keywords}
                self.assertEqual(analysis.args[0].elts[0].value, "photo_organizer_app.py")
                self.assertIn(".\\vendor", keywords["pathex"])
                self.assertIn(".\\src", keywords["pathex"])
                self.assertIn("photos.services", keywords["hiddenimports"])


if __name__ == "__main__":
    unittest.main()
