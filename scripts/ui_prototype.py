# -*- coding: utf-8 -*-
"""
Smart Photo Organizer - Wizard Sidebar UI Prototype (Premium Charcoal/Slate Dark Theme)
Premium, expert-grade Open-Design IDE Split Dashboard Layout (Option B).
File Location: D:\\work\\prj\\photos\\scripts\\ui_prototype.py
"""

import os
import time
import queue
import random
import threading
import tkinter as tk
from tkinter import ttk
from tkinter import filedialog

# ==============================================================================
# 1. VISUAL THEME & COLOR DESIGN CONSTANTS (Premium Charcoal/Slate Dark Theme)
# ==============================================================================
BG_DARK = "#202124"          # Main Background (Deep premium charcoal)
BG_SIDEBAR = "#1a1b1e"       # Sidebar Background (Slightly darker slate-charcoal for wizard pane)
BG_CARD = "#292a2d"          # Card Background (Slightly lighter charcoal cards for contrast)
BORDER_COLOR = "#3c4043"     # High-fidelity dark-slate borders

ACCENT_BLUE = "#1a73e8"      # Accent Blue (Google/Fluent Premium Blue)
ACCENT_GREEN = "#188038"     # Success Green (Premium Emerald/Mint Green)
ACCENT_RED = "#d93025"       # Warning/Delete Red (Premium Crimson/Coral Red)
ACCENT_YELLOW = "#f9ab00"    # Warning/Alert Yellow (Premium Amber/Gold)

TEXT_PRIMARY = "#e8eaed"     # Primary Text (High-contrast clean silver-white)
TEXT_SECONDARY = "#9aa0a6"   # Secondary Text (Muted slate-gray for descriptions)
TEXT_MUTED = "#5f6368"       # Muted Text (Disabled/low priority labels)

FONT_FAMILY = "Segoe UI"
FONT_MONO = "Consolas"

# ==============================================================================
# 2. CUSTOM HIGH-FIDELITY INTERACTIVE WIDGETS
# ==============================================================================

class HoverButton(tk.Button):
    """Modern styled button with dynamic hover states for Charcoal Dark Theme."""
    def __init__(self, master, active_bg=None, active_fg=None, border_color=BORDER_COLOR, **kwargs):
        self.normal_bg = kwargs.get('bg', BG_CARD)
        self.normal_fg = kwargs.get('fg', TEXT_PRIMARY)
        
        # Automatically assign modern hover states based on original background
        if self.normal_bg == ACCENT_BLUE:
            self.hover_bg = "#2b82f6"
            self.hover_fg = "#ffffff"
            self.active_background = "#185abc"
        elif self.normal_bg == ACCENT_GREEN:
            self.hover_bg = "#1e8e3e"
            self.hover_fg = "#ffffff"
            self.active_background = "#137333"
        elif self.normal_bg == ACCENT_RED:
            self.hover_bg = "#e04347"
            self.hover_fg = "#ffffff"
            self.active_background = "#c5221f"
        elif self.normal_bg == BG_DARK:
            self.hover_bg = "#292a2d"
            self.hover_fg = TEXT_PRIMARY
            self.active_background = "#3c4043"
        else:
            # For standard card buttons or default buttons
            self.hover_bg = "#3c4043"
            self.hover_fg = TEXT_PRIMARY
            self.active_background = "#4a4e52"
            
        if active_bg: self.hover_bg = active_bg
        if active_fg: self.hover_fg = active_fg
        
        super().__init__(
            master, 
            bd=0, 
            relief='flat', 
            activebackground=self.active_background, 
            activeforeground=self.hover_fg if active_fg else self.normal_fg,
            highlightthickness=1,
            highlightbackground=border_color,
            highlightcolor=ACCENT_BLUE,
            **kwargs
        )
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)
        
    def on_enter(self, e):
        if self['state'] != 'disabled':
            self.config(bg=self.hover_bg, fg=self.hover_fg)
        
    def on_leave(self, e):
        if self['state'] != 'disabled':
            self.config(bg=self.normal_bg, fg=self.normal_fg)


class CustomProgressBar(tk.Canvas):
    """A smooth, thin progress bar matching premium accent."""
    def __init__(self, master, bg="#3c4043", border_color=BORDER_COLOR, fill_color=ACCENT_BLUE, height=8, **kwargs):
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, height=height, **kwargs)
        self.fill_color = fill_color
        self.progress = 0.0  # 0.0 to 1.0 range
        self.bind("<Configure>", self.on_resize)
        
    def on_resize(self, event):
        self.draw_bar()
        
    def draw_bar(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        # Draw background track
        self.create_rectangle(0, 0, w, h, fill="#3c4043", outline="")
        # Draw fill progress
        fill_width = int(w * self.progress)
        if fill_width > 0:
            self.create_rectangle(0, 0, fill_width, h, fill=self.fill_color, outline="")
            
    def set_progress(self, val):
        self.progress = max(0.0, min(1.0, val))
        self.draw_bar()


class SidebarStep(tk.Frame):
    """Interactive timeline element with accent indicator and state checkmarks."""
    def __init__(self, master, step_num, title, initial_status="pending", command=None, **kwargs):
        super().__init__(master, bg=BG_SIDEBAR, height=48, **kwargs)
        self.step_num = step_num
        self.title = title
        self.status = initial_status  # pending, active, completed
        self.command = command
        self.active = False
        
        self.grid_propagate(False)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        
        # Left Accent blue strip when active (4px)
        self.accent_bar = tk.Frame(self, width=4, bg=BG_SIDEBAR)
        self.accent_bar.grid(row=0, column=0, sticky="ns")
        
        # Compact circle canvas
        self.badge_canvas = tk.Canvas(self, width=24, height=24, bg=BG_SIDEBAR, highlightthickness=0, bd=0)
        self.badge_canvas.grid(row=0, column=1, padx=(10, 8), sticky="w")
        
        # Label Title
        self.title_label = tk.Label(self, text=self.title, font=(FONT_FAMILY, 9, "normal"), fg=TEXT_SECONDARY, bg=BG_SIDEBAR, anchor="w")
        self.title_label.grid(row=0, column=2, sticky="ew", padx=(0, 5))
        
        # Right Status symbol
        self.dot_label = tk.Label(self, text="○", font=(FONT_FAMILY, 9), fg=TEXT_MUTED, bg=BG_SIDEBAR, anchor="e")
        self.dot_label.grid(row=0, column=3, padx=(0, 12), sticky="e")
        
        # Bind events
        for widget in (self, self.badge_canvas, self.title_label, self.dot_label):
            widget.bind("<Enter>", self.on_enter)
            widget.bind("<Leave>", self.on_leave)
            widget.bind("<Button-1>", self.on_click)
            
        self.update_appearance()
        
    def draw_badge(self):
        self.badge_canvas.delete("all")
        bg_col = "#3c4043"
        text_col = TEXT_SECONDARY
        
        if self.status == "completed":
            bg_col = ACCENT_GREEN
            text_col = "#ffffff"
        elif self.status == "active" or self.active:
            bg_col = ACCENT_BLUE
            text_col = "#ffffff"
            
        # Draw base badge circle
        self.badge_canvas.create_oval(1, 1, 23, 23, fill=bg_col, outline="")
        
        # Draw small custom checkmark
        if self.status == "completed":
            self.badge_canvas.create_line(7, 12, 10, 15, fill=text_col, width=2, capstyle="round")
            self.badge_canvas.create_line(10, 15, 16, 8, fill=text_col, width=2, capstyle="round")
        else:
            self.badge_canvas.create_text(12, 12, text=str(self.step_num), fill=text_col, font=(FONT_FAMILY, 8, "bold"))
            
    def set_status(self, status):
        self.status = status
        self.update_appearance()
        
    def set_active(self, is_active):
        self.active = is_active
        self.update_appearance()
        
    def update_appearance(self):
        current_bg = "#2d2f31" if self.active else BG_SIDEBAR
        
        self.config(bg=current_bg)
        for w in (self.badge_canvas, self.title_label, self.dot_label):
            w.config(bg=current_bg)
            
        if self.active:
            self.accent_bar.config(bg=ACCENT_BLUE)
            self.title_label.config(fg=TEXT_PRIMARY, font=(FONT_FAMILY, 9, "bold"))
            self.dot_label.config(fg=ACCENT_BLUE, text="●")
        else:
            self.accent_bar.config(bg=BG_SIDEBAR)
            self.title_label.config(fg=TEXT_SECONDARY, font=(FONT_FAMILY, 9, "normal"))
            
            if self.status == "completed":
                self.dot_label.config(fg=ACCENT_GREEN, text="●")
            elif self.status == "pending":
                self.dot_label.config(fg=TEXT_MUTED, text="○")
            elif self.status == "active":
                self.dot_label.config(fg=ACCENT_BLUE, text="●")
                
        self.draw_badge()
        
    def on_enter(self, e):
        if not self.active:
            hover_bg = "#2d2f31"
            self.config(bg=hover_bg)
            for w in (self.badge_canvas, self.title_label, self.dot_label):
                w.config(bg=hover_bg)
            self.badge_canvas.config(bg=hover_bg)
            
    def on_leave(self, e):
        self.update_appearance()
        
    def on_click(self, e):
        if self.command:
            self.command(self.step_num)


class TelemetryCard(tk.Frame):
    """High-contrast card for the Live Telemetry Dashboard grid."""
    def __init__(self, master, title, initial_val="--", desc="--", **kwargs):
        super().__init__(master, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER_COLOR, bd=0, **kwargs)
        
        self.title_lbl = tk.Label(self, text=title, font=(FONT_FAMILY, 8), fg=TEXT_SECONDARY, bg=BG_CARD, anchor="w")
        self.title_lbl.pack(anchor="w", padx=10, pady=(8, 2))
        
        self.val_lbl = tk.Label(self, text=initial_val, font=(FONT_MONO, 14, "bold"), fg=ACCENT_BLUE, bg=BG_CARD, anchor="w")
        self.val_lbl.pack(anchor="w", padx=10, pady=(0, 1))
        
        self.desc_lbl = tk.Label(self, text=desc, font=(FONT_FAMILY, 8), fg=TEXT_MUTED, bg=BG_CARD, anchor="w")
        self.desc_lbl.pack(anchor="w", padx=10, pady=(0, 8))
        
    def update_telemetry(self, value, color=ACCENT_BLUE, desc=None):
        self.val_lbl.config(text=value, fg=color)
        if desc is not None:
            self.desc_lbl.config(text=desc)

# ==============================================================================
# 3. DYNAMIC RIGHT CONTAINER WORKSPACE PAGES
# ==============================================================================

class WorkspaceStep1(tk.Frame):
    """Step 1 Workspace View: Source folder explorer checklist."""
    def __init__(self, master, controller):
        super().__init__(master, bg=BG_DARK)
        self.controller = controller
        
        # 1. Header
        header = tk.Frame(self, bg=BG_DARK)
        header.pack(fill="x", padx=25, pady=(20, 12))
        
        tk.Label(header, text="WORKSPACE // STEP 1: 대상 디렉토리 브라우저", font=(FONT_FAMILY, 14, "bold"), fg=TEXT_PRIMARY, bg=BG_DARK).pack(anchor="w")
        tk.Label(header, text="스캔을 수행할 로컬 보관함 소스 주소 및 인덱스 처리 범위를 인가합니다.", font=(FONT_FAMILY, 9), fg=TEXT_SECONDARY, bg=BG_DARK).pack(anchor="w", pady=(3, 0))
        
        # 2. Path Entry Card
        card = tk.Frame(self, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER_COLOR, bd=0)
        card.pack(fill="x", padx=25, pady=8)
        
        tk.Label(card, text="소스 디렉토리 타겟 주소", font=(FONT_FAMILY, 10, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD).pack(anchor="w", padx=18, pady=(12, 5))
        
        path_frame = tk.Frame(card, bg=BG_CARD)
        path_frame.pack(fill="x", padx=18, pady=(0, 12))
        path_frame.columnconfigure(0, weight=1)
        
        self.path_entry = tk.Entry(path_frame, bg=BG_DARK, fg=TEXT_PRIMARY, insertbackground=TEXT_PRIMARY, bd=0, relief="flat", font=(FONT_MONO, 10))
        self.path_entry.grid(row=0, column=0, sticky="ew", ipady=7, padx=(0, 8))
        self.path_entry.insert(0, r"D:\work\prj\photos")
        self.path_entry.config(highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_BLUE)
        
        browse_btn = HoverButton(path_frame, text="폴더 탐색...", bg=BG_DARK, active_bg=ACCENT_BLUE, active_fg="#ffffff", font=(FONT_FAMILY, 9, "bold"), width=12, command=self.browse)
        browse_btn.grid(row=0, column=1, sticky="ns")
        
        # 3. Dynamic subdirectories selector
        list_card = tk.Frame(self, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER_COLOR, bd=0)
        list_card.pack(fill="both", expand=True, padx=25, pady=8)
        
        tk.Label(list_card, text="인덱싱 대상 하위 세부 디렉토리 목록", font=(FONT_FAMILY, 10, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD).pack(anchor="w", padx=18, pady=(12, 4))
        tk.Label(list_card, text="활성화 처리된 폴더만 EXIF 분석 엔진의 1차 파이기반 라인에 주입됩니다.", font=(FONT_FAMILY, 8), fg=TEXT_SECONDARY, bg=BG_CARD).pack(anchor="w", padx=18, pady=(0, 8))
        
        list_container = tk.Frame(list_card, bg=BG_DARK, highlightthickness=1, highlightbackground=BORDER_COLOR)
        list_container.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        
        canvas = tk.Canvas(list_container, bg=BG_DARK, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(list_container, orient="vertical", command=canvas.yview, bg=BG_DARK)
        scrollable_frame = tk.Frame(canvas, bg=BG_DARK)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Dynamic search inside photos directory
        try:
            workspace_path = r"D:\work\prj\photos"
            folders = [d for d in os.listdir(workspace_path) if os.path.isdir(os.path.join(workspace_path, d))]
            folders = [d for d in folders if not d.startswith('.')]
        except Exception:
            folders = ["src", "tests", "scripts", "legacy2", "dist", "build", "vendor"]
            
        if not folders:
            folders = ["src", "tests", "scripts", "legacy2", "dist", "build", "vendor"]
            
        self.checks = {}
        for folder in folders:
            item = tk.Frame(scrollable_frame, bg=BG_DARK, pady=4)
            item.pack(fill="x", padx=12, anchor="w")
            
            var = tk.BooleanVar(value=True)
            self.checks[folder] = var
            
            chk = tk.Checkbutton(
                item, 
                text=f"  {folder}/", 
                variable=var, 
                bg=BG_DARK, 
                fg=TEXT_PRIMARY, 
                selectcolor=BG_CARD, 
                activebackground=BG_DARK, 
                activeforeground=TEXT_PRIMARY,
                font=(FONT_MONO, 9),
                bd=0
            )
            chk.pack(side="left")
            
            mock_cap = random.choice(["4.24 GB", "210.5 MB", "1.18 GB", "512 KB", "18.3 MB"])
            lbl = tk.Label(item, text=f"({mock_cap})", font=(FONT_FAMILY, 8), fg=TEXT_MUTED, bg=BG_DARK)
            lbl.pack(side="right", padx=(40, 10))
            
        # Action Row
        action_row = tk.Frame(self, bg=BG_DARK)
        action_row.pack(fill="x", padx=25, pady=(8, 20))
        
        next_btn = HoverButton(action_row, text="다음 설정 단계로 이동  →", bg=ACCENT_BLUE, active_bg="#1557b0", active_fg="#ffffff", border_color=ACCENT_BLUE, font=(FONT_FAMILY, 9, "bold"), pady=8, fg="#ffffff", command=self.next_step)
        next_btn.pack(side="right")
        
    def browse(self):
        path = filedialog.askdirectory(initialdir=r"D:\work\prj\photos")
        if path:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, path)
            self.controller.show_notification(f"디렉토리 변경: {os.path.basename(path)}")
            
    def next_step(self):
        self.controller.mark_complete(1)
        self.controller.switch_step(2)


class WorkspaceStep2(tk.Frame):
    """Step 2 Workspace View: Similarity slider & advanced configuration rules."""
    def __init__(self, master, controller):
        super().__init__(master, bg=BG_DARK)
        self.controller = controller
        
        # 1. Header
        header = tk.Frame(self, bg=BG_DARK)
        header.pack(fill="x", padx=25, pady=(20, 12))
        
        tk.Label(header, text="WORKSPACE // STEP 2: 스캔 필터 및 알고리즘 규칙", font=(FONT_FAMILY, 14, "bold"), fg=TEXT_PRIMARY, bg=BG_DARK).pack(anchor="w")
        tk.Label(header, text="중복 검출 감도 수준과 프로세서 스레드 연산 스콥을 최적화합니다.", font=(FONT_FAMILY, 9), fg=TEXT_SECONDARY, bg=BG_DARK).pack(anchor="w", pady=(3, 0))
        
        grid = tk.Frame(self, bg=BG_DARK)
        grid.pack(fill="both", expand=True, padx=25, pady=8)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        grid.rowconfigure(0, weight=1)
        
        # Left Card
        left = tk.Frame(grid, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER_COLOR, bd=0)
        left.grid(row=0, column=0, padx=(0, 8), sticky="nsew")
        
        tk.Label(left, text="중복 판단 알고리즘 기준 설정", font=(FONT_FAMILY, 10, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD).pack(anchor="w", padx=18, pady=(15, 12))
        
        self.mode_var = tk.IntVar(value=1)
        r1 = tk.Radiobutton(
            left, text=" 해시 바이너리 모드 (100% 동일 바이너리 파일 검출)", variable=self.mode_var, value=1,
            bg=BG_CARD, fg=TEXT_PRIMARY, selectcolor=BG_DARK, activebackground=BG_CARD, activeforeground=TEXT_PRIMARY,
            font=(FONT_FAMILY, 9), bd=0
        )
        r1.pack(anchor="w", padx=18, pady=5)
        
        r2 = tk.Radiobutton(
            left, text=" 지각 해시 유사 모드 (구도 및 조명이 유사한 연사 감지)", variable=self.mode_var, value=2,
            bg=BG_CARD, fg=TEXT_PRIMARY, selectcolor=BG_DARK, activebackground=BG_CARD, activeforeground=TEXT_PRIMARY,
            font=(FONT_FAMILY, 9), bd=0
        )
        r2.pack(anchor="w", padx=18, pady=5)
        
        tk.Label(left, text="중복 분석 허용치 슬라이더", font=(FONT_FAMILY, 9, "bold"), fg=TEXT_SECONDARY, bg=BG_CARD).pack(anchor="w", padx=18, pady=(15, 2))
        
        self.val_lbl = tk.Label(left, text="기준선: 95% 유사도 기준", font=(FONT_FAMILY, 9), fg=ACCENT_BLUE, bg=BG_CARD)
        self.val_lbl.pack(anchor="w", padx=18, pady=1)
        
        self.scale = tk.Scale(
            left, from_=80, to=100, orient="horizontal", bg=BG_CARD, fg=TEXT_PRIMARY,
            activebackground=ACCENT_BLUE, highlightbackground=BG_CARD, troughcolor=BG_DARK,
            relief="flat", bd=0, command=self.update_slider
        )
        self.scale.pack(fill="x", padx=18, pady=5)
        self.scale.set(95)
        
        # Right Card
        right = tk.Frame(grid, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER_COLOR, bd=0)
        right.grid(row=0, column=1, padx=(8, 0), sticky="nsew")
        
        tk.Label(right, text="스캐닝 고급 세부 매개변수", font=(FONT_FAMILY, 10, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD).pack(anchor="w", padx=18, pady=(15, 12))
        
        self.rec_var = tk.BooleanVar(value=True)
        chk_rec = tk.Checkbutton(
            right, text=" 하위 폴더 재귀적 분석 (Recursive Scan)", variable=self.rec_var,
            bg=BG_CARD, fg=TEXT_PRIMARY, selectcolor=BG_DARK, activebackground=BG_CARD, activeforeground=TEXT_PRIMARY,
            font=(FONT_FAMILY, 9), bd=0
        )
        chk_rec.pack(anchor="w", padx=18, pady=4)
        
        self.exif_var = tk.BooleanVar(value=True)
        chk_exif = tk.Checkbutton(
            right, text=" EXIF 메타데이터 시간/위치 파싱 활성화", variable=self.exif_var,
            bg=BG_CARD, fg=TEXT_PRIMARY, selectcolor=BG_DARK, activebackground=BG_CARD, activeforeground=TEXT_PRIMARY,
            font=(FONT_FAMILY, 9), bd=0
        )
        chk_exif.pack(anchor="w", padx=18, pady=4)
        
        self.corrupt_var = tk.BooleanVar(value=False)
        chk_cor_var = tk.Checkbutton(
            right, text=" 손상되거나 파손된 이미지 레코드 배제", variable=self.corrupt_var,
            bg=BG_CARD, fg=TEXT_PRIMARY, selectcolor=BG_DARK, activebackground=BG_CARD, activeforeground=TEXT_PRIMARY,
            font=(FONT_FAMILY, 9), bd=0
        )
        chk_cor_var.pack(anchor="w", padx=18, pady=4)
        
        # Thread Selector
        tk.Label(right, text="스레드 엔진 대역폭 모드", font=(FONT_FAMILY, 9, "bold"), fg=TEXT_SECONDARY, bg=BG_CARD).pack(anchor="w", padx=18, pady=(12, 3))
        
        combo = ttk.Combobox(right, values=["자동 (CPU Core 최적 권장)", "싱글 스레드 (대기 시간 김)", "2 스레드", "4 스레드", "8 스레드 (최대 파워)"], font=(FONT_FAMILY, 9), width=24)
        combo.pack(anchor="w", padx=18, pady=3)
        combo.current(0)
        
        # Action Row
        action_row = tk.Frame(self, bg=BG_DARK)
        action_row.pack(fill="x", padx=25, pady=(8, 20))
        
        prev_btn = HoverButton(action_row, text="←  이전 단계", bg=BG_DARK, border_color=BORDER_COLOR, font=(FONT_FAMILY, 9, "bold"), pady=8, width=12, command=self.go_prev)
        prev_btn.pack(side="left")
        
        next_btn = HoverButton(action_row, text="설정 저장 및 다음  →", bg=ACCENT_BLUE, active_bg="#1557b0", active_fg="#ffffff", border_color=ACCENT_BLUE, font=(FONT_FAMILY, 9, "bold"), pady=8, fg="#ffffff", command=self.go_next)
        next_btn.pack(side="right")
        
    def update_slider(self, val):
        self.val_lbl.config(text=f"기준선: {val}% 유사도 기준")
        
    def go_prev(self):
        self.controller.switch_step(1)
        
    def go_next(self):
        self.controller.mark_complete(2)
        self.controller.switch_step(3)


class WorkspaceStep3(tk.Frame):
    """Step 3 Workspace View: Donut chart & statistical reports."""
    def __init__(self, master, controller):
        super().__init__(master, bg=BG_DARK)
        self.controller = controller
        
        # 1. Header
        header = tk.Frame(self, bg=BG_DARK)
        header.pack(fill="x", padx=25, pady=(20, 12))
        
        tk.Label(header, text="WORKSPACE // STEP 3: 스캔 결과 분석 보고서", font=(FONT_FAMILY, 14, "bold"), fg=TEXT_PRIMARY, bg=BG_DARK).pack(anchor="w")
        tk.Label(header, text="바이너리 및 유사 구도 인덱싱을 거쳐 격리 대상으로 검출된 현황판입니다.", font=(FONT_FAMILY, 9), fg=TEXT_SECONDARY, bg=BG_DARK).pack(anchor="w", pady=(3, 0))
        
        grid = tk.Frame(self, bg=BG_DARK)
        grid.pack(fill="both", expand=True, padx=25, pady=8)
        grid.columnconfigure(0, weight=4)
        grid.columnconfigure(1, weight=6)
        grid.rowconfigure(0, weight=1)
        
        # Left card: Donut chart
        left = tk.Frame(grid, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER_COLOR, bd=0)
        left.grid(row=0, column=0, padx=(0, 8), sticky="nsew")
        
        tk.Label(left, text="전체 파일 유형 점유 비중", font=(FONT_FAMILY, 10, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD).pack(anchor="w", padx=18, pady=(15, 5))
        
        self.canvas = tk.Canvas(left, width=180, height=180, bg=BG_CARD, highlightthickness=0, bd=0)
        self.canvas.pack(pady=5)
        
        # Donut Chart values: Unique (75.5%), Duplicates (12.4%), Other (12.1%)
        box = (10, 10, 170, 170)
        self.canvas.create_arc(box, start=0, extent=271.8, fill=ACCENT_GREEN, outline="")
        self.canvas.create_arc(box, start=271.8, extent=44.6, fill=ACCENT_RED, outline="")
        self.canvas.create_arc(box, start=316.4, extent=43.6, fill=TEXT_MUTED, outline="")
        
        # Center circle
        self.canvas.create_oval(45, 45, 135, 135, fill=BG_CARD, outline="")
        self.canvas.create_text(90, 80, text="2,450장", fill=TEXT_PRIMARY, font=(FONT_FAMILY, 12, "bold"))
        self.canvas.create_text(90, 98, text="총 검사 대상", fill=TEXT_SECONDARY, font=(FONT_FAMILY, 8))
        
        # Legends
        legends = tk.Frame(left, bg=BG_CARD)
        legends.pack(fill="x", padx=20, pady=(5, 15))
        
        self.add_legend(legends, ACCENT_GREEN, "고유 오리지널 (1,850장 / 75.5%)")
        self.add_legend(legends, ACCENT_RED, "중복 감지 대상 (342장 / 12.4%)")
        self.add_legend(legends, TEXT_MUTED, "인덱스 필터 예외 (258장 / 12.1%)")
        
        # Right card: Overview table of sizes
        right = tk.Frame(grid, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER_COLOR, bd=0)
        right.grid(row=0, column=1, padx=(8, 0), sticky="nsew")
        
        tk.Label(right, text="저장용량 낭비 요인 세부 분석", font=(FONT_FAMILY, 10, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD).pack(anchor="w", padx=18, pady=(15, 2))
        tk.Label(right, text="중복 격리로 확보 가능한 공간 및 클러스터 카테고리 정보입니다.", font=(FONT_FAMILY, 8), fg=TEXT_SECONDARY, bg=BG_CARD).pack(anchor="w", padx=18, pady=(0, 10))
        
        # Table listbox or grid of metadata
        metrics_box = tk.Frame(right, bg=BG_DARK, highlightthickness=1, highlightbackground=BORDER_COLOR, bd=0)
        metrics_box.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        
        self.add_metric_row(metrics_box, "✓  바이너리 완전 일치 중복 사진", "154 개 그룹 / 280장", ACCENT_RED)
        self.add_metric_row(metrics_box, "✓  지각 해시 유사 구도 근접 사진", "24 개 그룹 / 62장", ACCENT_YELLOW)
        self.add_metric_row(metrics_box, "✓  고유 원본 대비 저장 낭비 비율", "14.2 % 소모 중", ACCENT_RED)
        self.add_metric_row(metrics_box, "✓  정리 시 즉각 소생 가능한 공간", "1.44 GB (바이너리 격리 기준)", ACCENT_GREEN)
        self.add_metric_row(metrics_box, "✓  예상 작업 스레드 구동 시간", "실시간 (<0.1 초 내외 완료)", TEXT_SECONDARY)
        
        # Action Row
        action_row = tk.Frame(self, bg=BG_DARK)
        action_row.pack(fill="x", padx=25, pady=(8, 20))
        
        prev_btn = HoverButton(action_row, text="←  이전 단계", bg=BG_DARK, border_color=BORDER_COLOR, font=(FONT_FAMILY, 9, "bold"), pady=8, width=12, command=self.go_prev)
        prev_btn.pack(side="left")
        
        next_btn = HoverButton(action_row, text="다음 세부 검토 단계로 이동  →", bg=ACCENT_BLUE, active_bg="#1557b0", active_fg="#ffffff", border_color=ACCENT_BLUE, font=(FONT_FAMILY, 9, "bold"), pady=8, fg="#ffffff", command=self.go_next)
        next_btn.pack(side="right")
        
    def add_legend(self, master, color, text):
        frame = tk.Frame(master, bg=BG_CARD, pady=2)
        frame.pack(fill="x", anchor="w")
        sq = tk.Canvas(frame, width=8, height=8, bg=BG_CARD, highlightthickness=0, bd=0)
        sq.pack(side="left", padx=(0, 6))
        sq.create_rectangle(0, 0, 8, 8, fill=color, outline="")
        tk.Label(frame, text=text, font=(FONT_FAMILY, 8), fg=TEXT_SECONDARY, bg=BG_CARD).pack(side="left")
        
    def add_metric_row(self, master, label, val, color):
        row = tk.Frame(master, bg=BG_DARK, pady=10)
        row.pack(fill="x", padx=15)
        tk.Label(row, text=label, font=(FONT_FAMILY, 9), fg=TEXT_SECONDARY, bg=BG_DARK).pack(side="left")
        tk.Label(row, text=val, font=(FONT_MONO, 9, "bold"), fg=color, bg=BG_DARK).pack(side="right")
        
    def go_prev(self):
        self.controller.switch_step(2)
        
    def go_next(self):
        self.controller.mark_complete(3)
        self.controller.switch_step(4)


class WorkspaceStep4(tk.Frame):
    """Step 4 Workspace View: Live Telemetry Dashboard directly integrated with duplicate viewer."""
    def __init__(self, master, controller):
        super().__init__(master, bg=BG_DARK)
        self.controller = controller
        
        # 1. Header
        header = tk.Frame(self, bg=BG_DARK)
        header.pack(fill="x", padx=25, pady=(15, 6))
        
        tk.Label(header, text="WORKSPACE // STEP 4: 사진 메타데이터 스캔 & 검토", font=(FONT_FAMILY, 14, "bold"), fg=TEXT_PRIMARY, bg=BG_DARK).pack(anchor="w")
        tk.Label(header, text="실시간 데이터베이스 캐시 및 원본 분석 매칭 현황을 추적하고 중복 사본을 선별합니다.", font=(FONT_FAMILY, 9), fg=TEXT_SECONDARY, bg=BG_DARK).pack(anchor="w", pady=(2, 0))
        
        # Split layout: Left (Telemetry & Controls + Console Logs), Right (Duplicate Clusters Detail Grid)
        split_layout = tk.Frame(self, bg=BG_DARK)
        split_layout.pack(fill="both", expand=True, padx=25, pady=4)
        split_layout.columnconfigure(0, weight=5) # Telemetry & Console Logs
        split_layout.columnconfigure(1, weight=6) # Clusters detail Treeview
        split_layout.rowconfigure(0, weight=1)
        
        # ==========================================
        # LEFT COLUMN: TELEMETRY & CONSOLE LOGS
        # ==========================================
        left_column = tk.Frame(split_layout, bg=BG_DARK)
        left_column.grid(row=0, column=0, padx=(0, 6), sticky="nsew")
        left_column.rowconfigure(2, weight=1) # Log panel expands
        left_column.columnconfigure(0, weight=1)
        
        # A. Live Telemetry Panel Grid
        telemetry_frame = tk.Frame(left_column, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER_COLOR, bd=0)
        telemetry_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        
        tk.Label(telemetry_frame, text="DAEMON ENGINE LIVE TELEMETRY", font=(FONT_MONO, 8, "bold"), fg=TEXT_SECONDARY, bg=BG_CARD).pack(anchor="w", padx=12, pady=(10, 6))
        
        t_grid = tk.Frame(telemetry_frame, bg=BG_CARD)
        t_grid.pack(fill="x", padx=12, pady=(0, 8))
        t_grid.columnconfigure(0, weight=1)
        t_grid.columnconfigure(1, weight=1)
        
        self.card_speed = TelemetryCard(t_grid, "⚡ 속도 (Speed)", "대기 중", "초당 스캔 파일 수")
        self.card_speed.grid(row=0, column=0, padx=(0, 4), pady=(0, 4), sticky="ew")
        
        self.card_eta = TelemetryCard(t_grid, "⏱️ 남은 시간 (ETA)", "--:--:--", "시뮬레이션 진행 시간")
        self.card_eta.grid(row=0, column=1, padx=(4, 0), pady=(0, 4), sticky="ew")
        
        self.card_extrap = TelemetryCard(t_grid, "📈 50만 장 예측 (500k)", "계산 대기 중", "대용량 보정 예측")
        self.card_extrap.grid(row=1, column=0, padx=(0, 4), pady=0, sticky="ew")
        
        self.card_cache = TelemetryCard(t_grid, "💾 캐시 적중률", "0.0%", "로컬 DB 히트 비율")
        self.card_cache.grid(row=1, column=1, padx=(4, 0), pady=0, sticky="ew")
        
        # B. Progress & Simulation Actions Card
        actions_frame = tk.Frame(left_column, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER_COLOR, bd=0)
        actions_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        
        progress_row = tk.Frame(actions_frame, bg=BG_CARD)
        progress_row.pack(fill="x", padx=14, pady=(10, 4))
        
        self.status_lbl = tk.Label(progress_row, text="IDLE (스캔 대기 중)", font=(FONT_FAMILY, 8, "bold"), fg=TEXT_MUTED, bg=BG_CARD)
        self.status_lbl.pack(side="left")
        
        self.percent_lbl = tk.Label(progress_row, text="0 / 2,000 (0.0%)", font=(FONT_MONO, 8, "bold"), fg=ACCENT_BLUE, bg=BG_CARD)
        self.percent_lbl.pack(side="right")
        
        self.prog_bar = CustomProgressBar(actions_frame, fill_color=ACCENT_BLUE)
        self.prog_bar.pack(fill="x", padx=14, pady=(0, 10))
        
        buttons_row = tk.Frame(actions_frame, bg=BG_CARD)
        buttons_row.pack(fill="x", padx=14, pady=(0, 12))
        buttons_row.columnconfigure(0, weight=1)
        buttons_row.columnconfigure(1, weight=1)
        
        self.sim_btn = HoverButton(
            buttons_row, text="▶  시뮬레이션 실행", bg=ACCENT_BLUE, active_bg="#1557b0",
            active_fg="#ffffff", border_color=ACCENT_BLUE, font=(FONT_FAMILY, 9, "bold"), pady=6, fg="#ffffff", command=self.controller.start_simulation
        )
        self.sim_btn.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        
        self.cache_btn = HoverButton(
            buttons_row, text="🗑  데이터베이스 캐시 삭제", bg=BG_DARK, active_bg=ACCENT_RED,
            active_fg="#ffffff", border_color=BORDER_COLOR, font=(FONT_FAMILY, 9, "bold"), pady=6, command=self.controller.clear_cache
        )
        self.cache_btn.grid(row=0, column=1, padx=(4, 0), sticky="ew")
        
        # C. Scrolling Console Log Window
        console_frame = tk.Frame(left_column, bg="#1a1b1e", highlightthickness=1, highlightbackground=BORDER_COLOR, bd=0)
        console_frame.grid(row=2, column=0, sticky="nsew")
        console_frame.rowconfigure(1, weight=1)
        console_frame.columnconfigure(0, weight=1)
        
        tk.Label(console_frame, text="DAEMON ANALYSIS CONSOLE LOG", font=(FONT_MONO, 8, "bold"), fg=TEXT_SECONDARY, bg="#1a1b1e").grid(row=0, column=0, sticky="w", padx=12, pady=(8, 4))
        
        self.console_text = tk.Text(
            console_frame, bg="#1a1b1e", fg=TEXT_PRIMARY, insertbackground=TEXT_PRIMARY, bd=0, relief="flat",
            font=(FONT_MONO, 8), state="disabled", wrap="word"
        )
        self.console_text.grid(row=1, column=0, sticky="nsew", padx=(12, 0), pady=(0, 10))
        
        c_scroll = ttk.Scrollbar(console_frame, orient="vertical", command=self.console_text.yview)
        self.console_text.configure(yscrollcommand=c_scroll.set)
        c_scroll.grid(row=1, column=1, sticky="ns", pady=(0, 10))
        
        # Tag configuration (strictly using standard foreground parameters)
        self.console_text.tag_config("info", foreground="#8ab4f8")
        self.console_text.tag_config("miss", foreground=ACCENT_RED)
        self.console_text.tag_config("hit", foreground="#81c784")
        self.console_text.tag_config("success", foreground="#ffffff", background=ACCENT_GREEN)
        self.console_text.tag_config("system", foreground=ACCENT_YELLOW)
        
        # ==========================================
        # RIGHT COLUMN: DUPLICATE CLUSTERS DETAIL
        # ==========================================
        right_column = tk.Frame(split_layout, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER_COLOR, bd=0)
        right_column.grid(row=0, column=1, padx=(6, 0), sticky="nsew")
        right_column.rowconfigure(2, weight=1)
        right_column.columnconfigure(0, weight=1)
        
        tk.Label(right_column, text="EXIF DUPLICATE CLUSTERS ANALYSIS", font=(FONT_FAMILY, 9, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))
        
        # Top Cluster Selector list
        self.clusters_container = tk.Frame(right_column, bg=BG_DARK, highlightthickness=1, highlightbackground=BORDER_COLOR)
        self.clusters_container.grid(row=1, column=0, sticky="ew", padx=14, pady=4)
        
        self.cluster_buttons = []
        clusters_definitions = [
            (1, "Cluster #01 (3 duplicates)", ACCENT_RED),
            (2, "Cluster #02 (2 duplicates)", ACCENT_RED),
            (3, "Cluster #03 (4 duplicates)", ACCENT_YELLOW),
            (4, "Cluster #04 (2 duplicates)", ACCENT_RED),
            (5, "Cluster #05 (2 duplicates)", TEXT_MUTED)
        ]
        
        for idx, (c_id, title, color) in enumerate(clusters_definitions):
            c_frame = tk.Frame(self.clusters_container, bg=BG_DARK, height=28, cursor="hand2")
            c_frame.pack(fill="x", side="top", pady=1)
            c_frame.grid_propagate(False)
            
            lbl_dot = tk.Label(c_frame, text="■", font=(FONT_FAMILY, 8), fg=color, bg=BG_DARK)
            lbl_dot.pack(side="left", padx=(10, 5))
            
            lbl_txt = tk.Label(c_frame, text=title, font=(FONT_FAMILY, 8), fg=TEXT_PRIMARY, bg=BG_DARK, anchor="w")
            lbl_txt.pack(side="left", fill="both", expand=True)
            
            # Bind click
            c_frame.bind("<Button-1>", lambda e, cid=c_id: self.select_cluster(cid))
            lbl_txt.bind("<Button-1>", lambda e, cid=c_id: self.select_cluster(cid))
            
            self.cluster_buttons.append((c_id, c_frame, lbl_txt))
            
        # Middle Detailed Treeview
        tree_frame = tk.Frame(right_column, bg=BG_CARD)
        tree_frame.grid(row=2, column=0, sticky="nsew", padx=14, pady=4)
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        
        cols = ("name", "sim", "size", "path")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("name", text="파일명")
        self.tree.heading("sim", text="유사도")
        self.tree.heading("size", text="파일 크기")
        self.tree.heading("path", text="로컬 전체 저장 경로")
        
        self.tree.column("name", width=105, anchor="w")
        self.tree.column("sim", width=65, anchor="center")
        self.tree.column("size", width=75, anchor="e")
        self.tree.column("path", width=180, anchor="w")
        
        self.tree.grid(row=0, column=0, sticky="nsew")
        
        t_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=t_scroll.set)
        t_scroll.grid(row=0, column=1, sticky="ns")
        
        # Table action controls
        tbl_controls = tk.Frame(right_column, bg=BG_CARD)
        tbl_controls.grid(row=3, column=0, sticky="ew", padx=14, pady=(6, 12))
        
        btn_chk = HoverButton(tbl_controls, text="✓ 원본 유지 사본 자동 선택", bg=BG_DARK, active_bg=ACCENT_BLUE, active_fg="#ffffff", font=(FONT_FAMILY, 8, "bold"), padx=10, pady=5, command=self.auto_select)
        btn_chk.pack(side="left", padx=(0, 6))
        
        btn_del = HoverButton(tbl_controls, text="🗑 선택 중복 사본 수동 삭제", bg=BG_DARK, active_bg=ACCENT_RED, active_fg="#ffffff", font=(FONT_FAMILY, 8, "bold"), padx=10, pady=5, command=self.manual_delete)
        btn_del.pack(side="left")
        
        # Populate Cluster 1 details by default
        self.select_cluster(1)
        
        # Action Row
        action_row = tk.Frame(self, bg=BG_DARK)
        action_row.pack(fill="x", padx=25, pady=(8, 12))
        
        prev_btn = HoverButton(action_row, text="←  이전 단계", bg=BG_DARK, border_color=BORDER_COLOR, font=(FONT_FAMILY, 9, "bold"), pady=8, width=12, command=self.go_prev)
        prev_btn.pack(side="left")
        
        self.next_btn = HoverButton(action_row, text="다음 단계로 이동  →", bg=BG_DARK, border_color=BORDER_COLOR, font=(FONT_FAMILY, 9, "bold"), pady=8, fg=TEXT_MUTED, command=self.go_next)
        self.next_btn.pack(side="right")
        
        # Log initial console startup
        self.append_log("Daemon Engine telemetry pipeline ready.", "system")
        self.append_log("SQLite database indexing connection successful.", "info")
        
    def select_cluster(self, cluster_id):
        # Update left list visual states
        for c_id, frame, label in self.cluster_buttons:
            if c_id == cluster_id:
                frame.config(bg="#1a3b5c")  # Subtle premium dark blue selected background
                label.config(bg="#1a3b5c", font=(FONT_FAMILY, 8, "bold"), fg="#8ab4f8") # Soft blue text
            else:
                frame.config(bg=BG_DARK)
                label.config(bg=BG_DARK, font=(FONT_FAMILY, 8, "normal"), fg=TEXT_PRIMARY)
                
        # Clear treeview
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        # Add details based on cluster ID
        if cluster_id == 1:
            data = [
                ("DSC_0124.jpg", "오리지널", "4.24 MB", "D:\\work\\prj\\photos\\travel\\"),
                ("DSC_0124_dup.jpg", "100.0%", "4.24 MB", "D:\\work\\prj\\photos\\travel\\europe\\"),
                ("DSC_0124_copy.jpg", "100.0%", "4.24 MB", "D:\\work\\prj\\photos\\backup\\")
            ]
        elif cluster_id == 2:
            data = [
                ("IMG_2024_0211.jpg", "오리지널", "2.85 MB", "D:\\work\\prj\\photos\\family\\"),
                ("IMG_2024_0211_edit.jpg", "98.5%", "2.81 MB", "D:\\work\\prj\\photos\\family\\winter\\")
            ]
        elif cluster_id == 3:
            data = [
                ("screenshot_01.png", "오리지널", "1.12 MB", "D:\\work\\prj\\photos\\work\\"),
                ("screenshot_01_alt.png", "100.0%", "1.12 MB", "D:\\work\\prj\\photos\\work\\capture\\"),
                ("screenshot_01_old.png", "100.0%", "1.12 MB", "D:\\work\\prj\\photos\\trash\\"),
                ("screenshot_01_v2.png", "100.0%", "1.12 MB", "D:\\work\\prj\\photos\\archive\\")
            ]
        elif cluster_id == 4:
            data = [
                ("GOPR5240.jpg", "오리지널", "6.51 MB", "D:\\work\\prj\\photos\\sports\\"),
                ("GOPR5240_copy.jpg", "99.1%", "6.51 MB", "D:\\work\\prj\\photos\\sports\\hike\\")
            ]
        else:
            data = [
                ("IMG_9999.jpg", "오리지널", "3.02 MB", "D:\\work\\prj\\photos\\legacy2\\"),
                ("IMG_9999_dup.jpg", "100.0%", "3.02 MB", "D:\\work\\prj\\photos\\legacy2\\temp\\")
            ]
            
        for idx, row in enumerate(data):
            tag = "even" if idx % 2 == 0 else "odd"
            self.tree.insert("", "end", values=row, tags=(tag,))
            
        self.tree.tag_configure("even", background="#2d2f31")
        self.tree.tag_configure("odd", background="#242528")
        
    def auto_select(self):
        self.controller.show_notification("각 중복 그룹 사본 9개가 자동 분석 지정되었습니다.")
        # Programmatically highlight duplicate items in treeview
        for item in self.tree.get_children():
            values = self.tree.item(item, 'values')
            if values[1] != "오리지널":
                self.tree.selection_set(item)
                
    def manual_delete(self):
        selected = self.tree.selection()
        if not selected:
            self.controller.show_notification("수동 삭제 처리할 중복 사본 항목을 선택하세요.", is_success=False)
            return
            
        for item in selected:
            vals = self.tree.item(item, 'values')
            if vals[1] == "오리지널":
                self.controller.show_notification("원본 원 파일은 보안 보호 규칙에 의해 삭제할 수 없습니다.", is_success=False)
                return
            self.tree.delete(item)
            self.controller.show_notification(f"격리 제거 완료: {vals[0]}")
            
    def update_navigation(self, simulation_completed):
        """Allows transitioning once a full telemetry/simulation scan validates telemetry."""
        if simulation_completed:
            self.next_btn.config(bg=ACCENT_BLUE, active_bg="#1557b0", active_fg="#ffffff", border_color=ACCENT_BLUE, fg="#ffffff")
        else:
            self.next_btn.config(bg=BG_DARK, active_bg=BORDER_COLOR, border_color=BORDER_COLOR, fg=TEXT_MUTED)

    def append_log(self, text, tag="info"):
        self.console_text.config(state="normal")
        stamp = time.strftime("[%H:%M:%S] ")
        self.console_text.insert(tk.END, stamp, "system")
        self.console_text.insert(tk.END, text + "\n", tag)
        self.console_text.see(tk.END)
        self.console_text.config(state="disabled")

    def go_prev(self):
        self.controller.switch_step(3)
        
    def go_next(self):
        # Enable bypassing restriction if simulation was already completed
        if not self.controller.is_simulation_finished:
            self.controller.show_notification("Step 4 내에서 '시뮬레이션 실행'을 구동하여 통계를 인덱싱하세요.", is_success=False)
            return
        self.controller.mark_complete(4)
        self.controller.switch_step(5)


class WorkspaceStep5(tk.Frame):
    """Step 5 Workspace View: Planned execution & Final glowing big button."""
    def __init__(self, master, controller):
        super().__init__(master, bg=BG_DARK)
        self.controller = controller
        
        # 1. Header
        header = tk.Frame(self, bg=BG_DARK)
        header.pack(fill="x", padx=25, pady=(20, 12))
        
        tk.Label(header, text="WORKSPACE // STEP 5: 최종 분류 배치 실행", font=(FONT_FAMILY, 14, "bold"), fg=TEXT_PRIMARY, bg=BG_DARK).pack(anchor="w")
        tk.Label(header, text="메타데이터 가공 및 캐싱 분석이 완료되었습니다. 최종 배치를 트리거합니다.", font=(FONT_FAMILY, 9), fg=TEXT_SECONDARY, bg=BG_DARK).pack(anchor="w", pady=(3, 0))
        
        grid = tk.Frame(self, bg=BG_DARK)
        grid.pack(fill="both", expand=True, padx=25, pady=8)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        grid.rowconfigure(0, weight=1)
        
        # Left card
        left = tk.Frame(grid, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER_COLOR, bd=0)
        left.grid(row=0, column=0, padx=(0, 8), sticky="nsew")
        
        tk.Label(left, text="완료 예정 정리 개요 요약", font=(FONT_FAMILY, 10, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD).pack(anchor="w", padx=18, pady=(15, 12))
        self.add_bullet(left, "✓  대상 타겟: D:\\work\\prj\\photos (감지됨)")
        self.add_bullet(left, "✓  총 검출 고유 원본: 1,850 개 (EXIF 정보 매칭 완료)")
        self.add_bullet(left, "✓  중복 제거 지정 파일: 342 장 (아카이브로 자동 백업)")
        self.add_bullet(left, "✓  확보 예정 여유 드라이브 공간: 1.44 GB")
        self.add_bullet(left, "✓  데이터베이스 캐시 성능: EXIF 매칭 적중률 50.0% 검증")
        
        # Right card
        right = tk.Frame(grid, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER_COLOR, bd=0)
        right.grid(row=0, column=1, padx=(8, 0), sticky="nsew")
        
        tk.Label(right, text="출력 파일명 폴더 레이아웃 유형", font=(FONT_FAMILY, 10, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD).pack(anchor="w", padx=18, pady=(15, 12))
        
        self.layout_var = tk.IntVar(value=1)
        tk.Radiobutton(
            right, text=" 연도-월 연대순 분류 형식 (예: /2026/05/DSC_0001.jpg)", variable=self.layout_var, value=1,
            bg=BG_CARD, fg=TEXT_PRIMARY, selectcolor=BG_DARK, activebackground=BG_CARD, activeforeground=TEXT_PRIMARY,
            font=(FONT_FAMILY, 9), bd=0
        ).pack(anchor="w", padx=18, pady=5)
        
        tk.Radiobutton(
            right, text="  카메라 제작 기종별 분류 형식 (예: /ILCE-7M4/DSC_0001.jpg)", variable=self.layout_var, value=2,
            bg=BG_CARD, fg=TEXT_PRIMARY, selectcolor=BG_DARK, activebackground=BG_CARD, activeforeground=TEXT_PRIMARY,
            font=(FONT_FAMILY, 9), bd=0
        ).pack(anchor="w", padx=18, pady=5)
        
        tk.Radiobutton(
            right, text="  원본 물리 배치 유지 및 사본 백업 폴더 이격 격리", variable=self.layout_var, value=3,
            bg=BG_CARD, fg=TEXT_PRIMARY, selectcolor=BG_DARK, activebackground=BG_CARD, activeforeground=TEXT_PRIMARY,
            font=(FONT_FAMILY, 9), bd=0
        ).pack(anchor="w", padx=18, pady=5)
        
        # Huge action button
        tk.Label(right, text="최종 배치 파이프라인 트리거", font=(FONT_FAMILY, 9, "bold"), fg=TEXT_SECONDARY, bg=BG_CARD).pack(anchor="w", padx=18, pady=(20, 5))
        
        run_btn = HoverButton(
            right, text="⚡  최종 파일 정리 시작 (Launch)", bg=ACCENT_GREEN, active_bg="#115e2e", active_fg="#ffffff", border_color=ACCENT_GREEN,
            font=(FONT_FAMILY, 10, "bold"), fg="#ffffff", padx=20, pady=12, command=self.run_process
        )
        run_btn.pack(fill="x", padx=18, pady=(0, 15))
        
        # Action Row
        action_row = tk.Frame(self, bg=BG_DARK)
        action_row.pack(fill="x", padx=25, pady=(8, 20))
        
        prev_btn = HoverButton(action_row, text="←  이전 단계", bg=BG_DARK, border_color=BORDER_COLOR, font=(FONT_FAMILY, 9, "bold"), pady=8, width=12, command=self.go_prev)
        prev_btn.pack(side="left")
        
    def add_bullet(self, master, text):
        lbl = tk.Label(master, text=text, font=(FONT_FAMILY, 9), fg=TEXT_PRIMARY, bg=BG_CARD, anchor="w")
        lbl.pack(anchor="w", padx=22, pady=6)
        
    def go_prev(self):
        self.controller.switch_step(4)
        
    def run_process(self):
        self.controller.show_overlay()


# ==============================================================================
# 4. CORE MAIN APPLICATION ORCHESTRATOR
# ==============================================================================

class PhotosApp(tk.Tk):
    def __init__(self):
        super().__init__()
        
        # Global properties
        self.title("Smart Photo Organizer // Premium Charcoal Dark UI")
        self.geometry("1180x780")
        self.configure(bg=BG_DARK)
        self.minsize(1120, 720)
        
        # Style option database settings for professional dark widgets
        self.option_add("*TCombobox*Listbox.background", BG_CARD)
        self.option_add("*TCombobox*Listbox.foreground", TEXT_PRIMARY)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT_BLUE)
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.option_add("*TCombobox*Listbox.font", (FONT_FAMILY, 9))
        
        # Global ttk Style configuration
        self.style = ttk.Style()
        self.style.theme_use('clam')  # Clam theme is highly customizable for dark widgets
        
        # Configure TCombobox
        self.style.configure("TCombobox", 
                        fieldbackground=BG_CARD, 
                        background=BG_DARK, 
                        foreground=TEXT_PRIMARY, 
                        bordercolor=BORDER_COLOR, 
                        arrowcolor=TEXT_PRIMARY)
        
        # Configure Treeview
        self.style.configure("Treeview", 
                        background=BG_CARD, 
                        foreground=TEXT_PRIMARY, 
                        fieldbackground=BG_CARD, 
                        rowheight=26, 
                        borderwidth=0,
                        font=(FONT_FAMILY, 8))
        self.style.map("Treeview", 
                  background=[('selected', '#1a3b5c')], 
                  foreground=[('selected', '#ffffff')])
                  
        self.style.configure("Treeview.Heading",
                        background=BG_DARK,
                        foreground=TEXT_PRIMARY,
                        relief="flat",
                        font=(FONT_FAMILY, 8, "bold"))
        self.style.map("Treeview.Heading",
                  background=[('active', '#3c4043')],
                  foreground=[('active', TEXT_PRIMARY)])
                  
        # Configure TScrollbar
        self.style.configure("TScrollbar",
                        background=BG_DARK,
                        troughcolor=BG_DARK,
                        bordercolor=BORDER_COLOR,
                        arrowcolor=TEXT_SECONDARY)
        
        self.queue = queue.Queue()
        self.simulation_running = False
        self.is_simulation_finished = False
        self.led_state = False
        self.active_step = 1
        
        # Double pane design layout: Left fixed panel (340px), Right dynamic panel
        self.columnconfigure(0, weight=0)  # Left fixed
        self.columnconfigure(1, weight=1)  # Right expanding
        self.rowconfigure(0, weight=1)
        
        # Left Panel (Fixed Width 340px)
        self.left_pane = tk.Frame(self, width=340, bg=BG_SIDEBAR)
        self.left_pane.grid(row=0, column=0, sticky="ns")
        self.left_pane.grid_propagate(False)
        
        # Left Row 0: Header with title 'PHOTOS ORGANIZER // WIZARD UI' and pulsing emerald indicator
        header_frame = tk.Frame(self.left_pane, bg=BG_SIDEBAR, height=60)
        header_frame.pack(fill="x", padx=16, pady=(18, 10))
        
        # Emerald status indicator LED
        self.led_canvas = tk.Canvas(header_frame, width=12, height=12, bg=BG_SIDEBAR, highlightthickness=0, bd=0)
        self.led_canvas.pack(side="left", padx=(2, 6))
        self.led_dot = self.led_canvas.create_oval(1, 1, 11, 11, fill=ACCENT_GREEN, outline="")
        
        tk.Label(header_frame, text="PHOTOS ORGANIZER // WIZARD UI", font=(FONT_MONO, 9, "bold"), fg=TEXT_PRIMARY, bg=BG_SIDEBAR).pack(side="left")
        
        # Start LED pulsing background
        self.pulse_led()
        
        # Divider
        h_line = tk.Frame(self.left_pane, height=1, bg=BORDER_COLOR, width=300)
        h_line.pack(fill="x", padx=16, pady=(0, 10))
        
        # Left Row 1: Steps 1-5 Compact vertical Timeline
        self.steps_container = tk.Frame(self.left_pane, bg=BG_SIDEBAR)
        self.steps_container.pack(fill="x", padx=16)
        
        self.sidebar_steps = {}
        steps_definitions = [
            (1, "대상 디렉토리 소스 설정"),
            (2, "바이너리/유사 필터링 규칙"),
            (3, "중복 통계 대시보드 리포트"),
            (4, "사진 메타데이터 분석"),
            (5, "최종 정리 가동 및 분류")
        ]
        
        for idx, (num, label) in enumerate(steps_definitions):
            init_status = "pending"
            if num == 1:
                init_status = "active"
                
            step_w = SidebarStep(
                self.steps_container, 
                step_num=num, 
                title=label, 
                initial_status=init_status, 
                command=self.switch_step
            )
            step_w.pack(fill="x", side="top", pady=1)
            self.sidebar_steps[num] = step_w
            
        # Left Row 2: Guide Card
        guide_frame = tk.Frame(self.left_pane, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER_COLOR, bd=0)
        guide_frame.pack(fill="both", expand=True, padx=16, pady=(20, 15))
        
        tk.Label(guide_frame, text="WIZARD WORKFLOW GUIDE", font=(FONT_MONO, 8, "bold"), fg=ACCENT_BLUE, bg=BG_CARD).pack(anchor="w", padx=12, pady=(12, 6))
        
        guide_text = (
            "본 마법사 보드는 5단계 인덱싱 분류 절차를 안내합니다.\n\n"
            "• Step 1: 디렉토리를 로드하여 스캔 대상 설정.\n\n"
            "• Step 2: 판단 알고리즘 및 민감도 유사 가동 필터 셋업.\n\n"
            "• Step 3: 중복 분포 비중 Donut Chart 분석 리포트 확인.\n\n"
            "• Step 4: 메타데이터 라이브 캐싱 시뮬레이션 및 중복 클러스터의 디테일 검수 실행.\n\n"
            "• Step 5: 파일 자동 격리 정리 최종 배치 가동."
        )
        
        lbl_guide = tk.Label(guide_frame, text=guide_text, font=(FONT_FAMILY, 8), fg=TEXT_SECONDARY, bg=BG_CARD, justify="left", wraplength=280, anchor="nw")
        lbl_guide.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        
        # Right Workspace Container Frame
        self.right_pane = tk.Frame(self, bg=BG_DARK)
        self.right_pane.grid(row=0, column=1, sticky="nsew")
        self.right_pane.columnconfigure(0, weight=1)
        self.right_pane.rowconfigure(0, weight=1)
        
        # Swappable frames
        self.frames = {
            1: WorkspaceStep1(self.right_pane, self),
            2: WorkspaceStep2(self.right_pane, self),
            3: WorkspaceStep3(self.right_pane, self),
            4: WorkspaceStep4(self.right_pane, self),
            5: WorkspaceStep5(self.right_pane, self)
        }
        
        for f in self.frames.values():
            f.grid(row=0, column=0, sticky="nsew")
            
        self.switch_step(1)
        
        # Overlay completed popup
        self.overlay = None
        
        # Launch queue daemon checker loop
        self.check_queue()
        
        # Bind cleanup on window close
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def pulse_led(self):
        """Creates a modern pulsing green light effect in the daemon header."""
        self.led_state = not self.led_state
        color = ACCENT_GREEN if self.led_state else "#81c784"
        self.led_canvas.itemconfig(self.led_dot, fill=color)
        self.after(800, self.pulse_led)

    def switch_step(self, step_num):
        self.active_step = step_num
        self.frames[step_num].lift()
        
        for num, step_widget in self.sidebar_steps.items():
            step_widget.set_active(num == step_num)
            
        for num, step_widget in self.sidebar_steps.items():
            if num < step_num:
                step_widget.set_status("completed")
            elif num == step_num:
                step_widget.set_status("active")
            elif num > step_num:
                if step_widget.status == "completed":
                    pass
                else:
                    step_widget.set_status("pending")

    def mark_complete(self, step_num):
        self.sidebar_steps[step_num].set_status("completed")

    def show_notification(self, message, is_success=True):
        toast = tk.Frame(
            self, 
            bg=BG_CARD, 
            highlightthickness=1, 
            highlightbackground=ACCENT_GREEN if is_success else ACCENT_RED, 
            bd=0
        )
        toast.place(relx=1.0, rely=0.0, anchor="ne", x=-20, y=20)
        
        lbl = tk.Label(toast, text=message, fg=TEXT_PRIMARY, bg=BG_CARD, font=(FONT_FAMILY, 9, "bold"), padx=16, pady=10)
        lbl.pack()
        self.after(3000, toast.destroy)

    def check_queue(self):
        try:
            while True:
                msg_type, data = self.queue.get_nowait()
                if msg_type == "log":
                    self.frames[4].append_log(data[0], data[1])
                elif msg_type == "progress":
                    self.update_telemetry_ui(data)
                elif msg_type == "complete":
                    self.simulation_complete()
                self.queue.task_done()
        except queue.Empty:
            pass
        self.after(40, self.check_queue)

    def update_telemetry_ui(self, data):
        scanned = data["scanned"]
        total = data["total"]
        speed = data["speed"]
        hits = data["hits"]
        phase = data["phase"]
        
        frac = scanned / total
        step4 = self.frames[4]
        step4.prog_bar.set_progress(frac)
        step4.percent_lbl.config(text=f"{scanned:,} / {total:,} ({frac*100:.1f}%)")
        
        if phase == "miss":
            step4.status_lbl.config(text="SCANNING: Phase 1 Exif parsing...", fg=ACCENT_BLUE)
            step4.prog_bar.fill_color = ACCENT_BLUE
            step4.prog_bar.draw_bar()
            
            step4.card_speed.update_telemetry(f"{speed:.1f} f/s", ACCENT_BLUE)
            step4.card_cache.update_telemetry("0.0%", TEXT_SECONDARY, "0 / 1,000 matches")
            
            rem = (total - scanned) / speed if speed > 0 else 0
            step4.card_eta.update_telemetry(f"00:00:{int(rem):02d}", ACCENT_YELLOW)
            
            extrap_h = 500000 / speed / 3600 if speed > 0 else 0
            step4.card_extrap.update_telemetry(f"~{extrap_h:.2f} hours", ACCENT_BLUE, "500k raw parsing est.")
            
        elif phase == "hit":
            step4.status_lbl.config(text="SCANNING: Phase 2 Cache matching...", fg=ACCENT_GREEN)
            step4.prog_bar.fill_color = ACCENT_GREEN
            step4.prog_bar.draw_bar()
            
            step4.card_speed.update_telemetry(f"{speed:,.0f} f/s", ACCENT_GREEN)
            
            hit_rate = (hits / scanned) * 100.0
            step4.card_cache.update_telemetry(f"{hit_rate:.1f}%", ACCENT_GREEN, f"{hits:,} / {scanned:,} hits")
            step4.card_eta.update_telemetry("< 1 second", ACCENT_GREEN)
            
            extrap_s = 500000 / speed if speed > 0 else 0
            step4.card_extrap.update_telemetry(f"~{extrap_s:.1f} seconds", ACCENT_GREEN, "500k cache match est.")

    def start_simulation(self):
        if self.simulation_running:
            self.show_notification("시뮬레이션이 활성화되어 스캔 구동 중입니다.", is_success=False)
            return
            
        self.simulation_running = True
        self.is_simulation_finished = False
        
        step4 = self.frames[4]
        step4.sim_btn.config(state="disabled", text="스캔 진행 중...")
        step4.cache_btn.config(state="disabled")
        
        # Sync navigation block
        step4.update_navigation(False)
        
        step4.append_log("사진 메타데이터 실시간 색인 가동 시작...", "system")
        t = threading.Thread(target=self.run_thread, daemon=True)
        t.start()

    def run_thread(self):
        total = 2000
        scanned = 0
        hits = 0
        
        # Phase 1: 1000 misses at ~80 files/s
        self.queue.put(("log", ("Phase 1 Direct File Disk Scan starting (~80 files/s)...", "system")))
        for step in range(100):
            if not self.simulation_running:
                break
            scanned += 10
            cur_speed = 80.0 + random.uniform(-4.0, 4.0)
            
            prog_data = {
                "scanned": scanned,
                "total": total,
                "speed": cur_speed,
                "hits": 0,
                "phase": "miss"
            }
            self.queue.put(("progress", prog_data))
            
            if step % 10 == 0:
                mock_file = f"IMG_{random.randint(1000, 9999)}.jpg"
                self.queue.put(("log", (f"[MISS] {mock_file} parsed successfully in 12.5ms", "miss")))
            time.sleep(0.12)  # ~80 files/s speed sleep
            
        # Phase 2: 1000 hits at ~10,000 files/s
        if self.simulation_running:
            self.queue.put(("log", ("Phase 2 Database Cache Matching starting (~10,000 files/s)...", "system")))
            for step in range(5):
                if not self.simulation_running:
                    break
                scanned += 200
                hits += 200
                cur_speed = 10000.0 + random.uniform(-400.0, 400.0)
                
                prog_data = {
                    "scanned": scanned,
                    "total": total,
                    "speed": cur_speed,
                    "hits": hits,
                    "phase": "hit"
                }
                self.queue.put(("progress", prog_data))
                self.queue.put(("log", (f"[HIT] Loaded 200 metadata records from SQLite DB Cache", "hit")))
                time.sleep(0.02)
                
        self.queue.put(("complete", None))

    def simulation_complete(self):
        self.simulation_running = False
        self.is_simulation_finished = True
        
        step4 = self.frames[4]
        step4.sim_btn.config(state="normal", text="▶  시뮬레이션 재실행")
        step4.cache_btn.config(state="normal")
        step4.status_lbl.config(text="COMPLETED (색인 완료)", fg=ACCENT_GREEN)
        
        # Unlock Step 4 navigation
        step4.update_navigation(True)
        
        step4.append_log("시뮬레이션 인덱싱 완료: 데이터 검증 필터 합격.", "success")
        self.show_notification("시뮬레이션이 성공적으로 완수되었습니다!", is_success=True)

    def clear_cache(self):
        if self.simulation_running:
            self.show_notification("동작 연산 중에는 캐시를 정리할 수 없습니다.", is_success=False)
            return
            
        step4 = self.frames[4]
        step4.card_speed.update_telemetry("대기 중", ACCENT_BLUE)
        step4.card_eta.update_telemetry("--:--:--", TEXT_SECONDARY)
        step4.card_extrap.update_telemetry("계산 대기 중", TEXT_SECONDARY)
        step4.card_cache.update_telemetry("0.0%", TEXT_SECONDARY, "로컬 DB 히트 비율")
        
        step4.prog_bar.set_progress(0.0)
        step4.percent_lbl.config(text="0 / 2,000 (0.0%)")
        step4.status_lbl.config(text="IDLE (스캔 대기 중)", fg=TEXT_MUTED)
        self.is_simulation_finished = False
        
        # Lock navigation
        step4.update_navigation(False)
        
        step4.append_log("[CLEARED] 로컬 SQLite DB 캐시 파일 인덱스가 안전하게 완전 리셋되었습니다.", "miss")
        self.show_notification("데이터베이스 캐시 비우기 성공!")

    def show_overlay(self):
        """Displays a beautiful popup report showing successfully reorganized structures."""
        self.overlay = tk.Frame(self, bg=BG_DARK)
        self.overlay.place(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)
        
        card = tk.Frame(self.overlay, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER_COLOR, bd=0)
        card.place(relx=0.5, rely=0.5, anchor="center", width=520, height=440)
        
        # Draw success canvas graphics
        canvas = tk.Canvas(card, width=70, height=70, bg=BG_CARD, highlightthickness=0, bd=0)
        canvas.pack(pady=(35, 10))
        canvas.create_oval(4, 4, 66, 66, fill=ACCENT_GREEN, outline="")
        canvas.create_line(22, 35, 32, 45, fill="#ffffff", width=4, capstyle="round")
        canvas.create_line(32, 45, 48, 23, fill="#ffffff", width=4, capstyle="round")
        
        tk.Label(card, text="사진 정리 작업 완전 성료!", font=(FONT_FAMILY, 18, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD).pack(pady=5)
        tk.Label(card, text="인덱스 기반 메타데이터 분류 재배치가 마무리되었습니다.", font=(FONT_FAMILY, 10), fg=TEXT_SECONDARY, bg=BG_CARD).pack(pady=(0, 20))
        
        specs = tk.Frame(card, bg=BG_DARK, highlightthickness=1, highlightbackground=BORDER_COLOR, bd=0)
        specs.pack(fill="x", padx=40, pady=5)
        
        self.add_spec_row(specs, "✓  분류 완료 오리지널 파일 수", "1,850 개", ACCENT_BLUE)
        self.add_spec_row(specs, "✓  격리 수거 완료 사본 파일 수", "342 개", ACCENT_RED)
        self.add_spec_row(specs, "✓  확보 성공 디스크 세이브 용량", "1.44 GB", ACCENT_GREEN)
        self.add_spec_row(specs, "✓  보관 구조 레이아웃 보고서", "report_photo.json", TEXT_SECONDARY)
        
        close_btn = HoverButton(
            card, text="메인 통계 제어 대시보드로 복귀", bg=ACCENT_BLUE, active_bg="#1557b0", active_fg="#ffffff", border_color=ACCENT_BLUE,
            font=(FONT_FAMILY, 10, "bold"), padx=25, pady=8, fg="#ffffff", command=self.close_overlay
        )
        close_btn.pack(pady=(25, 20))
        
    def add_spec_row(self, master, label, val, color):
        row = tk.Frame(master, bg=BG_DARK, pady=6)
        row.pack(fill="x", padx=15)
        tk.Label(row, text=label, font=(FONT_FAMILY, 9), fg=TEXT_SECONDARY, bg=BG_DARK).pack(side="left")
        tk.Label(row, text=val, font=(FONT_MONO, 9, "bold"), fg=color, bg=BG_DARK).pack(side="right")
        
    def close_overlay(self):
        if self.overlay:
            self.overlay.destroy()
            self.overlay = None
            self.switch_step(1)

    def on_closing(self):
        self.simulation_running = False
        self.destroy()

# ==============================================================================
# 5. RUNTIME SCRIPT ENTRY
# ==============================================================================
if __name__ == "__main__":
    try:
        os.makedirs(r"D:\work\prj\photos\scripts", exist_ok=True)
    except Exception:
        pass
        
    app = PhotosApp()
    app.mainloop()
