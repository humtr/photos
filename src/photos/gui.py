"""
Photo Organizer v1 — PySide6 Wizard GUI
"""
from __future__ import annotations

import json
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

try:
    from PySide6.QtCore import (
        QObject, QRunnable, Qt, QThreadPool, Signal, Slot,
    )
    from PySide6.QtGui import QColor, QFont, QIcon, QPalette
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QFileDialog, QFrame,
        QHBoxLayout, QHeaderView, QLabel, QLineEdit,
        QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
        QProgressBar, QPushButton, QSizePolicy, QSplitter,
        QStackedWidget, QStatusBar, QTextEdit,
        QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    )
    _PYSIDE6_OK = True
except Exception:
    _PYSIDE6_OK = False

# ─── 데이터 경로: 항상 사용자 홈 디렉토리 아래에 생성 ──────────────────────────
def _default_db_path() -> Path:
    """EXE 실행 위치에 관계없이 쓰기 가능한 경로를 반환합니다."""
    base = Path.home() / ".photo-organizer"
    base.mkdir(parents=True, exist_ok=True)
    return base / "photos.sqlite"

def _default_review_dir(archive_root: str) -> Path:
    arc = Path(archive_root)
    try:
        test = arc / "_review" / ".write_test"
        test.parent.mkdir(parents=True, exist_ok=True)
        test.touch(); test.unlink()
        return arc / "_review"
    except OSError:
        fallback = Path.home() / ".photo-organizer" / "review"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

# ─── Windows 11 Fluent Light Theme ──────────────────────────────────────────
STYLE = """
/* ── 전체 기본 ── */
* { font-family: "Segoe UI", "Malgun Gothic", Arial, sans-serif; font-size: 13px; }
QMainWindow, QWidget { background: #f0f0f0; color: #1a1a1a; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }

/* ── 사이드바 ── */
QFrame#sidebar {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #1e3a5f, stop:1 #162d4a);
    border: none;
}
QLabel#app_title {
    color: #ffffff; font-size: 16px; font-weight: 700;
    padding: 20px 16px 8px 16px;
}
QLabel#app_version { color: #7fafd4; font-size: 11px; padding: 0 16px 20px 16px; }
QFrame#sidebar_divider { background: rgba(255,255,255,0.12); max-height: 1px; margin: 4px 16px; }

/* ── 사이드바 스텝 버튼 ── */
QPushButton#step_btn {
    background: transparent; color: #b0cce8;
    border: none; border-radius: 8px;
    text-align: left; padding: 10px 16px;
    font-size: 13px;
}
QPushButton#step_btn:hover { background: rgba(255,255,255,0.08); color: #ddeeff; }
QPushButton#step_btn_active {
    background: rgba(255,255,255,0.15); color: #ffffff;
    border: none; border-radius: 8px;
    border-left: 3px solid #4da6ff;
    text-align: left; padding: 10px 13px;
    font-size: 13px; font-weight: 600;
}

/* ── 카드 ── */
QFrame#card {
    background: #ffffff;
    border: 1px solid #e0e4e8;
    border-radius: 10px;
}
QFrame#card_accent {
    background: #ffffff;
    border: 1px solid #0078d4;
    border-radius: 10px;
}

/* ── 버튼 ── */
QPushButton {
    background: #0078d4; color: #ffffff;
    border: none; border-radius: 6px;
    padding: 7px 18px; font-size: 13px; font-weight: 500;
    min-height: 32px;
}
QPushButton:hover { background: #106ebe; }
QPushButton:pressed { background: #005a9e; }
QPushButton:disabled { background: #d0d4d8; color: #909498; }
QPushButton#btn_secondary {
    background: #ffffff; color: #0078d4;
    border: 1px solid #0078d4;
}
QPushButton#btn_secondary:hover { background: #e8f4fd; }
QPushButton#btn_danger { background: #c42b1c; }
QPushButton#btn_danger:hover { background: #a52315; }
QPushButton#btn_success { background: #107c10; }
QPushButton#btn_success:hover { background: #0b6a0b; }
QPushButton#btn_icon {
    background: transparent; color: #0078d4;
    border: none; padding: 4px 8px;
    font-size: 13px;
}
QPushButton#btn_icon:hover { background: #e8f4fd; border-radius: 4px; }

/* ── 입력 ── */
QLineEdit {
    background: #ffffff; border: 1px solid #c8cdd2;
    border-radius: 6px; padding: 6px 10px;
    selection-background-color: #0078d4;
}
QLineEdit:focus { border: 1.5px solid #0078d4; }
QTextEdit {
    background: #fafbfc; border: 1px solid #e0e4e8;
    border-radius: 6px; padding: 6px;
    font-family: "Consolas", "Courier New", monospace; font-size: 12px;
}

/* ── 트리/리스트 ── */
QTreeWidget, QListWidget {
    background: #ffffff; border: 1px solid #e0e4e8;
    border-radius: 6px; outline: none;
    alternate-background-color: #f7f9fb;
}
QTreeWidget::item, QListWidget::item {
    padding: 5px 4px; border-radius: 4px;
}
QTreeWidget::item:selected, QListWidget::item:selected {
    background: #cce4f7; color: #1a1a1a;
}
QTreeWidget::item:hover, QListWidget::item:hover { background: #edf5fc; }
QHeaderView::section {
    background: #f4f6f8; color: #505558;
    border: none; border-bottom: 1px solid #e0e4e8;
    padding: 6px 8px; font-weight: 600; font-size: 12px;
}

/* ── 프로그레스 바 ── */
QProgressBar {
    background: #e4e8ec; border: none; border-radius: 4px;
    height: 6px; text-align: center; color: transparent;
}
QProgressBar::chunk { background: #0078d4; border-radius: 4px; }
QProgressBar[busy="true"]::chunk { background: #0078d4; }

/* ── 체크박스 ── */
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1.5px solid #8a9099; border-radius: 4px;
    background: #ffffff;
}
QCheckBox::indicator:checked {
    background: #0078d4; border-color: #0078d4;
    image: none;
}
QCheckBox::indicator:hover { border-color: #0078d4; }

/* ── 스크롤바 ── */
QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
QScrollBar::handle:vertical { background: #c0c8d0; border-radius: 3px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #9aaab8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 6px; margin: 0; }
QScrollBar::handle:horizontal { background: #c0c8d0; border-radius: 3px; min-width: 24px; }
QScrollBar::handle:horizontal:hover { background: #9aaab8; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ── 상태바 ── */
QStatusBar { background: #f4f6f8; border-top: 1px solid #e0e4e8; color: #606468; font-size: 12px; }

/* ── 라벨 ── */
QLabel#page_title { font-size: 22px; font-weight: 700; color: #1a1a1a; }
QLabel#page_subtitle { font-size: 13px; color: #606468; }
QLabel#section_label { font-size: 12px; font-weight: 600; color: #505558; text-transform: uppercase; letter-spacing: 0.5px; }
QLabel#stat_num { font-size: 30px; font-weight: 700; color: #0078d4; }
QLabel#stat_cap { font-size: 11px; color: #808488; }
QLabel#badge_ok { color: #107c10; font-weight: 600; font-size: 13px; }
QLabel#badge_err { color: #c42b1c; font-weight: 600; font-size: 13px; }
QLabel#badge_warn { color: #c07700; font-weight: 600; font-size: 13px; }

/* ── 구분선 ── */
QFrame#hline { background: #e0e4e8; max-height: 1px; }
QFrame#vline { background: #e0e4e8; max-width: 1px; }

/* ── 네비게이션 바 ── */
QFrame#nav_bar { background: #ffffff; border-top: 1px solid #e0e4e8; }
"""

STEPS = [
    ("1", "소스 설정",      "정리할 폴더와 대상 폴더를 선택합니다"),
    ("2", "필터 규칙",      "제외 폴더와 안전 설정을 조정합니다"),
    ("3", "분석 대시보드",  "폴더 구조와 파일 현황을 분석합니다"),
    ("4", "검토 및 계획",   "중복 검토 후 정리 계획을 수립합니다"),
    ("5", "정리 실행",      "Dry-run 검증 후 파일을 이동합니다"),
]

# ─── Worker ──────────────────────────────────────────────────────────────────
if _PYSIDE6_OK:
    class _Sig(QObject):
        result   = Signal(object)
        error    = Signal(str)
        finished = Signal()

    class Worker(QRunnable):
        def __init__(self, fn, *a, **kw):
            super().__init__()
            self.fn = fn; self.a = a; self.kw = kw
            self.signals = _Sig()
            self.setAutoDelete(True)

        @Slot()
        def run(self):
            try:
                self.signals.result.emit(self.fn(*self.a, **self.kw))
            except Exception as e:
                self.signals.error.emit(str(e))
            finally:
                self.signals.finished.emit()

# ─── 헬퍼 ────────────────────────────────────────────────────────────────────
def _card(name="card", parent=None):
    f = QFrame(parent); f.setObjectName(name); return f

def _hline(parent=None):
    f = QFrame(parent); f.setObjectName("hline"); f.setFixedHeight(1); return f

def _fmt_bytes(b: int) -> str:
    for u in ("B","KB","MB","GB","TB"):
        if b < 1024: return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} PB"

def _section(text: str, parent=None) -> QLabel:
    l = QLabel(text, parent); l.setObjectName("section_label"); return l

def _browse_btn(parent=None) -> QPushButton:
    b = QPushButton("  찾아보기", parent)
    b.setObjectName("btn_secondary"); b.setFixedWidth(110)
    return b

# ─── 사이드바 ─────────────────────────────────────────────────────────────────
def _build_sidebar(parent, current: int) -> QFrame:
    sb = QFrame(parent); sb.setObjectName("sidebar"); sb.setFixedWidth(230)
    lay = QVBoxLayout(sb); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

    title = QLabel("📷  Photo Organizer"); title.setObjectName("app_title")
    ver   = QLabel("v1.0"); ver.setObjectName("app_version")
    lay.addWidget(title); lay.addWidget(ver)

    div = QFrame(); div.setObjectName("sidebar_divider"); div.setFixedHeight(1)
    lay.addWidget(div); lay.addSpacing(8)

    for i, (num, name, _) in enumerate(STEPS):
        btn = QPushButton(f"  {num}   {name}")
        btn.setObjectName("step_btn_active" if i == current else "step_btn")
        btn.setEnabled(False)
        lay.addWidget(btn)

    lay.addStretch()
    return sb

# ─── Step 1: 소스 설정 ────────────────────────────────────────────────────────
def _page_step1(parent, state: dict) -> QWidget:
    page = QWidget(parent)
    root = QVBoxLayout(page); root.setContentsMargins(36, 28, 36, 28); root.setSpacing(20)

    # 헤더
    hdr = QVBoxLayout(); hdr.setSpacing(4)
    t = QLabel("소스 설정"); t.setObjectName("page_title")
    s = QLabel("정리할 사진 폴더와 결과를 저장할 폴더를 지정합니다."); s.setObjectName("page_subtitle")
    hdr.addWidget(t); hdr.addWidget(s)
    root.addLayout(hdr)
    root.addWidget(_hline())

    fields = [
        ("source_root",  "📁  원본 루트",   "정리할 사진이 있는 드라이브 또는 폴더",  r"D:\\",                       True),
        ("archive_root", "🗂️  정리 대상 루트", "사진을 날짜별로 정리해서 모을 폴더",   r"D:\\PICTURES",              True),
        ("db_path",      "💾  데이터베이스",  "앱 상태를 저장하는 파일 (자동 생성)",   str(_default_db_path()),       False),
    ]

    for key, label, hint, default, has_browse in fields:
        card = _card(); cl = QVBoxLayout(card); cl.setContentsMargins(20, 16, 20, 16); cl.setSpacing(8)

        lbl_row = QHBoxLayout()
        lbl = QLabel(label); lbl.setStyleSheet("font-weight:600; font-size:14px;")
        hint_lbl = QLabel(hint); hint_lbl.setStyleSheet("color:#808488; font-size:12px;")
        lbl_row.addWidget(lbl); lbl_row.addStretch(); lbl_row.addWidget(hint_lbl)
        cl.addLayout(lbl_row)

        row = QHBoxLayout(); row.setSpacing(8)
        edit = QLineEdit(state.get(key, default)); edit.setPlaceholderText(default)
        edit.textChanged.connect(lambda t, k=key: state.update({k: t}))
        row.addWidget(edit)

        if has_browse:
            btn = _browse_btn()
            def _pick(_, k=key, e=edit):
                p = QFileDialog.getExistingDirectory(page, "폴더 선택", e.text())
                if p: e.setText(p); state[k] = p
            btn.clicked.connect(_pick)
            row.addWidget(btn)
        cl.addLayout(row)
        root.addWidget(card)

    root.addStretch()
    return page

# ─── Step 2: 필터 규칙 ────────────────────────────────────────────────────────
def _page_step2(parent, state: dict) -> QWidget:
    page = QWidget(parent)
    root = QVBoxLayout(page); root.setContentsMargins(36, 28, 36, 28); root.setSpacing(20)

    t = QLabel("필터 규칙"); t.setObjectName("page_title")
    s = QLabel("정리 대상에서 제외할 폴더와 안전 설정을 조정합니다."); s.setObjectName("page_subtitle")
    root.addWidget(t); root.addWidget(s); root.addWidget(_hline())

    # 제외 폴더
    excl_card = _card(); el = QVBoxLayout(excl_card); el.setContentsMargins(20, 16, 20, 16); el.setSpacing(10)
    el.addWidget(_section("🚫  기본 제외 폴더"))
    el.addWidget(_hline())

    EXCLUSIONS = [
        (".thumbnails",              True,  "썸네일 캐시"),
        ("$RECYCLE.BIN",             True,  "휴지통"),
        ("System Volume Information",True,  "시스템 볼륨 정보"),
        ("OneDriveTemp",             True,  "OneDrive 임시 파일"),
        (".tmp 계열",                True,  "임시 파일"),
        ("Google Photos",            True,  "클라우드 동기화"),
        ("Samsung Gallery",          True,  "클라우드 동기화"),
        ("OneDrive",                 True,  "클라우드 동기화"),
    ]
    grid = QHBoxLayout(); grid.setSpacing(12)
    col1 = QVBoxLayout(); col2 = QVBoxLayout()
    for i, (name, checked, note) in enumerate(EXCLUSIONS):
        cb = QCheckBox(f"{name}  ")
        cb.setChecked(checked)
        cb.setToolTip(note)
        (col1 if i < 4 else col2).addWidget(cb)
    grid.addLayout(col1); grid.addLayout(col2)
    el.addLayout(grid)
    root.addWidget(excl_card)

    # 안전 설정
    safe_card = _card(); sl = QVBoxLayout(safe_card); sl.setContentsMargins(20, 16, 20, 16); sl.setSpacing(10)
    sl.addWidget(_section("🔒  안전 설정"))
    sl.addWidget(_hline())

    ro_cb = QCheckBox("읽기 전용 모드  —  이 모드에서는 파일을 이동하지 않습니다 (권장)")
    ro_cb.setChecked(state.get("read_only", True))
    ro_cb.setStyleSheet("font-size:13px; padding: 4px 0;")
    ro_cb.toggled.connect(lambda v: state.update({"read_only": v}))
    sl.addWidget(ro_cb)

    ro_desc = QLabel("파일 이동을 실행하려면 Step 5에서 읽기 전용을 해제하세요.")
    ro_desc.setStyleSheet("color:#808488; font-size:12px; padding-left: 24px;")
    sl.addWidget(ro_desc)
    root.addWidget(safe_card)

    root.addStretch()
    return page

# ─── Step 3: 분석 대시보드 ────────────────────────────────────────────────────
def _page_step3(parent, state: dict) -> QWidget:
    page = QWidget(parent)
    root = QVBoxLayout(page); root.setContentsMargins(36, 28, 36, 28); root.setSpacing(16)

    t = QLabel("분석 대시보드"); t.setObjectName("page_title")
    s = QLabel("원본 폴더를 스캔하여 파일 현황을 분석합니다."); s.setObjectName("page_subtitle")
    root.addWidget(t); root.addWidget(s); root.addWidget(_hline())

    # 스캔 컨트롤
    ctrl_card = _card(); ctl = QHBoxLayout(ctrl_card); ctl.setContentsMargins(16, 12, 16, 12); ctl.setSpacing(12)
    scan_btn = QPushButton("  📂  스캔 시작"); scan_btn.setFixedHeight(38); scan_btn.setMinimumWidth(140)
    prog = QProgressBar(); prog.setRange(0, 0); prog.setVisible(False); prog.setFixedHeight(6)
    status_lbl = QLabel("스캔 전 상태입니다. 스캔을 시작하세요.")
    status_lbl.setStyleSheet("color:#606468; font-size:12px;")
    ctl.addWidget(scan_btn); ctl.addWidget(prog, 1); ctl.addWidget(status_lbl, 2)
    root.addWidget(ctrl_card)

    # 통계 카드 4개
    stat_row = QHBoxLayout(); stat_row.setSpacing(12)
    stat_labels: dict[str, QLabel] = {}
    for key, icon, caption in [
        ("total",  "📄", "총 파일"),
        ("photos", "🖼️", "사진 파일"),
        ("size",   "💽", "총 용량"),
        ("dups",   "🔁", "중복 그룹"),
    ]:
        c = _card(); cl = QVBoxLayout(c); cl.setContentsMargins(16, 14, 16, 14); cl.setSpacing(4)
        ic = QLabel(icon); ic.setStyleSheet("font-size:22px;"); ic.setAlignment(Qt.AlignCenter)
        num = QLabel("—"); num.setObjectName("stat_num"); num.setAlignment(Qt.AlignCenter)
        cap = QLabel(caption); cap.setObjectName("stat_cap"); cap.setAlignment(Qt.AlignCenter)
        cl.addWidget(ic); cl.addWidget(num); cl.addWidget(cap)
        stat_labels[key] = num; stat_row.addWidget(c)
    root.addLayout(stat_row)

    # 폴더 트리
    tree_card = _card(); tl = QVBoxLayout(tree_card); tl.setContentsMargins(16, 14, 16, 14); tl.setSpacing(8)
    tl.addWidget(_section("📁  폴더별 현황"))
    folder_tree = QTreeWidget()
    folder_tree.setHeaderLabels(["폴더 경로", "파일 수", "사진 수", "용량"])
    folder_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
    for i in range(1, 4):
        folder_tree.header().setSectionResizeMode(i, QHeaderView.ResizeToContents)
    folder_tree.setAlternatingRowColors(True)
    folder_tree.setRootIsDecorated(False)
    folder_tree.setMinimumHeight(220)
    tl.addWidget(folder_tree)
    root.addWidget(tree_card, 1)

    # 로그
    log_edit = QTextEdit(); log_edit.setReadOnly(True); log_edit.setFixedHeight(72)
    log_edit.setPlaceholderText("스캔 로그가 여기에 표시됩니다…")
    root.addWidget(log_edit)

    state["_step3"] = {
        "scan_btn": scan_btn, "prog": prog, "status_lbl": status_lbl,
        "stat_labels": stat_labels, "folder_tree": folder_tree, "log_edit": log_edit,
    }
    return page

# ─── Step 4: 검토 및 계획 ─────────────────────────────────────────────────────
def _page_step4(parent, state: dict) -> QWidget:
    page = QWidget(parent)
    root = QVBoxLayout(page); root.setContentsMargins(36, 28, 36, 28); root.setSpacing(16)

    t = QLabel("검토 및 계획"); t.setObjectName("page_title")
    s = QLabel("중복 사진을 검토하고 정리 계획을 생성합니다."); s.setObjectName("page_subtitle")
    root.addWidget(t); root.addWidget(s); root.addWidget(_hline())

    splitter = QSplitter(Qt.Horizontal); splitter.setHandleWidth(1)

    # 왼쪽: 검토 큐
    left = _card(); ll = QVBoxLayout(left); ll.setContentsMargins(16, 14, 16, 14); ll.setSpacing(8)
    ll.addWidget(_section("🔍  검토 큐"))
    review_list = QListWidget(); review_list.setAlternatingRowColors(True)
    ll.addWidget(review_list, 1)
    load_btn = QPushButton("  📋  검토 큐 불러오기"); load_btn.setObjectName("btn_secondary")
    ll.addWidget(load_btn)
    splitter.addWidget(left)

    # 오른쪽: 정리 계획
    right = _card(); rl = QVBoxLayout(right); rl.setContentsMargins(16, 14, 16, 14); rl.setSpacing(8)
    rl.addWidget(_section("📋  정리 계획 미리보기"))
    plan_tree = QTreeWidget(); plan_tree.setAlternatingRowColors(True); plan_tree.setRootIsDecorated(False)
    plan_tree.setHeaderLabels(["대상 경로", "원본 경로"])
    plan_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
    plan_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
    rl.addWidget(plan_tree, 1)

    btn_row = QHBoxLayout(); btn_row.setSpacing(8)
    build_btn   = QPushButton("  📐  계획 생성")
    export_btn  = QPushButton("  💾  Review 저장"); export_btn.setObjectName("btn_secondary")
    codex_btn   = QPushButton("  📥  Review 로드"); codex_btn.setObjectName("btn_secondary")
    btn_row.addWidget(build_btn); btn_row.addWidget(export_btn); btn_row.addWidget(codex_btn)
    rl.addLayout(btn_row)
    splitter.addWidget(right)

    splitter.setSizes([320, 520])
    root.addWidget(splitter, 1)

    state["_step4"] = {
        "review_list": review_list, "plan_tree": plan_tree,
        "load_btn": load_btn, "build_btn": build_btn,
        "export_btn": export_btn, "codex_btn": codex_btn,
    }
    return page

# ─── Step 5: 정리 실행 ────────────────────────────────────────────────────────
def _page_step5(parent, state: dict) -> QWidget:
    page = QWidget(parent)
    root = QVBoxLayout(page); root.setContentsMargins(36, 28, 36, 28); root.setSpacing(16)

    t = QLabel("정리 실행"); t.setObjectName("page_title")
    s = QLabel("Dry-run으로 안전을 검증한 후 실제 파일을 이동합니다."); s.setObjectName("page_subtitle")
    root.addWidget(t); root.addWidget(s); root.addWidget(_hline())

    # Dry-run 카드
    dc = _card(); dl = QVBoxLayout(dc); dl.setContentsMargins(20, 16, 20, 16); dl.setSpacing(10)
    dl.addWidget(_section("🧪  Dry-run 검증"))
    dl.addWidget(_hline())
    desc = QLabel("실제 파일 이동 전에 경로 이탈, 충돌, 제외 대상 포함 여부를 검사합니다.")
    desc.setStyleSheet("color:#606468; font-size:12px;")
    desc.setWordWrap(True); dl.addWidget(desc)
    dr_row = QHBoxLayout(); dr_row.setSpacing(12)
    dryrun_btn = QPushButton("  🧪  Dry-run 실행"); dryrun_btn.setObjectName("btn_secondary")
    result_lbl = QLabel(""); result_lbl.setObjectName("badge_warn")
    dr_row.addWidget(dryrun_btn); dr_row.addWidget(result_lbl); dr_row.addStretch()
    dl.addLayout(dr_row)
    root.addWidget(dc)

    # 실행 카드
    ec = _card(); el = QVBoxLayout(ec); el.setContentsMargins(20, 16, 20, 16); el.setSpacing(10)
    el.addWidget(_section("🚀  실제 실행"))
    el.addWidget(_hline())
    warn = QLabel("⚠️  현재 읽기 전용 모드입니다. 아래 체크박스를 해제해야 실행됩니다.")
    warn.setStyleSheet("color:#c07700; font-size:12px;"); warn.setWordWrap(True)
    el.addWidget(warn)
    unlock_cb = QCheckBox("읽기 전용 해제  —  파일이 실제로 이동됩니다")
    unlock_cb.setStyleSheet("color:#c42b1c; font-weight:600;")
    el.addWidget(unlock_cb)
    exec_prog = QProgressBar(); exec_prog.setRange(0, 100); exec_prog.setVisible(False)
    el.addWidget(exec_prog)
    exec_btn = QPushButton("  🚀  파일 이동 실행"); exec_btn.setObjectName("btn_danger"); exec_btn.setEnabled(False)
    el.addWidget(exec_btn)
    root.addWidget(ec)

    # 실행 로그
    lc = _card(); ll2 = QVBoxLayout(lc); ll2.setContentsMargins(16, 14, 16, 14); ll2.setSpacing(8)
    ll2.addWidget(_section("📄  실행 로그"))
    exec_log = QTextEdit(); exec_log.setReadOnly(True); exec_log.setMinimumHeight(130)
    exec_log.setPlaceholderText("실행 결과가 여기에 표시됩니다…")
    ll2.addWidget(exec_log)
    root.addWidget(lc, 1)

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

# ─── 메인 윈도우 ──────────────────────────────────────────────────────────────
class PhotoOrganizerWindow(QMainWindow):
    def __init__(self, db_path: Path | None = None):
        super().__init__()
        self.setWindowTitle("Photo Organizer  v1.0")
        self.resize(1160, 760)
        self.setMinimumSize(960, 640)

        self._db_path = db_path or _default_db_path()
        self._pool = QThreadPool.globalInstance()
        self._step = 0
        self._state: dict[str, Any] = {
            "source_root":  r"D:\\",
            "archive_root": r"D:\\PICTURES",
            "db_path":      str(self._db_path),
            "read_only":    True,
        }
        self._build_ui()
        self._go(0)

    # ── UI 구성 ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QHBoxLayout(central); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        self._sb_wrap = QWidget(); self._sb_wrap.setFixedWidth(230)
        self._sb_lay  = QVBoxLayout(self._sb_wrap)
        self._sb_lay.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._sb_wrap)

        content = QWidget(); content.setStyleSheet("background:#f0f0f0;")
        cl = QVBoxLayout(content); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(0)

        self._stack = QStackedWidget()
        builders = [_page_step1, _page_step2, _page_step3, _page_step4, _page_step5]
        self._pages = [b(self._stack, self._state) for b in builders]
        for p in self._pages: self._stack.addWidget(p)
        cl.addWidget(self._stack, 1)

        # 네비게이션 바
        nav = QFrame(); nav.setObjectName("nav_bar"); nav.setFixedHeight(64)
        nl = QHBoxLayout(nav); nl.setContentsMargins(28, 0, 28, 0); nl.setSpacing(12)
        self._back_btn = QPushButton("  ← 이전"); self._back_btn.setObjectName("btn_secondary")
        self._back_btn.setFixedWidth(110); self._back_btn.clicked.connect(self._on_back)
        self._step_lbl = QLabel(""); self._step_lbl.setStyleSheet("color:#808488; font-size:12px;")
        self._next_btn = QPushButton("다음  →"); self._next_btn.setFixedWidth(110)
        self._next_btn.clicked.connect(self._on_next)
        nl.addWidget(self._back_btn); nl.addStretch()
        nl.addWidget(self._step_lbl); nl.addStretch()
        nl.addWidget(self._next_btn)
        cl.addWidget(nav)
        root.addWidget(content, 1)

        self._sbar = QStatusBar(); self.setStatusBar(self._sbar)
        self._sbar.showMessage("준비")

        self._wire_step3(); self._wire_step4(); self._wire_step5()

    def _rebuild_sidebar(self):
        for i in reversed(range(self._sb_lay.count())):
            w = self._sb_lay.itemAt(i).widget()
            if w: w.setParent(None)
        self._sb_lay.addWidget(_build_sidebar(self._sb_wrap, self._step))

    def _go(self, step: int):
        self._step = max(0, min(step, len(STEPS) - 1))
        self._stack.setCurrentIndex(self._step)
        self._rebuild_sidebar()
        self._back_btn.setEnabled(self._step > 0)
        self._next_btn.setText("완료" if self._step == len(STEPS) - 1 else "다음  →")
        self._step_lbl.setText(f"단계  {self._step + 1} / {len(STEPS)}")

    def _on_next(self):
        if self._step < len(STEPS) - 1: self._go(self._step + 1)
        else: QMessageBox.information(self, "완료", "모든 단계가 완료되었습니다.")

    def _on_back(self): self._go(self._step - 1)

    # ── Step 3 ───────────────────────────────────────────────────────────────
    def _wire_step3(self):
        self._state["_step3"]["scan_btn"].clicked.connect(self._run_scan)

    def _run_scan(self):
        from .database import connect
        from .scanner import scan_media

        w = self._state["_step3"]
        w["scan_btn"].setEnabled(False); w["prog"].setVisible(True)
        w["status_lbl"].setText("스캔 중…"); w["log_edit"].clear()
        self._sbar.showMessage("스캔 중…")

        source  = self._state.get("source_root", "")
        db_path = Path(self._state.get("db_path", str(_default_db_path())))

        def _task():
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(connect(db_path)) as con:
                count = scan_media(con, source)
                row   = con.execute("SELECT COUNT(*) c, COALESCE(SUM(size_bytes),0) b FROM media_files WHERE exists_on_disk=1").fetchone()
                photo = con.execute("SELECT COUNT(*) c FROM media_files WHERE exists_on_disk=1 AND media_type IN ('jpeg','raw','image','screenshot')").fetchone()
                dups  = con.execute("SELECT sha256 FROM media_files WHERE sha256 IS NOT NULL AND exists_on_disk=1 GROUP BY sha256 HAVING COUNT(*)>1").fetchall()
                folds = con.execute("SELECT parent_key, COUNT(*) c, SUM(CASE WHEN media_type IN ('jpeg','raw','image','screenshot') THEN 1 ELSE 0 END) pc, COALESCE(SUM(size_bytes),0) b FROM media_files WHERE exists_on_disk=1 GROUP BY parent_key ORDER BY c DESC LIMIT 300").fetchall()
            return {"ok":True,"count":count,"total":row["c"],"bytes":row["b"],"photos":photo["c"],"dups":len(dups),"folders":[(r["parent_key"],r["c"],r["pc"],r["b"]) for r in folds]}

        worker = Worker(_task)
        worker.signals.result.connect(self._on_scan_done)
        worker.signals.error.connect(self._on_scan_err)
        self._pool.start(worker)

    @Slot(object)
    def _on_scan_done(self, r: dict):
        w = self._state["_step3"]
        w["scan_btn"].setEnabled(True); w["prog"].setVisible(False)
        if not r.get("ok"):
            w["log_edit"].append(f"❌ {r.get('error')}"); return
        sl = w["stat_labels"]
        sl["total"].setText(f"{r['total']:,}")
        sl["photos"].setText(f"{r['photos']:,}")
        sl["size"].setText(_fmt_bytes(r["bytes"]))
        sl["dups"].setText(str(r["dups"]))
        tree: QTreeWidget = w["folder_tree"]; tree.clear()
        for folder, cnt, pcnt, size in r["folders"]:
            item = QTreeWidgetItem([folder or ".", f"{cnt:,}", f"{pcnt:,}", _fmt_bytes(size)])
            item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
            item.setTextAlignment(3, Qt.AlignRight | Qt.AlignVCenter)
            tree.addTopLevelItem(item)
        w["status_lbl"].setText(f"스캔 완료 — {r['total']:,}개 파일, {_fmt_bytes(r['bytes'])}")
        w["log_edit"].append(f"✅ 스캔 완료: {r['count']:,}개 파일 처리됨")
        self._sbar.showMessage(f"스캔 완료 — {r['total']:,}개 파일")
        self._state["_scan_done"] = True

    @Slot(str)
    def _on_scan_err(self, err: str):
        w = self._state["_step3"]
        w["scan_btn"].setEnabled(True); w["prog"].setVisible(False)
        w["status_lbl"].setText(f"오류: {err}")
        w["log_edit"].append(f"❌ {err}"); self._sbar.showMessage("스캔 오류")

    # ── Step 4 ───────────────────────────────────────────────────────────────
    def _wire_step4(self):
        w = self._state["_step4"]
        w["load_btn"].clicked.connect(self._load_review)
        w["build_btn"].clicked.connect(self._build_plan)
        w["export_btn"].clicked.connect(self._export_review)
        w["codex_btn"].clicked.connect(self._load_codex)

    def _load_review(self):
        from .database import connect
        from .review import review_queue_counts
        db_path = Path(self._state.get("db_path", str(_default_db_path())))
        if not db_path.exists():
            QMessageBox.warning(self, "DB 없음", "먼저 Step 3에서 스캔을 실행하세요."); return
        try:
            with closing(connect(db_path)) as con: counts = review_queue_counts(con)
            rl: QListWidget = self._state["_step4"]["review_list"]; rl.clear()
            icons = {"exact_duplicate_groups":"🔁","raw_jpg_pairs":"📷","raw_without_jpg":"📷","non_person_candidates":"🖼️","videos":"🎬"}
            for q, n in counts.items():
                ic = icons.get(q, "📄")
                item = QListWidgetItem(f"  {ic}  {q.replace('_',' ').title()}    {n:,}개")
                rl.addItem(item)
            self._sbar.showMessage("검토 큐 로드 완료")
        except Exception as exc: QMessageBox.critical(self, "오류", str(exc))

    def _build_plan(self):
        from .database import connect
        from .planning import build_archive_plans
        db_path = Path(self._state.get("db_path", str(_default_db_path())))
        archive_root = self._state.get("archive_root", r"D:\\PICTURES")
        if not db_path.exists():
            QMessageBox.warning(self, "DB 없음", "먼저 Step 3에서 스캔을 실행하세요."); return
        self._sbar.showMessage("정리 계획 생성 중…")
        def _task():
            with closing(connect(db_path)) as con:
                return build_archive_plans(con, archive_root=archive_root)
        worker = Worker(_task)
        worker.signals.result.connect(self._on_plan_done)
        worker.signals.error.connect(lambda e: (self._sbar.showMessage(f"오류: {e}"), QMessageBox.critical(self,"오류",e)))
        self._pool.start(worker)

    @Slot(object)
    def _on_plan_done(self, plans: list):
        self._state["_plans"] = plans
        tree: QTreeWidget = self._state["_step4"]["plan_tree"]; tree.clear()
        for p in plans[:2000]:
            tree.addTopLevelItem(QTreeWidgetItem([p["planned_path"], p["source_path"]]))
        self._sbar.showMessage(f"정리 계획 {len(plans):,}건 생성 완료")

    def _export_review(self):
        from .database import connect
        from .review import export_review_package
        db_path = Path(self._state.get("db_path", str(_default_db_path())))
        if not db_path.exists():
            QMessageBox.warning(self, "DB 없음", "먼저 Step 3에서 스캔을 실행하세요."); return
        out = _default_review_dir(self._state.get("archive_root", r"D:\\PICTURES"))
        try:
            with closing(connect(db_path)) as con: summary = export_review_package(con, out)
            QMessageBox.information(self, "Review 저장 완료",
                f"저장 위치: {out}\n\n" + "\n".join(f"  {k}: {v}" for k, v in summary["queue_counts"].items()))
            self._sbar.showMessage(f"Review 저장: {out}")
        except Exception as exc: QMessageBox.critical(self, "오류", str(exc))

    def _load_codex(self):
        path, _ = QFileDialog.getOpenFileName(self, "codex_review.json 선택", "", "JSON (*.json)")
        if not path: return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            decisions = data.get("folder_decisions", [])
            self._state["_codex_review"] = data
            QMessageBox.information(self, "Review 로드 완료", f"폴더 결정 {len(decisions)}건 로드됨")
            self._sbar.showMessage(f"codex_review.json 로드: {len(decisions)}건")
        except Exception as exc: QMessageBox.critical(self, "오류", str(exc))

    # ── Step 5 ───────────────────────────────────────────────────────────────
    def _wire_step5(self):
        w = self._state["_step5"]
        w["dryrun_btn"].clicked.connect(self._run_dryrun)
        w["exec_btn"].clicked.connect(self._run_execute)

    def _run_dryrun(self):
        plans = self._state.get("_plans")
        if not plans:
            QMessageBox.warning(self, "계획 없음", "먼저 Step 4에서 정리 계획을 생성하세요."); return
        from .win_fs import validate_move_plan
        archive_root = Path(self._state.get("archive_root", r"D:\\PICTURES"))
        w = self._state["_step5"]
        errors = validate_move_plan(plans, archive_root)
        rl: QLabel = w["result_lbl"]
        if errors:
            rl.setText(f"❌  Dry-run 실패: {len(errors)}건 오류")
            rl.setObjectName("badge_err"); rl.style().unpolish(rl); rl.style().polish(rl)
            w["exec_log"].append("Dry-run 실패:\n" + "\n".join(errors[:20]))
        else:
            rl.setText(f"✅  Dry-run 통과: 오류 0건 ({len(plans):,}개 계획)")
            rl.setObjectName("badge_ok"); rl.style().unpolish(rl); rl.style().polish(rl)
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
        if QMessageBox.question(self,"파일 이동 확인",f"{len(plans):,}개 파일을 이동합니까?",
                                QMessageBox.Yes|QMessageBox.No) != QMessageBox.Yes: return
        if QMessageBox.question(self,"최종 확인","이 작업은 되돌리기 어렵습니다. 계속하시겠습니까?",
                                QMessageBox.Yes|QMessageBox.No) != QMessageBox.Yes: return
        w = self._state["_step5"]
        w["exec_btn"].setEnabled(False); w["exec_prog"].setVisible(True)
        self._sbar.showMessage("파일 이동 중…")
        archive_root = Path(self._state.get("archive_root", r"D:\\PICTURES"))

        def _task():
            import csv
            from datetime import datetime
            from .win_fs import safe_move
            review_dir = _default_review_dir(str(archive_root))
            log_rows, undo_rows, moved = [], [], 0
            for p in plans:
                src, dst = Path(p["source_path"]), Path(p["planned_path"])
                try:
                    safe_move(src, dst); moved += 1
                    log_rows.append((str(src), str(dst), "moved", datetime.now().isoformat()))
                    undo_rows.append((str(dst), str(src)))
                except (OSError, PermissionError) as exc:
                    log_rows.append((str(src), str(dst), f"failed:{exc}", datetime.now().isoformat()))
            log_path  = review_dir / "execution_log.csv"
            undo_path = review_dir / "undo_plan.csv"
            for path, hdr, rows in [(log_path,["source","destination","result","timestamp"],log_rows),
                                     (undo_path,["moved_path","restore_to"],undo_rows)]:
                with open(path,"w",newline="",encoding="utf-8-sig") as f:
                    wt = csv.writer(f); wt.writerow(hdr); wt.writerows(rows)
            return {"moved":moved,"total":len(plans),"log_path":str(log_path)}

        worker = Worker(_task)
        worker.signals.result.connect(self._on_exec_done)
        worker.signals.error.connect(lambda e: (
            w["exec_btn"].setEnabled(True), w["exec_prog"].setVisible(False),
            QMessageBox.critical(self,"실행 오류",e)))
        self._pool.start(worker)

    @Slot(object)
    def _on_exec_done(self, r: dict):
        w = self._state["_step5"]
        w["exec_btn"].setEnabled(True); w["exec_prog"].setVisible(False); w["exec_prog"].setValue(100)
        msg = f"✅  {r['moved']:,}/{r['total']:,}개 이동 완료\n로그: {r['log_path']}"
        w["exec_log"].append(msg)
        self._sbar.showMessage(f"실행 완료: {r['moved']:,}개 이동")
        QMessageBox.information(self,"실행 완료",msg)


# ─── 진입점 ──────────────────────────────────────────────────────────────────
def launch(db_path: str | Path | None = None) -> int:
    if not _PYSIDE6_OK:
        raise RuntimeError("PySide6가 설치되어 있지 않습니다. 'pip install PySide6'를 실행하세요.")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = PhotoOrganizerWindow(db_path=Path(db_path) if db_path else None)
    window.show()
    return app.exec()
