# Photo Organizer

승인 게이트와 복구 절차를 갖춘 로컬 사진 정리 앱입니다. 기본 GUI는
`photo_organizer_app.py`의 Tkinter 앱이며, 실제 파일 이동은
`PhotoOrganizerService`를 통해서만 실행합니다.

## 실행

소스 체크아웃에서 실행:

```powershell
python .\photo_organizer_app.py
```

개발 설치 또는 wheel 설치 후 실행:

```powershell
python -m photos gui
photo-organizer
photos gui
```

Windows 개발 환경과 검증 명령:

```powershell
.\scripts\setup_windows.ps1
.\scripts\run_windows.ps1 -Gui
.\scripts\verify_windows.ps1
```

`photos gui`, `photo-organizer`, `run_windows.ps1 -Gui`는 모두 같은
`photo_organizer_app.main()`을 실행합니다. Wheel의 GUI를 사용하려면
`photos-triage[gui]`를 설치해 Pillow를 준비하고, Python 자체에 Tkinter 지원이
있어야 합니다.

## 주요 기능

- `1 폴더구조`: 실제 트리 구조로 폴더를 표시하고 정리 대상을 체크/언체크할 수 있습니다.
- `2 용량/종류`: 폴더별 파일 수, 사진 수, 용량, 주요 확장자를 채웁니다.
- `3 날짜근거`: 파일명 날짜, 상위 폴더 날짜, 수정일, 메타(미확인/확인)를 나란히 표시합니다.
- `4 사진스캔`: 체크된 폴더만 대상으로 사진 목록을 만듭니다.
- `정리 계획`: 리스트가 아니라 목표 폴더 트리로 결과를 미리 봅니다.
- `Review 저장`: `D:\PICTURES\_review`에 inventory/audit/draft 파일을 저장합니다.
- `Review 로드`: `codex_review.json`을 읽어 폴더 포함 여부와 분류를 반영합니다.
- `Dry-run`: 실제 이동 전 충돌/제외대상/루트이탈을 검사합니다.
- `.thumbnails`, `$RECYCLE.BIN`, `System Volume Information`, `.tmp`, `OneDriveTemp` 등은 제외 후보로 표시하고 사진 단위 스캔에서 건너뜁니다.
- SHA-256 해시로 완전히 동일한 사진을 찾습니다.
- dHash 이미지 지문으로 밝기 조정, 리사이즈, 가벼운 편집이 들어간 유사 사진을 찾습니다.
- EXIF 촬영일, EXIF 편집/디지털화 일자, 파일명 날짜, 작성일, 수정일 순서로 기준 날짜를 결정합니다.
- 기준 날짜와 위치 정보 유무를 바탕으로 정리 계획을 생성합니다.
- 기본값은 읽기 전용이며, 이 상태에서는 실제 파일 이동이 막힙니다.
- 중복/유사 결과와 정리 계획을 CSV로 저장할 수 있습니다.

## 정리 기준 검토

사진 보관 목적이면 폴더명은 날짜 기반이 가장 안정적입니다.

권장 기본 구조:

```text
정리대상\YYYY\YYYY-MM GPS 또는 NoLocation\파일명
```

장소명은 EXIF GPS 좌표가 있어도 오프라인 상태에서는 실제 주소로 안전하게 변환하기 어렵습니다. 그래서 이 앱은 우선 `GPS` 또는 `NoLocation`만 폴더명에 넣습니다. 실제 여행지/도시명은 정리 후 폴더명을 직접 다듬는 쪽이 안전합니다.

태그는 검색에는 좋지만 파일 시스템만 봐서는 정리 상태가 드러나지 않습니다. 장기 보관은 날짜 폴더를 기준으로 하고, 태그는 보조 메타데이터로 쓰는 방향이 낫습니다.

## 주의

D드라이브 전체 검토는 앱에서 원본을 `D:\`로 두고 읽기 전용을 켠 상태로 진행하세요. 읽기 전용 모드에서는 이동 실행이 차단됩니다.

권장 작업 순서:

1. `1 폴더구조`로 기본 체크 상태를 확인하고 필요시 수정합니다.
2. `2 용량/종류`로 규모를 확인합니다.
3. `3 날짜근거`로 불일치 항목을 확인합니다.
4. `Review 저장` 후 Codex 검수 파일(`codex_review.json`)을 반영하려면 `Review 로드`를 실행합니다.
5. `4 사진스캔` 후 `정리 계획`을 생성합니다.
6. `Dry-run`이 통과하면 결과를 저장하고 충돌/제외/루트이탈 항목을 검토합니다.
7. 원본 드라이브 또는 대상 폴더 백업을 확인한 뒤에만 읽기 전용을 해제합니다.
8. 실제 이동 후 audit/review 산출물을 보관합니다.

## 패키징 경계

- 소스 실행은 저장소의 `vendor\PIL`을 우선 사용하고 `src\photos` 백엔드를
  로드합니다.
- Wheel은 `photo_organizer_app.py`와 `photos` 백엔드를 포함하지만
  `vendor\PIL`은 포함하지 않습니다. GUI extra의 Pillow를 사용합니다.
- `PhotoOrganizer.spec`와 `PhotoOrganizerFast.spec`는 `vendor`와 `src`를
  PyInstaller 분석 경로에 넣습니다. 이 설정은 실행 파일 빌드 입력일 뿐,
  installer, code signing, 실제 Windows 실행 검증을 증명하지 않습니다.
- Termux 검증은 wheel 내용과 비대화형 백엔드 동작만 다룹니다. Windows의
  Tkinter 렌더링/성능, NTFS/exFAT, long path, junction, 권한, RAW/EXIF 도구,
  대용량 하드웨어 처리량은 별도 검증 대상입니다.

## Termux 개발 검증

비대화형 백엔드와 샘플 dry-run은 임시 데이터로 검증합니다:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python scripts/verify_handoff.py
```

임시 소스 추출, 비교, 빌드, 도구 설치는 `TMPDIR` 아래에서 수행합니다.
컴파일/바이트코드 캐시는 `XDG_CACHE_HOME`(기본 `~/.cache`)을 사용합니다.
임시 소스 복사본을 저장소에 남기지 마세요. 과거 소스 복구 방법은
`docs/windows_handoff.md`, 임시 체크아웃의 wheel 빌드는
`docs/large_library_windows_gaps.md`를 참고하세요.
