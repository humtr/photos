"""
Photo Organizer v1 - PySide6 Wizard GUI
5-step wizard: Source Setup → Filter Rules → Stats Dashboard → Review → Execute
"""
from __future__ import annotations

import json
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

try:
    from PySide6.QtCore import (
        QObject,
        QRunnable,
        Qt,
        QThreadPool,
        Signal,
        Slot,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QFileDialog,
        QFrame,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QSplitter,
        QStackedWidget,
        QStatusBar,
        QTextEdit,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )

    _PYSIDE6_OK = True
except Exception:  # pragma: no cover
    _PYSIDE6_OK = False

# ─── Windows 11 Fluent Light Theme ───────────────────────────────────────────
FLUENT_STYLESHEET = """
QWidget {
    background-color: #f3f3f3;
    color: #202020;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog {
    background-color: #f3f3f3;
}
QFrame#sidebar {
    background-color: #f9f9f9;
    border-right: 1px solid #e0e0e0;
}
QFrame#card {
    background-color: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
}
QPushButton {
    background-color: #0067b8;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 6px 16px;
    min-height: 28px;
}
QPushButton:hover { background-color: #005a9e; }
QPushButton:pressed { background-color: #004e8c; }
QPushButton:disabled { background-color: #c8c8c8; color: #888888; }
QPushButton#secondary {
    background-color: #ffffff;
    color: #0067b8;
    border: 1px solid #0067b8;
}
QPushButton#secondary:hover { background-color: #f0f6ff; }
QPushButton#danger { background-color: #d13438; }
QPushButton#danger:hover { background-color: #b52d31; }
QPushButton#success { background-color: #107c41; }
QPushButton#success:hover { background-color: #0d6635; }
QLineEdit, QTextEdit {
    background-color: #ffffff;
    border: 1px solid #d1d1d1;
    border-radius: 4px;
    padding: 4px 8px;
    selection-background-color: #0067b8;
}
QLineEdit:focus, QTextEdit:focus { border-color: #0067b8; }
QTreeWidget, QListWidget {
    background-color: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    alternate-background-color: #f9f9f9;
}
QTreeWidget::item:selected, QListWidget::item:selected {
    background-color: #cce4f7;
    color: #202020;
}
QTreeWidget::item:hover, QListWidget::item:hover { background-color: #e8f3fb; }
QHeaderView::section {
    background-color: #f3f3f3;
    border: none;
    border-bottom: 1px solid #e0e0e0;
    padding: 4px 8px;
    font-weight: bold;
}
QProgressBar {
    background-color: #e0e0e0;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}
QProgressBar::chunk { background-color: #0067b8; border-radius: 4px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #d1d1d1;
    border-radius: 3px;
    background-color: #ffffff;
}
QCheckBox::indicator:checked { background-color: #0067b8; border-color: #0067b8; }
QScrollBar:vertical {
    background: #f3f3f3; width: 8px; border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #c8c8c8; border-radius: 4px; min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #a0a0a0; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QLabel#step_title { font-size: 20px; font-weight: bold; color: #202020; }
QLabel#step_subtitle { font-size: 13px; color: #5f5f5f; }
QLabel#sidebar_step { font-size: 13px; padding: 10px 16px; border-radius: 6px; color: #5f5f5f; }
QLabel#sidebar_step_active {
    font-size: 13px; font-weight: bold; padding: 10px 16px;
    border-radius: 6px; color: #0067b8; background-color: #e8f3fb;
}
QLabel#stat_number { font-size: 28px; font-weight: bold; color: #0067b8; }
QLabel#stat_label { font-size: 12px; color: #5f5f5f; }
"""

STEPS = [
    ("1", "소스 설정",       "정리할 폴더와 대상 폴더를 선택합니다"),
    ("2", "필터 규칙",       "제외 폴더와 안전 설정을 조정합니다"),
    ("3", "통계 대시보드",   "폴더 구조와 파일 현황을 분석합니다"),
    ("4", "사진 검토",       "중복 사진을 검토하고 정리 계획을 수립합니다"),
    ("5", "정리 실행",       "Dry-run 검증 후 실제 파일을 이동합니다"),
]

# ─── Background worker ────────────────────────────────────────────────────────
if _PYSIDE6_OK:

    class _Signals(QObject):
        result = Signal(object)
        error = Signal(str)
        finished = Signal()

    class Worker(QRunnable):
        def __init__(self, fn, *args, **kwargs):
            super().__init__()
            self.fn = fn
            self.args = args
            self.kwargs = kwargs
            self.signals = _Signals()
            self.setAutoDelete(True)

        @Slot()
        def run(self):
            try:
                self.signals.result.emit(self.fn(*self.args, **self.kwargs))
            except Exception as exc:
                self.signals.error.emit(str(exc))
            finally:
                self.signals.finished.emit()


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _card(parent=None) -> "QFrame":
    f = QFrame(parent)
    f.setObjectName("card")
    return f


def _fmt_bytes(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


# ─── Sidebar ──────────────────────────────────────────────────────────────────
def _build_sidebar(parent, current: int) -> "QFrame":
    sidebar = QFrame(parent)
    sidebar.setObjectName("sidebar")
    sidebar.setFixedWidth(220)
    lay = QVBoxLayout(sidebar)
    lay.setContentsMargins(8, 20, 8, 20)
    lay.setSpacing(4)
    hdr = QLabel("📷  Photo Organizer")
    hdr.setStyleSheet("font-size:15px;font-weight:bold;color:#202020;padding:0 8px 16px 8px;")
    lay.addWidget(hdr)
    for i, (num, name, _) in enumerate(STEPS):
        lbl = QLabel(f"  {num}.  {name}")
        lbl.setObjectName("sidebar_step_active" if i == current else "sidebar_step")
        lay.addWidget(lbl)
    lay.addStretch()
    ver = QLabel("v1.0")
    ver.setStyleSheet("color:#a0a0a0;font-size:11px;padding:0 8px;")
    lay.addWidget(ver)
    return sidebar


# ─── Step pages ───────────────────────────────────────────────────────────────
def _page_step1(parent, state: dict) -> "QWidget":
    page = QWidget(parent)
    lay = QVBoxLayout(page)
    lay.setContentsMargins(32, 24, 32, 24)
    lay.setSpacing(16)

    t = QLabel(STEPS[0][1]); t.setObjectName("step_title"); lay.addWidget(t)
    s = QLabel(STEPS[0][2]); s.setObjectName("step_subtitle"); lay.addWidget(s)

    for key, label, default in [
        ("source_root",  "📁  원본 루트 (정리할 사진이 있는 폴더)",  r"D:\\"),
        ("archive_root", "🗂️  정리 대상 루트 (사진을 모을 폴더)",   r"D:\\PICTURES"),
        ("db_path",      "💾  데이터베이스 경로 (작업 상태 저장)",   ".photos-data/photos.sqlite"),
    ]:
        card = _card(); cl = QVBoxLayout(card); cl.setContentsMargins(16, 16, 16, 16)
        cl.addWidget(QLabel(label))
        row = QHBoxLayout()
        edit = QLineEdit(state.get(key, default))
        edit.textChanged.connect(lambda t, k=key: state.update({k: t}))
        row.addWidget(edit)
        if key != "db_path":
            btn = QPushButton("찾아보기…"); btn.setObjectName("secondary"); btn.setFixedWidth(100)
            _k = key
            def _pick(checked=False, k=_k, e=edit):
                p = QFileDialog.getExistingDirectory(page, "폴더 선택", e.text())
                if p:
                    e.setText(p); state[k] = p
            btn.clicked.connect(_pick)
            row.addWidget(btn)
        cl.addLayout(row)
        lay.addWidget(card)

    lay.addStretch()
    return page


def _page_step2(parent, state: dict) -> "QWidget":
    page = QWidget(parent)
    lay = QVBoxLayout(page)
    lay.setContentsMargins(32, 24, 32, 24)
    lay.setSpacing(16)

    t = QLabel(STEPS[1][1]); t.setObjectName("step_title"); lay.addWidget(t)
    s = QLabel(STEPS[1][2]); s.setObjectName("step_subtitle"); lay.addWidget(s)

    excl_card = _card(); el = QVBoxLayout(excl_card); el.setContentsMargins(16, 16, 16, 16)
    el.addWidget(QLabel("🚫  기본 제외 폴더"))
    for name, default in [
        (".thumbnails", True), ("$RECYCLE.BIN", True),
        ("System Volume Information", True), ("OneDriveTemp", True),
        (".tmp 계열", True), ("Google Photos", True),
        ("Samsung Gallery", True), ("OneDrive", True),
    ]:
        cb = QCheckBox(name); cb.setChecked(default); el.addWidget(cb)
    lay.addWidget(excl_card)

    safety_card = _card(); sl = QVBoxLayout(safety_card); sl.setContentsMargins(16, 16, 16, 16)
    sl.addWidget(QLabel("🔒  안전 설정"))
    ro_cb = QCheckBox("읽기 전용 모드 (실제 파일 이동 차단)")
    ro_cb.setChecked(state.get("read_only", True))
    ro_cb.toggled.connect(lambda v: state.update({"read_only": v}))
    sl.addWidget(ro_cb)
    lay.addWidget(safety_card)

    lay.addStretch()
    return page


def _page_step3(parent, state: dict) -> "QWidget":
    page = QWidget(parent)
    lay = QVBoxLayout(page)
    lay.setContentsMargins(32, 24, 32, 24)
    lay.setSpacing(16)

    t = QLabel(STEPS[2][1]); t.setObjectName("step_title"); lay.addWidget(t)
    s = QLabel(STEPS[2][2]); s.setObjectName("step_subtitle"); lay.addWidget(s)

    ctrl = QHBoxLayout()
    scan_btn = QPushButton("📂  폴더 구조 스캔 시작")
    prog = QProgressBar(); prog.setRange(0, 0); prog.setVisible(False)
    ctrl.addWidget(scan_btn); ctrl.addWidget(prog, 1)
    lay.addLayout(ctrl)

    # Stat cards
    stats_row = QHBoxLayout(); stats_row.setSpacing(12)
    stat_labels: dict[str, QLabel] = {}
    for key, caption in [("total", "총 파일"), ("photos", "사진 파일"), ("size", "총 용량"), ("dups", "중복 그룹")]:
        c = _card(); cl = QVBoxLayout(c); cl.setContentsMargins(16, 16, 16, 16)
        n = QLabel("—"); n.setObjectName("stat_number")
        lb = QLabel(caption); lb.setObjectName("stat_label")
        cl.addWidget(n, alignment=Qt.AlignCenter); cl.addWidget(lb, alignment=Qt.AlignCenter)
        stat_labels[key] = n; stats_row.addWidget(c)
    lay.addLayout(stats_row)

    tree_card = _card(); tl = QVBoxLayout(tree_card); tl.setContentsMargins(12, 12, 12, 12)
    tl.addWidget(QLabel("📁  폴더 구조"))
    folder_tree = QTreeWidget()
    folder_tree.setHeaderLabels(["폴더", "파일 수", "용량"])
    folder_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
    folder_tree.setAlternatingRowColors(True)
    folder_tree.setMinimumHeight(260)
    tl.addWidget(folder_tree)
    lay.addWidget(tree_card, 1)

    log_edit = QTextEdit(); log_edit.setReadOnly(True); log_edit.setMaximumHeight(90)
    log_edit.setPlaceholderText("스캔 로그…")
    lay.addWidget(log_edit)

    state["_step3"] = {
        "scan_btn": scan_btn, "prog": prog,
        "stat_labels": stat_labels,
        "folder_tree": folder_tree, "log_edit": log_edit,
    }
    return page


def _page_step4(parent, state: dict) -> "QWidget":
    page = QWidget(parent)
    lay = QVBoxLayout(page)
    lay.setContentsMargins(32, 24, 32, 24)
    lay.setSpacing(16)

    t = QLabel(STEPS[3][1]); t.setObjectName("step_title"); lay.addWidget(t)
    s = QLabel(STEPS[3][2]); s.setObjectName("step_subtitle"); lay.addWidget(s)

    splitter = QSplitter(Qt.Horizontal)

    left = _card(); ll = QVBoxLayout(left); ll.setContentsMargins(12, 12, 12, 12)
    ll.addWidget(QLabel("🔍  검토 큐"))
    review_list = QListWidget()
    ll.addWidget(review_list)
    load_btn = QPushButton("📋  검토 큐 불러오기"); load_btn.setObjectName("secondary")
    ll.addWidget(load_btn)
    splitter.addWidget(left)

    right = _card(); rl = QVBoxLayout(right); rl.setContentsMargins(12, 12, 12, 12)
    rl.addWidget(QLabel("📋  정리 계획 미리보기"))
    plan_tree = QTreeWidget()
    plan_tree.setHeaderLabels(["대상 경로", "원본 경로"])
    plan_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
    plan_tree.setAlternatingRowColors(True)
    rl.addWidget(plan_tree)
    pctrl = QHBoxLayout()
    build_btn = QPushButton("📐  정리 계획 생성")
    export_btn = QPushButton("💾  Review 저장"); export_btn.setObjectName("secondary")
    load_codex_btn = QPushButton("📥  Review 로드"); load_codex_btn.setObjectName("secondary")
    pctrl.addWidget(build_btn); pctrl.addWidget(export_btn); pctrl.addWidget(load_codex_btn)
    rl.addLayout(pctrl)
    splitter.addWidget(right)

    splitter.setSizes([300, 500])
    lay.addWidget(splitter, 1)

    state["_step4"] = {
        "review_list": review_list, "plan_tree": plan_tree,
        "load_btn": load_btn, "build_btn": build_btn,
        "export_btn": export_btn, "load_codex_btn": load_codex_btn,
    }
    return page


def _page_step5(parent, state: dict) -> "QWidget":
    page = QWidget(parent)
    lay = QVBoxLayout(page)
    lay.setContentsMargins(32, 24, 32, 24)
    lay.setSpacing(16)

    t = QLabel(STEPS[4][1]); t.setObjectName("step_title"); lay.addWidget(t)
    s = QLabel(STEPS[4][2]); s.setObjectName("step_subtitle"); lay.addWidget(s)

    # Dry-run card
    dc = _card(); dl = QVBoxLayout(dc); dl.setContentsMargins(16, 16, 16, 16)
    dl.addWidget(QLabel("🧪  Dry-run 검증"))
    desc = QLabel("실제 파일 이동 전 대상 루트 이탈·경로 충돌을 검사합니다.")
    desc.setWordWrap(True); desc.setStyleSheet("color:#5f5f5f;")
    dl.addWidget(desc)
    dryrun_btn = QPushButton("🧪  Dry-run 실행"); dryrun_btn.setObjectName("secondary")
    result_lbl = QLabel(""); result_lbl.setObjectName("dryrun_result_lbl")
    dl.addWidget(dryrun_btn); dl.addWidget(result_lbl)
    lay.addWidget(dc)

    # Execute card
    ec = _card(); el = QVBoxLayout(ec); el.setContentsMargins(16, 16, 16, 16)
    el.addWidget(QLabel("🚀  실제 실행"))
    warn = QLabel("⚠️  읽기 전용 모드입니다. 실행하려면 아래 체크박스를 해제하세요.")
    warn.setStyleSheet("color:#d13438;font-weight:bold;")
    el.addWidget(warn)
    unlock_cb = QCheckBox("읽기 전용 해제 (파일이 실제로 이동됩니다)")
    unlock_cb.setStyleSheet("color:#d13438;")
    el.addWidget(unlock_cb)
    exec_prog = QProgressBar(); exec_prog.setRange(0, 100); exec_prog.setValue(0); exec_prog.setVisible(False)
    el.addWidget(exec_prog)
    exec_btn = QPushButton("🚀  파일 이동 실행"); exec_btn.setObjectName("danger"); exec_btn.setEnabled(False)
    el.addWidget(exec_btn)
    lay.addWidget(ec)

    # Log
    lc = _card(); ll2 = QVBoxLayout(lc); ll2.setContentsMargins(12, 12, 12, 12)
    ll2.addWidget(QLabel("📄  실행 로그"))
    exec_log = QTextEdit(); exec_log.setReadOnly(True); exec_log.setMinimumHeight(140)
    exec_log.setPlaceholderText("실행 결과가 여기에 표시됩니다…")
    ll2.addWidget(exec_log)
    lay.addWidget(lc, 1)

    state["_step5"] = {
        "dryrun_btn": dryrun_btn, "result_lbl": result_lbl,
        "warn": warn, "unlock_cb": unlock_cb,
        "exec_btn": exec_btn, "exec_prog": exec_prog, "exec_log": exec_log,
    }

    unlock_cb.toggled.connect(lambda v: (
        state.update({"read_only": not v}),
        exec_btn.setEnabled(v),
    ))
    return page


# ─── Main Window ─────────────────────────────────────────────────────────────
class PhotoOrganizerWindow(QMainWindow):
    def __init__(self, db_path: Path | None = None):
        super().__init__()
        self.setWindowTitle("Photo Organizer v1")
        self.resize(1100, 720)
        self.setMinimumSize(900, 600)
        self._db_path = db_path or Path(".photos-data/photos.sqlite")
        self._pool = QThreadPool.globalInstance()
        self._step = 0
        self._state: dict[str, Any] = {
            "source_root": r"D:\\",
            "archive_root": r"D:\\PICTURES",
            "db_path": str(self._db_path),
            "read_only": True,
        }
        self._build_ui()
        self._go(0)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._sb_container = QWidget(); self._sb_container.setFixedWidth(220)
        self._sb_lay = QVBoxLayout(self._sb_container)
        self._sb_lay.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._sb_container)

        content = QFrame()
        content.setStyleSheet("background-color:#f3f3f3;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        self._stack = QStackedWidget()
        builders = [_page_step1, _page_step2, _page_step3, _page_step4, _page_step5]
        self._pages = [b(self._stack, self._state) for b in builders]
        for p in self._pages:
            self._stack.addWidget(p)
        cl.addWidget(self._stack, 1)

        nav = QFrame()
        nav.setStyleSheet("background-color:#f9f9f9;border-top:1px solid #e0e0e0;")
        nav.setFixedHeight(60)
        nl = QHBoxLayout(nav); nl.setContentsMargins(24, 8, 24, 8)
        self._back_btn = QPushButton("← 이전"); self._back_btn.setObjectName("secondary")
        self._back_btn.setFixedWidth(100); self._back_btn.clicked.connect(self._on_back)
        self._step_lbl = QLabel(""); self._step_lbl.setStyleSheet("color:#5f5f5f;")
        self._next_btn = QPushButton("다음 →"); self._next_btn.setFixedWidth(100)
        self._next_btn.clicked.connect(self._on_next)
        nl.addWidget(self._back_btn)
        nl.addWidget(self._step_lbl, 1, Qt.AlignCenter)
        nl.addWidget(self._next_btn)
        cl.addWidget(nav)
        root.addWidget(content, 1)

        self._sbar = QStatusBar(); self.setStatusBar(self._sbar)

        self._wire_step3()
        self._wire_step4()
        self._wire_step5()

    def _rebuild_sidebar(self):
        for i in reversed(range(self._sb_lay.count())):
            w = self._sb_lay.itemAt(i).widget()
            if w:
                w.setParent(None)
        self._sb_lay.addWidget(_build_sidebar(self._sb_container, self._step))

    def _go(self, step: int):
        self._step = max(0, min(step, len(STEPS) - 1))
        self._stack.setCurrentIndex(self._step)
        self._rebuild_sidebar()
        self._back_btn.setEnabled(self._step > 0)
        self._next_btn.setText("완료" if self._step == len(STEPS) - 1 else "다음 →")
        self._step_lbl.setText(f"단계 {self._step + 1} / {len(STEPS)}")

    def _on_next(self):
        if self._step < len(STEPS) - 1:
            self._go(self._step + 1)
        else:
            QMessageBox.information(self, "완료", "모든 단계가 완료되었습니다.")

    def _on_back(self):
        self._go(self._step - 1)

    # ── Step 3 ────────────────────────────────────────────────────────────────
    def _wire_step3(self):
        self._state["_step3"]["scan_btn"].clicked.connect(self._run_scan)

    def _run_scan(self):
        from .database import connect
        from .scanner import scan_media

        w = self._state["_step3"]
        w["scan_btn"].setEnabled(False)
        w["prog"].setVisible(True)
        w["log_edit"].clear()
        self._sbar.showMessage("스캔 중…")

        source = self._state.get("source_root", "")
        db_path = Path(self._state.get("db_path", ".photos-data/photos.sqlite"))

        def _task():
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(connect(db_path)) as con:
                count = scan_media(con, source)
                row = con.execute(
                    "SELECT COUNT(*) as c, COALESCE(SUM(size_bytes),0) as b FROM media_files WHERE exists_on_disk=1"
                ).fetchone()
                photo = con.execute(
                    "SELECT COUNT(*) as c FROM media_files WHERE exists_on_disk=1 AND media_type IN ('jpeg','raw','image','screenshot')"
                ).fetchone()
                dup_rows = con.execute(
                    "SELECT sha256 FROM media_files WHERE sha256 IS NOT NULL AND exists_on_disk=1 GROUP BY sha256 HAVING COUNT(*)>1"
                ).fetchall()
                folders = con.execute(
                    "SELECT parent_key, COUNT(*) as c, COALESCE(SUM(size_bytes),0) as b FROM media_files WHERE exists_on_disk=1 GROUP BY parent_key ORDER BY c DESC LIMIT 200"
                ).fetchall()
            return {
                "ok": True, "count": count,
                "total": row["c"], "bytes": row["b"],
                "photos": photo["c"], "dups": len(dup_rows),
                "folders": [(r["parent_key"], r["c"], r["b"]) for r in folders],
            }

        worker = Worker(_task)
        worker.signals.result.connect(self._on_scan_done)
        worker.signals.error.connect(self._on_scan_err)
        self._pool.start(worker)

    @Slot(object)
    def _on_scan_done(self, r: dict):
        w = self._state["_step3"]
        w["scan_btn"].setEnabled(True); w["prog"].setVisible(False)
        if not r.get("ok"):
            w["log_edit"].append(f"❌ 오류: {r.get('error')}")
            return
        sl = w["stat_labels"]
        sl["total"].setText(f"{r['total']:,}")
        sl["photos"].setText(f"{r['photos']:,}")
        sl["size"].setText(_fmt_bytes(r["bytes"]))
        sl["dups"].setText(str(r["dups"]))
        tree: QTreeWidget = w["folder_tree"]
        tree.clear()
        for folder, cnt, size in r["folders"]:
            tree.addTopLevelItem(QTreeWidgetItem([folder or ".", str(cnt), _fmt_bytes(size)]))
        w["log_edit"].append(f"✅ 스캔 완료: {r['count']:,}개 파일")
        self._sbar.showMessage(f"스캔 완료 — {r['total']:,}개 파일")
        self._state["_scan_done"] = True

    @Slot(str)
    def _on_scan_err(self, err: str):
        w = self._state["_step3"]
        w["scan_btn"].setEnabled(True); w["prog"].setVisible(False)
        w["log_edit"].append(f"❌ {err}"); self._sbar.showMessage("스캔 오류")

    # ── Step 4 ────────────────────────────────────────────────────────────────
    def _wire_step4(self):
        w = self._state["_step4"]
        w["load_btn"].clicked.connect(self._load_review)
        w["build_btn"].clicked.connect(self._build_plan)
        w["export_btn"].clicked.connect(self._export_review)
        w["load_codex_btn"].clicked.connect(self._load_codex)

    def _load_review(self):
        from .database import connect
        from .review import review_queue_counts

        db_path = Path(self._state.get("db_path", ".photos-data/photos.sqlite"))
        if not db_path.exists():
            QMessageBox.warning(self, "DB 없음", "먼저 Step 3에서 스캔을 실행하세요."); return
        try:
            with closing(connect(db_path)) as con:
                counts = review_queue_counts(con)
            rl: QListWidget = self._state["_step4"]["review_list"]
            rl.clear()
            for q, n in counts.items():
                rl.addItem(QListWidgetItem(f"  {q.replace('_',' ').title()}  —  {n:,}개"))
            self._sbar.showMessage("검토 큐 로드 완료")
        except Exception as exc:
            QMessageBox.critical(self, "오류", str(exc))

    def _build_plan(self):
        from .database import connect
        from .planning import build_archive_plans

        db_path = Path(self._state.get("db_path", ".photos-data/photos.sqlite"))
        archive_root = self._state.get("archive_root", r"D:\\PICTURES")
        if not db_path.exists():
            QMessageBox.warning(self, "DB 없음", "먼저 Step 3에서 스캔을 실행하세요."); return
        self._sbar.showMessage("정리 계획 생성 중…")

        def _task():
            with closing(connect(db_path)) as con:
                return build_archive_plans(con, archive_root=archive_root)

        worker = Worker(_task)
        worker.signals.result.connect(self._on_plan_done)
        worker.signals.error.connect(lambda e: (
            self._sbar.showMessage(f"오류: {e}"),
            QMessageBox.critical(self, "오류", e),
        ))
        self._pool.start(worker)

    @Slot(object)
    def _on_plan_done(self, plans: list):
        self._state["_plans"] = plans
        tree: QTreeWidget = self._state["_step4"]["plan_tree"]
        tree.clear()
        for p in plans[:2000]:
            tree.addTopLevelItem(QTreeWidgetItem([p["planned_path"], p["source_path"]]))
        self._sbar.showMessage(f"정리 계획 {len(plans):,}건 생성 완료")

    def _export_review(self):
        from .database import connect
        from .review import export_review_package

        db_path = Path(self._state.get("db_path", ".photos-data/photos.sqlite"))
        out = Path(self._state.get("archive_root", r"D:\\PICTURES")) / "_review"
        if not db_path.exists():
            QMessageBox.warning(self, "DB 없음", "먼저 Step 3에서 스캔을 실행하세요."); return
        try:
            with closing(connect(db_path)) as con:
                summary = export_review_package(con, out)
            QMessageBox.information(
                self, "Review 저장 완료",
                f"저장 위치: {out}\n\n" + "\n".join(f"  {k}: {v}" for k, v in summary["queue_counts"].items()),
            )
            self._sbar.showMessage(f"Review 저장 완료: {out}")
        except Exception as exc:
            QMessageBox.critical(self, "오류", str(exc))

    def _load_codex(self):
        path, _ = QFileDialog.getOpenFileName(self, "codex_review.json 선택", "", "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            decisions = data.get("folder_decisions", [])
            self._state["_codex_review"] = data
            QMessageBox.information(self, "Review 로드 완료", f"폴더 결정 {len(decisions)}건 로드됨")
            self._sbar.showMessage(f"codex_review.json 로드 완료: {len(decisions)}건")
        except Exception as exc:
            QMessageBox.critical(self, "오류", str(exc))

    # ── Step 5 ────────────────────────────────────────────────────────────────
    def _wire_step5(self):
        w = self._state["_step5"]
        w["dryrun_btn"].clicked.connect(self._run_dryrun)
        w["exec_btn"].clicked.connect(self._run_execute)

    def _run_dryrun(self):
        plans = self._state.get("_plans")
        if not plans:
            QMessageBox.warning(self, "계획 없음", "먼저 Step 4에서 정리 계획을 생성하세요."); return
        from .win_fs import validate_move_plan
        archive_root = Path(self._state.get("archive_root", r"D:\\"))
        w = self._state["_step5"]
        errors = validate_move_plan(plans, archive_root)
        rl: QLabel = w["result_lbl"]
        if errors:
            rl.setText(f"❌  Dry-run 실패: {len(errors)}건 오류")
            rl.setStyleSheet("color:#d13438;font-weight:bold;")
            w["exec_log"].append("Dry-run 실패:\n" + "\n".join(errors[:20]))
        else:
            rl.setText(f"✅  Dry-run 통과: 오류 0건 ({len(plans):,}개 계획)")
            rl.setStyleSheet("color:#107c41;font-weight:bold;")
            w["exec_log"].append(f"Dry-run 통과: {len(plans):,}개 계획 검증 완료")
            self._state["_dryrun_passed"] = True
        self._sbar.showMessage("Dry-run 완료")

    def _run_execute(self):
        if self._state.get("read_only", True):
            QMessageBox.warning(self, "읽기 전용", "읽기 전용 모드에서는 파일을 이동할 수 없습니다."); return
        if not self._state.get("_dryrun_passed"):
            QMessageBox.warning(self, "Dry-run 필요", "먼저 Dry-run을 통과해야 합니다."); return
        plans = self._state.get("_plans", [])
        if not plans:
            QMessageBox.warning(self, "계획 없음", "정리 계획이 없습니다."); return
        if QMessageBox.question(self, "확인", f"{len(plans):,}개 파일을 이동합니까?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        if QMessageBox.question(self, "최종 확인", "이 작업은 되돌리기 어렵습니다. 계속하시겠습니까?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        w = self._state["_step5"]
        w["exec_btn"].setEnabled(False); w["exec_prog"].setVisible(True)
        self._sbar.showMessage("파일 이동 중…")
        archive_root = Path(self._state.get("archive_root", r"D:\\PICTURES"))

        def _task():
            import csv
            from datetime import datetime
            from .win_fs import safe_move
            review_dir = archive_root / "_review"
            review_dir.mkdir(parents=True, exist_ok=True)
            log_rows, undo_rows, moved = [], [], 0
            for p in plans:
                src, dst = Path(p["source_path"]), Path(p["planned_path"])
                try:
                    safe_move(src, dst)
                    moved += 1
                    log_rows.append((str(src), str(dst), "moved", datetime.now().isoformat()))
                    undo_rows.append((str(dst), str(src)))
                except (OSError, PermissionError) as exc:
                    log_rows.append((str(src), str(dst), f"failed:{exc}", datetime.now().isoformat()))
            log_path = review_dir / "execution_log.csv"
            undo_path = review_dir / "undo_plan.csv"
            for path, header, rows in [
                (log_path, ["source", "destination", "result", "timestamp"], log_rows),
                (undo_path, ["moved_path", "restore_to"], undo_rows),
            ]:
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    wt = csv.writer(f); wt.writerow(header); wt.writerows(rows)
            return {"moved": moved, "total": len(plans), "log_path": str(log_path)}

        worker = Worker(_task)
        worker.signals.result.connect(self._on_exec_done)
        worker.signals.error.connect(lambda e: (
            w["exec_btn"].setEnabled(True), w["exec_prog"].setVisible(False),
            QMessageBox.critical(self, "실행 오류", e),
        ))
        self._pool.start(worker)

    @Slot(object)
    def _on_exec_done(self, r: dict):
        w = self._state["_step5"]
        w["exec_btn"].setEnabled(True); w["exec_prog"].setVisible(False); w["exec_prog"].setValue(100)
        msg = f"✅  {r['moved']:,}/{r['total']:,}개 이동 완료\n로그: {r['log_path']}"
        w["exec_log"].append(msg)
        self._sbar.showMessage(f"실행 완료: {r['moved']:,}개 이동")
        QMessageBox.information(self, "실행 완료", msg)


# ─── Public entry point ───────────────────────────────────────────────────────
def launch(db_path: str | Path | None = None) -> int:
    """PySide6 마법사 GUI를 실행합니다."""
    if not _PYSIDE6_OK:
        raise RuntimeError(
            "PySide6가 설치되어 있지 않습니다. "
            "Windows 설정 스크립트를 실행하거나 'pip install PySide6'를 실행하세요."
        )
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(FLUENT_STYLESHEET)
    window = PhotoOrganizerWindow(db_path=Path(db_path) if db_path else None)
    window.show()
    return app.exec()
