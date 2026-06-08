# ODB++ Processing System

ODB++ 아카이브를 파싱하여 PCB 레이어 시각화, 설계 규칙 자동 검증(체크리스트), 동박 비율 분석을 수행하는 Python 기반 PCB 설계 분석 도구입니다.

```
ODB++ .tgz Archive
  → odb_loader (추출 & 탐색)
  → 14개 파서 → Dataclass 모델 → JSON 캐시
  → 3개 소비자: 시각화, 체크리스트 엔진, 동박 분석
```

## Requirements

- Python 3.10+
- matplotlib, shapely, numpy, scipy, openpyxl

```bash
pip install -r requirements.txt
```

## CLI Commands

```bash
python main.py cache           <odb_path>                     # ODB++ 파싱 & JSON 캐시 생성
python main.py view            <odb_path> [--layers L1 L2]    # 레이어 인터랙티브 뷰어
python main.py view-comp       <odb_path>                     # 컴포넌트 뷰어
python main.py view-net        <odb_path>                     # 넷 필터 뷰어
python main.py check           <odb_path> [--rules R1 R2]     # 설계 체크리스트 실행
python main.py copper          <odb_path>                     # 레이어 두께 정보
python main.py copper-ratio    <odb_path>                     # 동박 비율 뷰어
python main.py copper-calculate                                # 배치 동박 계산기 GUI
python main.py compare         <odb_old> <odb_new>            # 리비전 비교
python main.py info            <odb_path>                     # Job 요약 정보
```

---

## 1. Project Structure

```
ODB/
├── main.py                              # CLI 진입점 (argparse 서브커맨드)
├── main_gui.py                          # 체크리스트 GUI 래퍼
├── requirements.txt                     # pip 의존성 목록
├── ODB_System_Design.md                 # 상세 아키텍처 문서
│
├── src/
│   ├── models.py                        # 모든 Dataclass & Enum 정의 (공유 데이터 레이어)
│   ├── odb_loader.py                    # 아카이브 추출 & Job 탐색
│   ├── cache_manager.py                 # JSON 직렬화/역직렬화
│   ├── unit_converter.py               # INCH → MM 단위 변환
│   ├── copper_reporter.py              # 동박 분석 리포트
│   ├── copper_html_reporter.py         # 동박 분석 HTML 리포트
│   │
│   ├── parsers/                         # 14개 ODB++ 파일 파서
│   │   ├── base_parser.py              #   공통 파싱 유틸리티
│   │   ├── matrix_parser.py            #   레이어 매트릭스 파싱
│   │   ├── feature_parser.py           #   레이어 피처 파싱 (Line, Pad, Arc, Surface 등)
│   │   ├── component_parser.py         #   컴포넌트 배치 파싱
│   │   ├── eda_parser.py              #   EDA 데이터 파싱 (넷, 패키지, 핀)
│   │   ├── symbol_parser.py           #   심볼 정의 파싱
│   │   ├── symbol_resolver.py         #   심볼 해석 로직
│   │   ├── font_parser.py            #   폰트 데이터 파싱
│   │   ├── profile_parser.py          #   보드 프로파일/외곽선 파싱
│   │   ├── stackup_parser.py          #   레이어 스택업 파싱
│   │   ├── netlist_parser.py          #   넷리스트 파싱
│   │   ├── stephdr_parser.py          #   Step 헤더 파싱
│   │   └── misc_parser.py            #   기타 메타정보 파싱
│   │
│   ├── visualizer/                      # 렌더링 & 인터랙티브 뷰어
│   │   ├── viewer.py                   #   메인 matplotlib 인터랙티브 뷰어
│   │   ├── renderer.py                #   렌더링 오케스트레이터
│   │   ├── layer_renderer.py          #   피처 → 그래픽 변환
│   │   ├── symbol_renderer.py         #   심볼 지오메트리 생성
│   │   ├── component_overlay.py       #   컴포넌트 배치 오버레이
│   │   ├── copper_utils.py            #   동박 비율 계산
│   │   ├── copper_vector.py           #   벡터 기반 동박 분석
│   │   ├── net_filter.py             #   넷 기반 필터링
│   │   └── fid_lookup.py             #   피듀셜 마커 조회
│   │
│   ├── checklist/                       # 설계 규칙 검증 엔진
│   │   ├── engine.py                   #   규칙 레지스트리 & 실행
│   │   ├── rule_base.py               #   ChecklistRule 추상 베이스 클래스
│   │   ├── reporter.py                #   Excel 리포트 생성
│   │   ├── html_reporter.py           #   HTML 리포트 생성
│   │   ├── report_text_generator.py   #   리포트 텍스트 포매팅
│   │   ├── component_classifier.py    #   컴포넌트 타입 분류
│   │   ├── reference_loader.py        #   레퍼런스 데이터 로딩
│   │   │
│   │   ├── geometry_utils/             #   11개 지오메트리 헬퍼
│   │   │   ├── overlap.py             #     폴리곤 겹침 감지
│   │   │   ├── distance.py            #     거리 계산
│   │   │   ├── clearance.py           #     클리어런스 규칙 검사
│   │   │   ├── orientation.py         #     컴포넌트 방향 분석
│   │   │   ├── polygon.py             #     폴리곤 연산 (Shapely)
│   │   │   ├── bending.py             #     벤딩 영역 분석
│   │   │   ├── via.py                 #     비아 배치 규칙
│   │   │   ├── shield_can.py          #     쉴드캔 지오메트리
│   │   │   ├── nc_pad.py              #     NC 패드 분석
│   │   │   └── size.py                #     컴포넌트 사이즈 계산
│   │   │
│   │   ├── rules/                      #   37개 설계 규칙 구현
│   │   │   ├── ckl_01_001 ~ 010.py    #     CKL-01: IC/필터/오실레이터 배치 규칙
│   │   │   ├── ckl_02_001 ~ 012.py    #     CKL-02: 캐패시터/인덕터/커넥터 간격 규칙
│   │   │   └── ckl_03_001 ~ 016.py    #     CKL-03: PCB 외곽 클리어런스/벤딩/보드 레벨 규칙
│   │   │
│   │   └── visualizers/                #   규칙별 시각화 모듈
│   │       ├── bending_viz.py         #     벤딩 영역 시각화
│   │       ├── clearance_viz.py       #     클리어런스 위반 시각화
│   │       ├── dpad_mask_viz.py       #     솔더마스크 클리어런스
│   │       ├── narrow_width_viz.py    #     좁은 트레이스 폭
│   │       ├── overlap_viz.py         #     컴포넌트 겹침
│   │       └── via_check_viz.py       #     비아 밀도/배치
│   │
│   └── comparator/                      # 리비전 간 비교 엔진
│       ├── engine.py                   #   비교 오케스트레이터
│       ├── base.py                     #   베이스 비교기 클래스
│       ├── reporter.py                #   비교 리포트 생성
│       ├── diff_visualizer.py         #   비주얼 diff 표시
│       └── comparators/               #   타입별 비교기
│           ├── component_diff.py      #     컴포넌트 변경 감지
│           └── checklist_diff.py      #     체크리스트 결과 비교
│
├── documents/                           # 사용자 문서
│   ├── USAGE.md                        #   사용 가이드 & CLI 문서
│   └── checklist_documentation.html    #   체크리스트 참조 문서
│
├── build/                               # PyInstaller 빌드 산출물
│   └── CopperCalculator/              #   독립 실행 파일 (.exe)
│
├── cache/                               # 생성된 JSON 캐시 (gitignored)
├── data/                                # 입력 ODB++ 아카이브 (gitignored)
├── output/                              # 생성된 리포트 (gitignored)
├── tests/                               # 테스트 파일 (gitignored)
└── references/                          # 참조 문서 (gitignored)
```

---

## 2. ODB++ Caching System

ODB++ 아카이브를 파싱한 결과를 **JSON 파일**로 캐싱하여, 반복 실행 시 재파싱 없이 데이터를 즉시 로드합니다. 캐시는 `cache/<job_name>/` 디렉토리에 저장되며, 모든 좌표는 **밀리미터(MM)** 단위로 정규화된 상태로 캐싱됩니다.

### 캐시 디렉토리 구조

```
cache/
└── <job_name>/                          # ODB++ 파일명 기반 캐시 폴더
    ├── job_info.json                    # Job 메타 정보
    ├── matrix_steps.json                # Step 정의
    ├── matrix_layers.json               # 레이어 매트릭스 (레이어 목록 & 속성)
    ├── step_header.json                 # Step 헤더 (좌표계 원점, 활성 영역)
    ├── profile.json                     # 보드 외곽선 (프로파일)
    ├── eda_data.json                    # EDA 데이터 (넷, 패키지, 핀)
    ├── netlist.json                     # 넷리스트 (넷 이름 매핑)
    ├── components_top.json              # Top 레이어 컴포넌트 배치
    ├── components_bot.json              # Bottom 레이어 컴포넌트 배치
    ├── components_top_units.json        # Top 컴포넌트 단위 정보
    ├── components_bot_units.json        # Bottom 컴포넌트 단위 정보
    ├── symbols.json                     # 사용자 정의 심볼
    ├── font.json                        # 스트로크 폰트 데이터
    ├── stackup.json                     # 레이어 스택업 (선택)
    ├── copper_data.json                 # 동박 두께 데이터 (선택)
    ├── data_type.json                   # 데이터 타입 (unit/array)
    │
    └── layers/                          # 레이어별 피처 데이터
        ├── <layer_name>.json            # 각 레이어의 피처 목록
        ├── comp_+_top.json
        ├── comp_+_bot.json
        ├── signal_1.json
        ├── signal_2.json
        ├── solder_mask_top.json
        └── ...
```

### 캐시 파일별 상세 데이터 구조

#### `job_info.json` — Job 메타 정보

ODB++ 아카이브의 기본 정보를 담고 있습니다.

```json
{
  "job_name": "example_board",
  "odb_version_major": 8,
  "odb_version_minor": 1,
  "odb_source": "Allegro",
  "creation_date": "20240101",
  "save_date": "20240115",
  "save_app": "Allegro PCB Designer",
  "save_user": "designer",
  "units": "INCH",
  "max_uid": 12345
}
```

#### `matrix_layers.json` — 레이어 매트릭스

PCB의 전체 레이어 구성을 정의합니다. 각 레이어의 타입, 극성, 적층 순서 등의 정보를 포함합니다.

```json
[
  {
    "row": 1,
    "name": "comp_+_top",
    "context": "BOARD",
    "type": "COMPONENT",
    "polarity": "POSITIVE",
    "id": 1,
    "form": "RIGID"
  },
  {
    "row": 2,
    "name": "signal_1",
    "context": "BOARD",
    "type": "SIGNAL",
    "polarity": "POSITIVE",
    "id": 2,
    "dielectric_type": "",
    "cu_top": "",
    "cu_bottom": ""
  }
]
```

| 필드 | 설명 |
|---|---|
| `type` | `SIGNAL`, `POWER_GROUND`, `DIELECTRIC`, `SOLDER_MASK`, `SILK_SCREEN`, `DRILL`, `COMPONENT` 등 |
| `context` | `BOARD` (기본 보드 레이어) 또는 `MISC` |
| `polarity` | `POSITIVE` 또는 `NEGATIVE` |
| `form` | `RIGID` 또는 `FLEX` (유연기판 여부) |

#### `profile.json` — 보드 외곽선

PCB 보드의 물리적 외곽선을 Contour(윤곽선) 형태로 정의합니다.

```json
{
  "units": "MM",
  "surface": {
    "polarity": "P",
    "contours": [
      {
        "is_island": true,
        "start": { "x": 0.0, "y": 0.0 },
        "segments": [
          { "end": { "x": 100.0, "y": 0.0 } },
          { "end": { "x": 100.0, "y": 80.0 } },
          { "end": { "x": 0.0, "y": 80.0 } },
          { "end": { "x": 0.0, "y": 0.0 } }
        ]
      }
    ]
  }
}
```

- `is_island: true` — 보드 외곽 (island), `false` — 내부 컷아웃 (hole)
- Segment는 `LineSegment` (직선) 또는 `ArcSegment` (호) 타입

#### `components_top.json` / `components_bot.json` — 컴포넌트 배치

Top/Bottom 레이어에 실장된 컴포넌트의 위치, 회전, 속성, 핀(Toeprint) 정보를 저장합니다.

```json
[
  {
    "pkg_ref": 0,
    "x": 45.72,
    "y": 30.48,
    "rotation": -90.0,
    "mirror": false,
    "comp_name": "C101",
    "part_name": "CAP_0402",
    "attributes": { ".comp_mount_type": "SMT" },
    "properties": {},
    "toeprints": [
      {
        "pin_num": 0,
        "x": 45.22,
        "y": 30.48,
        "rotation": 0.0,
        "mirror": false,
        "net_num": 5,
        "subnet_num": 0,
        "name": "1",
        "geom": {
          "symbol_name": "rect20x15",
          "x": 45.22,
          "y": 30.48,
          "rotation": 0.0,
          "mirror": false,
          "units": "MM",
          "is_user_symbol": false
        }
      }
    ],
    "bom_data": {
      "cpn": "CPN-001",
      "pkg": "0402",
      "ipn": "IPN-100",
      "description": "100nF 16V X7R",
      "vendors": []
    },
    "id": 1
  }
]
```

| 필드 | 설명 |
|---|---|
| `pkg_ref` | EDA 패키지 인덱스 (eda_data.packages에 대한 참조) |
| `x`, `y` | 보드 좌표 (MM) |
| `rotation` | 회전 각도 (ODB++ CW 양수 → 캐시에서 부호 반전됨) |
| `comp_name` | Reference Designator (예: C101, U3, R22) |
| `part_name` | 부품 이름 |
| `toeprints` | 핀별 패드 위치 & 넷 연결 정보 |
| `toeprints[].geom` | FID 해석된 패드 지오메트리 (심볼명, 좌표) |
| `bom_data` | BOM 정보 (부품 번호, 패키지, 설명) |

#### `eda_data.json` — EDA 데이터

넷(Net) 연결 정보와 패키지 정의를 포함하는 EDA 설계 데이터입니다.

```json
{
  "source": "Allegro",
  "units": "MM",
  "layer_names": ["signal_1", "signal_2", "power", "ground"],
  "nets": [
    {
      "name": "VCC_3V3",
      "index": 0,
      "subnets": [
        {
          "type": "TOP",
          "feature_ids": [
            { "type": "C", "layer_idx": 0, "feature_idx": 42 }
          ],
          "side": "T",
          "comp_num": 3,
          "toep_num": 1
        },
        {
          "type": "VIA",
          "feature_ids": [
            { "type": "C", "layer_idx": 0, "feature_idx": 100 }
          ]
        },
        {
          "type": "TRC",
          "feature_ids": [
            { "type": "C", "layer_idx": 0, "feature_idx": 55 }
          ]
        }
      ],
      "attributes": {}
    }
  ],
  "packages": [
    {
      "name": "CAP_0402",
      "pitch": 0.5,
      "bbox": { "xmin": -0.5, "ymin": -0.3, "xmax": 0.5, "ymax": 0.3 },
      "pins": [
        {
          "name": "1",
          "type": "SMD",
          "center": { "x": -0.25, "y": 0.0 },
          "electrical_type": "E",
          "mount_type": "S",
          "outlines": [
            { "type": "RC", "params": { "w": 0.2, "h": 0.15 } }
          ]
        }
      ],
      "outlines": [
        { "type": "RC", "params": { "w": 1.0, "h": 0.6 } }
      ]
    }
  ],
  "properties": {}
}
```

| 필드 | 설명 |
|---|---|
| `nets[].subnets` | 넷을 구성하는 서브넷 (VIA, TRC/Trace, PLN/Plane, TOP/Toeprint) |
| `nets[].subnets[].feature_ids` | 레이어 피처에 대한 교차 참조 (C=Copper, L=Laminate, H=Hole) |
| `packages` | EDA 패키지 정의 (핀 위치, 외곽선, BBox) |
| `packages[].pins[].outlines` | 핀 패드 형상 (RC=사각, CR=원형, SQ=정사각, CT=사용자 Contour) |

#### `layers/<layer_name>.json` — 레이어 피처

각 레이어에 포함된 그래픽 피처(Line, Pad, Arc, Text, Surface 등)를 저장합니다.

```json
{
  "units": "INCH",
  "id": 1,
  "feature_count": 1500,
  "symbols": [
    { "index": 0, "name": "r50", "unit_override": null },
    { "index": 1, "name": "rect60x40", "unit_override": null }
  ],
  "attr_names": { "0": ".drill", "1": ".net_name" },
  "attr_texts": { "0": "PLATED", "1": "VCC" },
  "features": [
    {
      "_type": "line",
      "xs": 10.0, "ys": 20.0,
      "xe": 15.0, "ye": 20.0,
      "symbol_idx": 0,
      "polarity": "P",
      "dcode": 10,
      "attributes": {}
    },
    {
      "_type": "pad",
      "x": 25.0, "y": 30.0,
      "symbol_idx": 1,
      "polarity": "P",
      "rotation": 45.0,
      "mirror": false,
      "attributes": { ".net_name": "GND" }
    },
    {
      "_type": "surface",
      "polarity": "P",
      "contours": [
        {
          "is_island": true,
          "start": { "x": 0.0, "y": 0.0 },
          "segments": [
            { "end": { "x": 5.0, "y": 0.0 } },
            { "end": { "x": 5.0, "y": 5.0 } }
          ]
        }
      ],
      "attributes": {}
    }
  ]
}
```

| 피처 타입 (`_type`) | 설명 | 주요 필드 |
|---|---|---|
| `line` | 직선 트레이스 | `xs`, `ys`, `xe`, `ye`, `symbol_idx` |
| `pad` | 패드 (SMD/TH) | `x`, `y`, `symbol_idx`, `rotation`, `mirror` |
| `arc` | 호 형태 트레이스 | `xs`, `ys`, `xe`, `ye`, `xc`, `yc`, `clockwise` |
| `text` | 텍스트 (실크스크린 등) | `x`, `y`, `font`, `text`, `xsize`, `ysize` |
| `barcode` | 바코드 | `x`, `y`, `barcode`, `width`, `height` |
| `surface` | 폴리곤 영역 (동박면 등) | `contours` (Contour 배열) |

- `symbol_idx` — `symbols` 배열의 인덱스로 해당 피처의 aperture(심볼) 참조
- `polarity` — `P` (Positive, 추가) 또는 `N` (Negative, 제거)

#### `symbols.json` — 사용자 정의 심볼

표준 심볼로 표현할 수 없는 사용자 정의 심볼(aperture)의 지오메트리를 저장합니다.

```json
{
  "custom_pad_1": {
    "name": "custom_pad_1",
    "units": "MM",
    "features": [
      { "_type": "line", "xs": 0.0, "ys": -0.5, "xe": 0.0, "ye": 0.5, "symbol_idx": 0, "polarity": "P" },
      { "_type": "pad", "x": 0.0, "y": 0.0, "symbol_idx": 1, "polarity": "P" }
    ],
    "symbols": [
      { "index": 0, "name": "r10", "unit_override": null }
    ]
  }
}
```

#### `netlist.json` — 넷리스트

넷 인덱스와 넷 이름의 매핑 정보입니다.

```json
{
  "header": { "optimize": false, "staggered": false },
  "net_names": { "0": "VCC_3V3", "1": "GND", "2": "CLK_100M" }
}
```

#### `step_header.json` — Step 헤더

Step의 좌표계 원점, 활성 영역, Step Repeat 정보를 포함합니다.

```json
{
  "units": "INCH",
  "x_datum": 0.0,
  "y_datum": 0.0,
  "x_origin": 0.0,
  "y_origin": 0.0,
  "top_active": 0.0,
  "bottom_active": 0.0,
  "right_active": 0.0,
  "left_active": 0.0,
  "id": 0,
  "step_repeats": []
}
```

#### `font.json` — 스트로크 폰트

텍스트 피처 렌더링에 사용되는 스트로크 폰트 정의입니다.

```json
{
  "xsize": 0.05,
  "ysize": 0.07,
  "offset": 0.0,
  "characters": {
    "A": {
      "char": "A",
      "strokes": [
        { "x1": 0.0, "y1": 0.0, "x2": 0.025, "y2": 0.07, "polarity": "P", "shape": "R", "width": 0.012 }
      ]
    }
  }
}
```

### 캐싱 플로우

```
1. ODB++ .tgz 아카이브 로드 (odb_loader)
2. 14개 전용 파서가 각 데이터 영역을 Dataclass로 파싱
3. 단위 정규화: 모든 INCH 좌표 → MM 변환 (×25.4)
4. 회전각 부호 반전: ODB++ CW 양수 → 캐시에서 부호 반전
5. EDA ↔ 컴포넌트 간 스케일 보정 (_calibrate_eda_to_components)
6. cache_manager가 Dataclass → JSON 직렬화 (타입 디스크리미네이터 _type 삽입)
7. cache/<job_name>/ 하위에 파일별로 저장
```

### 캐시 유효성 검사

캐시 매니저는 소스 ODB++ 파일의 수정 시간과 캐시 파일의 수정 시간을 비교하여, 소스가 더 최신이면 캐시를 재생성합니다.
