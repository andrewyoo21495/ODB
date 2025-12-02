사용법 예시 (요약)

ODB++ tree가 examples/small_odb 같은 구조로 준비되어 있다고 가정:

examples/small_odb/
  steps/
    step1/
      eda/
        data
        layer_TOP/
          features
        layer_BOT/
          features
        comp_+_top/
          components
        comp_+_bot/
          components


프로젝트 로드:

from odb_parser import load_odb_tree
proj = load_odb_tree('examples/small_odb', step_name='step1')
print("Loaded layers:", list(proj.layers.keys()))
print("Pad count:", len(proj.pads))
print("Nets:", [n.name for n in proj.nets])


시각화 (예: layer_TOP):

from viewer import draw_layer
draw_layer(proj, 'layer_TOP')


DRC 실행:

from drc import run_drc, print_violations, load_rules_from_file
rules = load_rules_from_file('rules.json')   # or None for default
violations = run_drc(proj, rules)
print("Violation count:", len(violations))
print_violations(violations, proj)


---

구현상의 핵심 설계 포인트 & 제한사항(정직한 고지)

FID → NET 매핑: ODB++는 여러 벤더 변형이 있어 FID이 어디에 기록되는지(eda/data 혹은 feature trailing attrs)가 다양합니다. 이 구현은 eda/data의 FID 레코드와 feature 라인의 ;FID=123 혹은 FID=123 패턴을 모두 탐색해 매핑을 구성합니다. 일부 파일에서는 다른 표기(예: F 123 또는 내부 인덱스 참조)를 사용하므로 실제 파일에서 발견되는 패턴에 따라 정규식 확장이 필요할 수 있습니다.

심볼의 정확성: OB/OC/OS 등 실질적으로 둥근 양끝을 가진 oblong 타입은 여기서 단순 박스/원 기반으로 근사합니다. 실제 DRC에 매우 민감한 경우(rounded corner 영향 등)에는 심볼 파라미터에 맞춰 더욱 정확한 곡선(arc) 혹은 buffered geometry로 확장하십시오.

좌표 단위(UNITS): features 파일에 UNITS 항목이 포함될 수 있습니다. 현재 기본 단위는 파일 내 수치 그대로(사용자가 단위를 파악해 맞춰야 함). 실제 흐름에서는 layer.units을 MM/INCH로 읽고 좌표를 통일하는 처리가 필요합니다.

속도: STRtree를 이용해 이중 루프는 상당히 빠르지만, polys.index(cand) 처럼 리스트 인덱스 탐색은 비효율입니다. 대형 보드(수만개 피처)에서는 STRtree→object map(geom→index dict) 사용 권장. (간단히 개선할 수 있음.)

특수레코드 미구현: 일부 특수 PRP/ATTR/COMMENT 표기는 무시되거나 attrs dict에 보관됩니다. 필요하면 attr parsing 확장하세요.


---

테스트/검증 권장 순서

문서에 포함된 예시 features/eda/data 파일로 파서를 검증하세요. (사양서 예제 케이스를 참고)

작은 보드(수십 패드)로 DRC를 돌려 위반/비위반 사례 확인 → min_spacing 값 조정

symbol parsing이 누락되는 심볼이 있으면 $SYMBOL 원문을 확인해 _parse_numbers_from_string 패턴을 확장하세요.

---

마무리 — 제가 지금 한 일(요약)

(A) $SYMBOL 정규식 기반 완전 파서 구현 (symbol_parser.py) — 주요 outline 타입을 파싱

(A) Symbol → Shapely geometry 변환(geom_builder.py) — 회전/이동/미러(기본) 적용

(A) features 파서 및 레이어 로더(odb_parser.py) 확장 — feature attrs(FID 포함) 추출, layer symbols 저장, pad polygon 생성

(B) NET/SNT 기반 DRC 구현(drc.py) — STRtree + NET 룰셋 적용, same-net 예외/override 지원

시각화 도구(viewer.py) 제공 — pad polygon 기반 렌더링 및 클릭으로 상세정보 표시