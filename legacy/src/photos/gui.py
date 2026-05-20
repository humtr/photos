from __future__ import annotations


def launch() -> int:
    try:
        from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget
    except Exception as exc:  # pragma: no cover - depends on optional Windows GUI extra.
        raise RuntimeError(
            "PySide6 is not installed. Run the Windows setup script or install the gui extra."
        ) from exc

    app = QApplication([])
    window = QMainWindow()
    window.setWindowTitle("photos v1 scaffold")
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.addWidget(QLabel("photos v1 scaffold"))
    layout.addWidget(QLabel("Use the dry-run pipeline before any real-drive work."))
    window.setCentralWidget(panel)
    window.resize(720, 360)
    window.show()
    return app.exec()
