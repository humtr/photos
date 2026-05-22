# Photo Organizer UI/UX Redesign (Wizard Sidebar Handoff Document)

This repository hosts the core codebase, test suites, and interactive prototypes for the next-generation **Smart Photo Organizer** UI/UX. This document serves as a comprehensive handoff outlining the current status of the redesigned interface (Option B), the visual transition plan, and the build/deployment pipelines.

---

## 1. Redesign Status & Option B (Wizard Sidebar Layout)

We have successfully designed and prototyped the new **Option B: Wizard Sidebar** design concept. The redesign pivots from classical dashboard layouts into a highly guided, 5-stage wizard pipeline. This layout assists the user directly through targeted index, review, and sorting phases.

### The 5 Wizard Steps:
1. **대상 디렉토리 소스 설정 (Step 1)**: Directory browser checklist and targeted folder filtering.
2. **바이너리/유사 필터링 규칙 (Step 2)**: Sensitivities scale controls and custom CPU threat allocation drop-downs.
3. **중복 통계 대시보드 리포트 (Step 3)**: Donut Chart breakdown of wasted storage capacity.
4. **사진 메타데이터 분석 & 검토 (Step 4)**: Live daemon telemetry updates, real-time background threads, scroll logging, and duplicate clusters explorer.
5. **최종 정리 가동 및 분류 (Step 5)**: Sorting layout select and launch, ending in a beautiful glowing complete overlay.

---

## 2. Visual Architecture & Theme Transition Plan

While the initial Tkinter prototype script was implemented in a sleek, high-fidelity dark charcoal theme, the final master interface is planned to transition into a premium, state-of-the-art **Windows 11 Fluent Light Theme** for ultimate office integration and Mica-like silver styling.

### 🎨 Windows 11 Fluent Light Theme Spec Tokens:

| UI Token / Component | Hex Color Value | Application Purpose |
| :--- | :--- | :--- |
| **Main Background** | `#f3f3f3` | Mica-like soft gray main window background |
| **Sidebar Background** | `#f9f9f9` | Fluent off-white tone for left timeline wizard pane |
| **Cards Background** | `#ffffff` | Pure white cards for high readability and contrast |
| **Borders & Grids** | `#e0e0e0` | Subtle, thin light gray separators |
| **Accent Color** | `#0067b8` | Windows 11 Fluent Blue (active buttons, timeline highlights) |
| **Success Color** | `#107c41` | Fluent Green (completed steps, pulsing system LEDs) |
| **Danger / Alert** | `#d13438` | Fluent Red (database cache resets, quarantine alerts) |
| **Primary Text** | `#202020` | High-contrast dark charcoal text for core headers |
| **Secondary Text** | `#5f5f5f` | Muted dark gray for descriptions and secondary text |

---

## 3. Prototype File Structure (`scripts/` Directory)

We have delivered two distinct, high-fidelity, interactive prototypes to fully model option B:

1. **Tkinter UI Prototype (`scripts/ui_prototype.py`)**
   - A standalone, zero-dependency Python script using standard Tkinter libraries only.
   - Currently styled in a premium dark slate/charcoal format, planned to be rewritten to the light theme specified above.
   - Houses the fully functional dual-phase background thread simulator:
     * **Phase 1 (Disk-Reads)**: Processes 1,000 files at **~80 files/sec** with real-time countdown ETA and extrapolates 500k files to **~1.73 hours**.
     * **Phase 2 (Cache-Hits)**: Instantly processes 1,000 files at **~10,000 files/sec** with speed spikes, 50.0% hits, and a 500k extrapolation correction to **~50 seconds**.
   - Contains scroll logging, styled alternate tables, custom canvases, and success overlays.

2. **Web UI Prototype (`scripts/ui_web_prototype.html`)**
   - An interactive HTML5/CSS/JS single-page application demonstrating the exact double-pane split workspace workspace with active animation hooks, timeline clicks, and tabular interactions.

---

## 4. Standalone Compilation & Build Instructions

The prototype has been designed to compile cleanly into a single-file executable for standalone testing on standard Windows environments without requiring python-dev dependencies.

### Compilation Steps:
1. Ensure your PowerShell window is opened inside the root workspace folder `D:\work\prj\photos`.
2. Run the PyInstaller command within the local virtual environment:
   ```powershell
   .\.venv\Scripts\pyinstaller.exe --noconfirm .\UIPrototype.spec
   ```
3. PyInstaller will parse the spec file, build the CArchive package (`UIPrototype.pkg`), and output the final, standalone executable directly to:
   - **`D:\work\prj\photos\dist\UIPrototype.exe`**
