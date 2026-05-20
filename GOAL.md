# Photo Organizer GOAL

## Objective

Windows에서 바로 실행 가능한 GUI 앱으로 D드라이브에 흩어진 사진을 먼저 폴더 구조 기준으로 파악하고, 사용자가 정리 대상을 직접 확정한 뒤, `D:\PICTURES` 아래로 검증 가능한 계획에 따라 정리한다.

이 앱은 단순 중복 사진 탐지기가 아니다. 50만 개 안팎의 파일이 있는 드라이브를 감당해야 하므로, 느린 작업을 처음부터 모두 실행하지 않고 다음 순서로 나눈다.

1. 폴더 구조와 제외 후보 파악
2. 폴더별 용량, 파일 수, 사진 수, 확장자 종류 파악
3. 파일명, 상위 폴더명, 파일 시스템 날짜의 불일치 파악
4. 선택된 폴더에 한해 사진 메타데이터와 정리 계획 생성
5. 필요할 때만 중복/유사 사진 분석
6. Review 저장, Codex 검수, Review 로드, Dry-run, 실제 이동

기본 원칙은 `읽기 전용 우선`, `D:\PICTURES 외부로 이동 금지`, `계획 파일 저장 필수`, `Dry-run 통과 후 실행`이다.

## Current Implementation Snapshot

현재 핵심 앱 파일은 `photo_organizer_app.py`이고, 실행 파일 산출물은 `dist\PhotoOrganizer.exe`이다. 개발용 실행은 `run.bat` 또는 `python .\photo_organizer_app.py`를 사용한다.

현재 GUI 상단 동작 버튼:

- `1 구조 개요`
- `2 폴더 상세 구조`
- `3 날짜 근거`
- `4 사진 메타데이터`
- `5 파일명 중복검사`
- `Review 저장`
- `Review 로드`
- `Dry-run`
- `중지`

현재 주요 탭:

- `폴더 구조`
- `날짜 근거`
- `사진 목록`
- `중복/유사 사진`
- `정리 계획`
- `정리 기준`

현재 기본값:

- 원본 루트: `D:\`
- 정리 루트: `D:\PICTURES`
- 읽기 전용: ON
- 중복/유사 임계값: 10
- 정리 모드: `year_month_place`
- 정리 스키마: `year_month_event`

## Implemented Trajectory

### 1. Folder-First Workflow

현재 앱은 사진 전체 목록을 먼저 UI에 밀어 넣지 않고, 폴더 구조를 먼저 파악하는 방향으로 바뀌었다.

폴더 구조 탭은 3개 패널로 구성한다.

- 왼쪽: 전체 폴더 트리
- 가운데: 정리 대상으로 체크된 폴더 요약 트리
- 오른쪽: 정리하지 않을 폴더 요약 트리

폴더 행에는 다음 정보를 표시한다.

- 분류
- 하위 폴더 수
- 파일 수
- 사진 수
- 용량
- 주요 확장자 종류
- 검수 상태

체크 상태는 GUI용 이미지 아이콘과 행 배경색으로 표시한다.

- 선택: 초록 체크
- 일부 선택: 주황 부분 표시
- 미선택: 회색 빈 체크

부모 폴더 체크/언체크는 하위 폴더에 전파된다. 하위 상태가 섞이면 부모는 부분 선택으로 표시한다. 폴더 펼침 `+` 클릭은 체크 상태를 바꾸지 않도록 분리했다.

오른쪽/가운데 요약 패널에서도 아이콘 클릭으로 빠르게 포함/제외를 전환할 수 있다. 이때 왼쪽 트리의 펼침 상태와 선택 상태를 최대한 보존한다.

우클릭 편의 기능:

- 탐색기에서 열기
- 왼쪽 패널로 포커스
- 정리 대상 포함
- 정리 대상 제외
- 하위 전체 포함
- 하위 전체 제외
- 경로 복사

### 2. Exclusion and Classification Rules

현재 제외 또는 주의 분류 규칙은 코드에 반영되어 있다.

제외 후보:

- `.thumbnails`
- `$RECYCLE.BIN`
- `System Volume Information`
- `OneDriveTemp`
- `.tmp` 계열 경로

클라우드/동기화 후보:

- `Google Photos`
- `Samsung Gallery`
- `OneDrive`

기본 포함 후보:

- `HYEJIN`
- `!이안`
- `휴대폰 백업`
- `돌사진 원본`
- `잔PC 바탕화면`
- `FUJI`
- `DCIM`
- `Camera`

클라우드/동기화와 캐시성 폴더는 기본적으로 정리 대상에서 제외하는 방향이 맞다. 단, 사용자가 명시적으로 포함시킬 수 있어야 한다.

### 3. Performance Direction

50만 개 파일 규모에서는 모든 파일을 한 번에 세밀 분석하면 UI가 느려진다. 그래서 현재 구현은 다음 식으로 나뉘었다.

- 구조/용량/종류: `os.scandir` 기반으로 폴더 단위 통계를 빠르게 만든다.
- 날짜 근거: 기본적으로 EXIF를 열지 않고 파일명, 상위 폴더명, 수정일만 본다.
- 사진 메타데이터: 체크된 폴더만 대상으로 EXIF를 열어 보강한다.
- 중복/유사 분석: 별도 버튼으로 분리한다.
- 파일명 중복검사: 5번 버튼으로 빠르게 수행한다.

사진 목록 탭은 전체 50만 행을 모두 표시하지 않고 최근 스캔 미리보기 최대 1,000개만 보여준다. 전체 결과는 메모리에 보관하고 정리 계획과 저장 파일에 반영한다.

정리 계획 트리는 표시 건수가 많을 수 있으므로 미리보기 상한을 둔다.

### 4. Date Evidence Flow

현재 날짜 근거 탭은 다음 값을 나란히 표시한다.

- 파일명 날짜
- 상위 폴더 날짜
- 파일 시스템 수정일
- 메타데이터 날짜
- 상태
- 파일 경로

현재 `3 날짜 근거`는 기본적으로 메타데이터를 열지 않는다. 메타데이터 날짜는 `4 사진 메타데이터`에서 보강한다.

날짜 판단 방향:

1. 사진 메타데이터 촬영일
2. 파일명 날짜
3. 상위 폴더명 날짜
4. 파일 시스템 수정일
5. 파일 시스템 작성일

현재 코드에는 빠른 날짜 판단과 EXIF 기반 판단이 분리되어 있다. 대용량 작업에서는 빠른 판단을 먼저 보고, 불일치나 중요 폴더만 정밀 확인하는 방향을 유지한다.

### 5. Duplicate and Similar Photo Flow

중복/유사 사진 기능은 느린 작업이므로 기본 스캔과 분리한다.

현재 구현된 축:

- `5 파일명 중복검사`: 파일명 소문자 기준으로 동일 이름 그룹을 빠르게 찾는다.
- `중복/유사 분석`: 기존 레거시 성격의 정밀 분석으로 둔다.
- 동일 사진: SHA-256 해시 일치
- 유사 사진: 이미지 지문 거리 기준

현 단계에서는 대용량 정리 흐름의 기본 중복 검사는 파일명 기준을 우선한다. SHA-256/dHash 기반 분석은 사용자가 작은 범위나 후보 폴더를 좁힌 뒤 실행하는 보조 기능으로 둔다.

### 6. Review Export and Codex Round Trip

앱은 조사 결과를 `D:\PICTURES\_review` 아래에 저장한다.

현재 저장 파일:

```text
D:\PICTURES\_review\folder_inventory.csv
D:\PICTURES\_review\folder_inventory.json
D:\PICTURES\_review\date_audit.csv
D:\PICTURES\_review\date_audit.json
D:\PICTURES\_review\organize_draft.json
D:\PICTURES\_review\composite_review.json
D:\PICTURES\_review\organize_plan.csv
D:\PICTURES\_review\organize_plan.json
```

`composite_review.json`은 Codex 검수를 위해 폴더 포함 여부, 폴더 역할, 기준 날짜, 날짜 불일치 상태, 중복/유사 그룹 정보를 사진 단위로 합친다.

Codex가 검수 후 앱에 돌려주는 파일은 다음 경로를 유지한다.

```text
D:\PICTURES\_review\codex_review.json
```

현재 앱이 로드하는 `codex_review.json` 핵심 필드:

```json
{
  "folder_decisions": [
    {
      "path": "D:\\sample",
      "include": true,
      "role": "phone_backup",
      "reason": "primary photo source"
    }
  ]
}
```

향후 `codex_review.json`에서 추가로 반영해야 할 필드:

- `exclude_paths`
- `duplicate_candidates`
- `date_overrides`
- `rename_suggestions`
- `folder_rename_suggestions`
- `metadata_edit_suggestions`
- `organize_strategy_recommendations`
- `notes`

### 7. Organize Plan

정리 계획 탭은 2개 패널로 구성한다.

- 왼쪽: 정리 후 목표 폴더/파일 트리
- 오른쪽: 계획 검토 트리

계획 검토 패널은 다음을 표시한다.

- 정리 파일 수
- 정리 용량
- 목표 루트
- 날짜 소스 모드
- 구조 스키마
- 읽기 전용 상태
- 날짜 불일치 수
- 메타 미확인 수
- 중복/유사 그룹 수
- 샘플 대상 경로

현재 정리 스키마:

- `year_month_event`
- `year_source_month`
- `year_month_day`

현재 날짜/폴더명 모드:

- `year_month_place`
- `date_place`
- `year_month`

정리 계획은 항상 `D:\PICTURES` 아래에 생성되어야 한다. 실제 이동 전 `Dry-run`에서 대상 루트 이탈, 제외 후보 포함, 대상 경로 중복을 검사한다.

### 8. Execution Safety

현재 실제 이동은 읽기 전용이 ON이면 차단된다.

실제 이동 조건:

1. 정리 계획이 있어야 한다.
2. 읽기 전용을 사용자가 OFF로 바꿔야 한다.
3. 사용자 확인을 2회 받아야 한다.
4. Dry-run이 오류 0건이어야 한다.

실행 로그:

```text
D:\PICTURES\_review\execution_log.csv
D:\PICTURES\_review\undo_plan.csv
```

`undo_plan.csv`는 자동 복구 실행기가 아니라 수동 복구용 대응표다.

## Remaining Work

### High Priority

- 완료: 트리 헤더 컬럼 폭 리사이즈를 막던 이벤트 차단을 해제해 좌우 크기 변경이 가능하도록 수정했다.
- 완료: 체크/미체크 트리 하부 노드 열기 문제를 줄이기 위해 `indicator` 클릭 간섭을 보수화하고, 선택/제외 요약 패널을 재귀 트리 렌더로 바꿔 깊은 하부 구조도 열 수 있게 했다.
- 완료: `5 파일명 중복검사` 결과를 기준으로 메타데이터 일괄 변환 계획을 생성하는 버튼(`중복기반 메타계획`)을 추가했다. 기본은 plan-only이며 실제 쓰기는 금지 상태를 유지한다.
- 완료: `1 구조 개요`와 `2 폴더 상세 구조`의 동작 차이를 코드/상태 문구에 반영했다.
- 완료: `codex_review.json` 로드 범위를 폴더 포함 여부와 역할뿐 아니라 날짜 보정, 이름 변경 제안, 제외 경로, 중복 후보까지 확장했다.
- 완료: 날짜 불일치 항목의 파일명/폴더명/메타 수정 제안을 일괄 검토하는 우측 패널을 추가했고, 행 단위 적용 토글 후 제안 반영이 가능하다.
- 완료: 파일명/폴더명 변경 제안은 실제 원본 파일명을 즉시 바꾸지 않고 정리 계획 destination에만 반영되며, 충돌 해소/ Dry-run/사용자 확인 흐름을 거친다.
- 완료: 메타데이터 실제 쓰기는 기본 금지로 유지하고, `metadata_edit_plan.json/csv`를 생성하는 계획 전용 위험작업 분리로 반영했다.
- 완료: 자동 파일명 제안은 보수적으로 정규화하여 ASCII 안전 문자 위주로 제한하고, 위험하거나 난해한 이름은 자동 적용하지 않으며 원본 파일명을 기본 보존한다.

### Medium Priority

- 완료: 날짜 불일치 등급을 `정상`, `검토 필요`, `강한 불일치`, `메타데이터 없음`, `자동 수정 금지`로 세분화했다.
- 완료: 사진 목록 탭 필터를 추가했다(상태, 메타 없음 상태 포함, 중복 후보 폴더만, 제외 폴더 내부만, 특정 확장자).
- 완료: 중복/유사 사진 분석 범위를 `selected_roots` 또는 `review_pairs`(검수 후보쌍)로 제한할 수 있고, 후보 누락/선택 오류/빈 결과 안내 메시지를 제공한다.
- 완료: 정리 전략 비교 버튼으로 여러 모드/스키마 조합의 예상 결과를 우측 검토 패널에 비교 표시한다.
- 완료: 전략별 파일 수, 폴더 수, 용량, 계획 충돌 수, 기존 파일 충돌 수, 날짜 불일치 수를 비교 표시한다.
- 완료: `composite_review`는 `json` 외에 `jsonl`을 함께 저장하고, 대용량일 때 분할 JSON(`partNNN`)으로도 저장한다.

### Lower Priority

- 완료: EXIF GPS를 실제 지명으로 바꾸는 기능은 오프라인 신뢰도가 낮으므로 기본 기능에서 제외했다.
- 완료: 태그 저장을 보조 기능으로 추가했다. 정리 계획 저장 시 `photo_tags.csv/json`을 생성하며, 기본 정리 기준은 파일 시스템 폴더 구조를 유지한다.
- 완료: SHA-256/dHash 기반 유사 사진 분석은 대용량 기본 플로우가 아니라 범위 제한(`selected_roots`/`review_pairs`) 후 실행하는 고급 기능으로 운용한다.

## Recommended User Workflow

1. 앱을 실행한다.
2. 원본을 `D:\`로 둔다.
3. `1 구조 개요`를 실행한다.
4. 폴더 구조 탭에서 왼쪽 전체 트리, 가운데 정리 대상, 오른쪽 제외 대상을 검토한다.
5. 필요하면 우클릭 메뉴나 체크 아이콘으로 포함/제외를 조정한다.
6. `2 폴더 상세 구조`를 실행해 날짜 근거까지 함께 본다.
7. `3 날짜 근거`로 불일치 항목을 검토한다.
8. 필요한 폴더만 체크한 상태에서 `4 사진 메타데이터`를 실행한다.
9. 빠른 중복 확인이 필요하면 `5 파일명 중복검사`를 실행한다.
10. `Review 저장`으로 `D:\PICTURES\_review` 파일 묶음을 만든다.
11. Codex가 `folder_inventory`, `date_audit`, `composite_review`를 검수하고 `codex_review.json`을 작성한다.
12. 앱에서 `Review 로드`를 실행한다.
13. 정리 계획 탭에서 정리 전략을 고르고 `계획 생성`을 누른다.
14. 왼쪽 목표 트리와 오른쪽 계획 검토 패널을 확인한다.
15. `Dry-run`이 오류 0건인지 확인한다.
16. 읽기 전용을 해제하고 실제 이동을 실행한다.

## Validation Requirements

테스트는 실제 D드라이브 원본을 쓰지 않고 샘플 폴더 또는 `D:\PICTURES\_sandbox_test`에서 수행한다.

필수 검증:

- 트리 헤더 컬럼 리사이즈가 마우스 드래그로 정상 동작한다.
- 체크/미체크 상태에서 하부 트리 노드 접기/펼치기가 안정적으로 동작하고 상태가 유지된다.
- 폴더 펼침 `+` 클릭이 체크 상태를 바꾸지 않는다.
- 왼쪽 폴더 체크/언체크가 하위 폴더에 전파된다.
- 하위 상태가 섞이면 부모가 부분 선택으로 표시된다.
- 오른쪽/가운데 패널에서 선택을 바꿔도 왼쪽 트리 펼침 상태가 보존된다.
- `.thumbnails`, `$RECYCLE.BIN`, `System Volume Information`, `.tmp`, `OneDriveTemp`가 제외 후보로 잡힌다.
- 클라우드/동기화 폴더는 기본 제외 또는 주의 대상으로 잡힌다.
- `Review 저장`이 모든 review 파일을 만든다.
- `codex_review.json` 로드가 폴더 체크 상태와 역할을 반영한다.
- 정리 계획 대상 경로가 `D:\PICTURES` 아래로만 생성된다.
- Dry-run이 대상 루트 이탈, 제외 후보 포함, 대상 충돌을 잡는다.
- 읽기 전용 ON에서 실제 이동이 차단된다.
- 실제 이동은 사용자 확인 2회와 Dry-run 통과 후에만 실행된다.
- `execution_log.csv`와 `undo_plan.csv`가 생성된다.
- 파일명 중복검사 결과 기반 메타데이터 일괄 변환 계획(`metadata_edit_plan.*`)이 생성되고, 실제 쓰기는 기본 비활성화 상태를 유지한다.

## Development Governance

작업 운영 규칙은 루트 `AGENTS.md`에 둔다. 현재 `AGENTS.md`에는 CAO 실행 규칙과 vowline 검증 규칙을 함께 둔 상태다.

향후 구현은 다음 기준을 따른다.

- 사용자 원본 사진에는 기본적으로 쓰지 않는다.
- 파일 이동, 이름 변경, 메타데이터 변경은 모두 계획 파일과 Dry-run을 먼저 만든다.
- 앱이 저장한 review 파일을 Codex가 검수하고, Codex의 검수 결과를 앱이 다시 로드하는 왕복 구조를 유지한다.
- UI가 대용량 데이터를 한 번에 다 표시하지 않게 한다.
- 느린 작업은 별도 버튼으로 분리하고 중지 가능하게 한다.
- 앱 문서와 GUI 명칭은 실제 코드 동작과 계속 일치시킨다.

## Imported Good Practices From Existing Repo History

`humtr/photos` 기존 커밋 이력에서 바로 가져와서 적용할 만한 계획 항목을 아래에 추가한다.

### 1. Fail-Fast Command Discipline

Windows 스크립트/명령 실행은 중간 실패를 무시하지 않고 즉시 중단해야 한다.

- 핵심 실행기는 `ErrorActionPreference=Stop` 또는 동등 정책을 적용한다.
- 외부 명령 실행 후 종료코드를 반드시 확인한다.
- 실패한 명령, 종료코드, 인자를 로그에 남긴다.
- 실패 후 다음 단계로 넘어가지 않는다.

이 원칙은 정리 작업에서 특히 중요하다. 실패를 무시하고 진행하면 일부 파일만 이동된 불완전 상태가 남는다.

### 2. Windows Handoff Validation Checklist

실사용 전 검증 절차를 목표 문서에 명시해 개발/운영 경계를 분리한다.

- 먼저 샘플 폴더에서 dry-run을 통과시킨다.
- `D:\` 같은 실경로 입력이 정상 동작하는지 확인한다.
- 결과 DB/review/log/undo 파일이 의도 경로(`D:\PICTURES\_review`)에 생성되는지 확인한다.
- dry-run 경로에서는 파일 삭제/이동이 절대 일어나지 않는지 확인한다.
- 실제 대용량 원본은 별도 승인 전 읽기 전용으로만 검토한다.

### 3. Resumable Large-Scale Analysis

50만 파일급에서는 중단 후 재개가 필수다. 기존 이력의 "resumable analysis" 원칙을 다음으로 반영한다.

- 단계별 스냅샷 파일 저장: 폴더 구조, 용량/종류, 날짜 근거, 메타데이터, 중복 검사.
- 재실행 시 기존 스냅샷을 우선 재사용하고 변경된 폴더만 재스캔한다.
- 스캔 단위는 "폴더 경계"로 나눠 중간 저장 가능하게 한다.
- 중단(`중지` 버튼) 시 마지막 정상 체크포인트를 기록한다.

### 4. File-Management Review Reports As First-Class Artifacts

기존 이력의 "file management review reports"를 본 앱 용어로 고정한다.

- `folder_inventory.*`, `date_audit.*`, `organize_draft.json`, `composite_review.json`, `organize_plan.*`, `execution_log.csv`, `undo_plan.csv`를 핵심 산출물로 본다.
- 보고서 파일이 없는 상태에서는 실제 이동을 허용하지 않는다.
- 보고서에는 계획의 근거(날짜 소스, 중복 여부, 제외 여부)를 반드시 남긴다.

### 5. Temporary Path Policy

기존 이력의 임시경로 정책을 Windows 중심으로 변환해 반영한다.

- 런타임 임시 데이터는 프로젝트 지정 위치(`D:\PICTURES\_review` 또는 앱 전용 작업 디렉터리)로 모은다.
- 시스템 임시 경로를 써야 할 때는 OS 기본 임시 경로를 사용하고, 쓰기 가능 여부를 먼저 확인한다.
- 임시 파일 의존 로직을 하드코딩 경로로 고정하지 않는다.

### 6. Scope Boundary for Safety Claims

기존 이력의 "handoff boundary"를 본 앱에도 유지한다.

- 문서에 적은 기능이 곧바로 실드라이브 검증 완료를 의미하지 않는다.
- 성능/파일잠금/긴경로/권한/외부 툴 연동은 실제 Windows 환경 검증 결과로만 "완료" 판정한다.
- GOAL과 README에는 "구현됨"과 "실환경 검증 완료"를 구분해 기록한다.
