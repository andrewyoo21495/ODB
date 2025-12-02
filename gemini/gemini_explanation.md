제시해주신 ODB++ Specification 문서를 기반으로, PCB 설계 및 검토 자동화 시스템의 초석이 될 파이썬 코드를 작성해 드립니다.

이 코드는 단일 파일로 실행 가능하도록 구조화되어 있으며, 확장성을 위해 객체 지향 프로그래밍(OOP) 방식을 따릅니다.

## 주요 기능 요약
1. 데이터 모델링: ODB++의 계층 구조(Step, Layer, Net, Package, Component)를 파이썬 클래스로 정의했습니다.
2. 파싱 엔진: ODB++의 matrix, eda/data, components 파일을 읽어 객체로 변환하는 로직을 포함합니다.
3. 지오메트리 연산: 부품의 회전(Rotation), 미러(Mirror)를 고려하여 Pin의 절대 좌표를 계산하는 로직을 구현했습니다.
4. 시각화 및 인터랙션: matplotlib을 사용하여 PCB를 시각화하고, 마우스 클릭 시 부품 정보를 출력합니다.
5. 설계 검토 기능: 부품 간 거리 계산, 배치 방향(수평/수직) 판별 기능을 포함합니다.



## 코드 구조 및 구현 설명 (Specification 반영)

1. 데이터 클래스화 (Package, Component, Layer 등)Specification 반영: ODB++의 계층 구조를 반영하기 위해 물리적 배치를 담당하는 Component와 논리적/형상 정보를 담는 Package를 분리했습니다.효율성: eda/data 파일에 있는 패키지 정보는 한 번만 로드하고(Package 클래스), 수많은 부품(Component 클래스)이 이를 참조(package_ref)하는 방식으로 메모리를 효율적으로 관리합니다.

2. 지오메트리 계산 엔진 (get_pin_absolute_coordinates)필수 규칙 반영: 부품의 좌표($x, y$), 회전($rotation$), 미러($mirror$) 속성을 이용하여 패키지 기준의 핀 좌표를 PCB 전체 기준의 절대 좌표로 변환하는 선형 대수 로직을 구현했습니다. 이는 Pin-to-Pin 거리 계산의 핵심입니다.

3. 층별 정보 관리 (Layer 클래스)Specification 반영: matrix 파일 정보를 기반으로 레이어의 순서(Order)와 극성(Polarity), Context(Board/Misc)를 관리할 수 있는 구조를 잡았습니다. 시각화 시 Top과 Bottom을 색상(파랑/빨강)으로 구분하여 표현했습니다.

4. 시각화 및 인터랙션 (PCBViewer)matplotlib을 사용하여 PCB 뷰어를 구현했습니다.Interactive: 마우스 클릭 이벤트(button_press_event)를 바인딩하여, 사용자가 부품을 클릭하면 해당 부품의 상세 정보(Ref Des, Layer, Rotation, 수평/수직 배치 여부 등)를 팝업(Annotation)으로 띄웁니다.

5. 설계 검토 자동화 기초 (PCBCalculator)최종 목표인 "설계 및 검토 자동화"를 위해 계산 전용 클래스를 분리했습니다.현재는 Pin-to-Pin 거리 계산과 클리어런스 체크(DRC) 로직이 구현되어 있으며, 향후 Pad-to-Via 등으로 쉽게 확장이 가능합니다.

향후 확장 가이드 (20년차 엔지니어의 조언)실제 파일 파싱: 현재 코드는 로직 검증을 위해 데이터를 하드코딩으로 넣었습니다. 실제 구현 시에는 Python의 gzip 모듈(ODB++ 파일은 보통 압축됨)과 정규표현식(re)을 사용하여 텍스트 기반의 ODB++ 파일을 줄 단위로 파싱하는 코드를 ODBParser 메서드 내에 채워 넣으셔야 합니다.Contour 처리: eda/data에는 패키지의 외곽선이 단순 박스가 아니라 복잡한 폴리곤(Contour)으로 정의될 수 있습니다. 이를 완벽히 지원하려면 shapely 라이브러리를 도입하여 다각형 교차 연산을 수행하는 것이 좋습니다.Netlist 통합: 현재는 형상 정보 위주이나, 자동화 검토를 위해서는 eda/data의 NET 정보를 파싱하여 "같은 Net끼리는 가까워도 되지만 다른 Net은 이격거리를 지켜야 한다"는 로직을 PCBCalculator에 추가해야 합니다.

