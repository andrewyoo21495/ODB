###################################
### THE CODE IS BASED ON GEMINI ###
###################################


import os
import math
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

# ==========================================
# 1. 데이터 클래스 정의 (Data Modeling)
# ODB++ 사양서에 기반한 데이터 구조화
# ==========================================

@dataclass
class Point:
    """X, Y 좌표를 관리하는 클래스"""
    x: float
    y: float

@dataclass
class BoundBox:
    """부품이나 형상의 경계 박스 (Min/Max)"""
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def width(self):
        return abs(self.x_max - self.x_min)

    @property
    def height(self):
        return abs(self.y_max - self.y_min)

    @property
    def center(self):
        return Point((self.x_min + self.x_max) / 2, (self.y_min + self.y_max) / 2)

@dataclass
class PinDef:
    """패키지 내부의 핀 정의 (eda/data)"""
    name: str
    x: float
    y: float
    type: str  # T(Through), S(Surface) 등
    id: int

@dataclass
class Package:
    """부품의 형상 정보 (PKG)"""
    name: str
    pitch: float
    bbox: BoundBox
    pins: Dict[str, PinDef] = field(default_factory=dict)

    def get_orientation(self) -> str:
        """장축을 기준으로 배치 방향 확인"""
        if self.bbox.width >= self.bbox.height:
            return "Horizontal" # 수평
        return "Vertical"   # 수직

@dataclass
class Component:
    """실장된 부품 정보 (CMP)"""
    ref_des: str        # 참조 번호 (예: U1, R2)
    part_name: str      # 파트 이름
    package_name: str   # 사용하는 패키지 이름
    x: float            # 배치 X 좌표
    y: float            # 배치 Y 좌표
    rotation: float     # 회전 각도
    mirror: bool        # 미러 여부 (True면 Bottom 면일 확률 높음)
    layer_name: str     # 소속 레이어 (comp_+_top 등)
    
    # 런타임에 연결될 패키지 객체 참조
    package_ref: Optional[Package] = None 

    def get_pin_absolute_coordinates(self) -> Dict[str, Point]:
        """
        부품의 위치, 회전, 미러를 적용하여 
        핀들의 절대 좌표(Global Coordinate)를 계산하여 반환
        """
        if not self.package_ref:
            return {}

        abs_pins = {}
        rad = math.radians(self.rotation)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        for pin_name, pin_def in self.package_ref.pins.items():
            # 1. 로컬 좌표 가져오기
            px, py = pin_def.x, pin_def.y

            # 2. 미러링 적용 (X축 기준 반전)
            if self.mirror:
                px = -px

            # 3. 회전 변환 (Rotation)
            # x' = x*cos - y*sin
            # y' = x*sin + y*cos
            rx = px * cos_a - py * sin_a
            ry = px * sin_a + py * cos_a

            # 4. 이동 변환 (Translation)
            final_x = self.x + rx
            final_y = self.y + ry

            abs_pins[pin_name] = Point(final_x, final_y)
        
        return abs_pins

@dataclass
class Layer:
    """PCB 레이어 정보 (Matrix 기반)"""
    name: str
    type: str       # SIGNAL, DRILL, SOLDER_MASK, COMPONENT 등
    context: str    # BOARD, MISC
    polarity: str   # POSITIVE, NEGATIVE
    order: int      # 적층 순서

# ==========================================
# 2. ODB++ 파서 엔진 (Parsing Engine)
# 파일 구조를 읽어 객체로 변환
# ==========================================

class ODBParser:
    def __init__(self, odb_path: str):
        self.root_path = odb_path
        self.packages: Dict[str, Package] = {}
        self.components: List[Component] = []
        self.layers: List[Layer] = []
        self.steps: List[str] = []
        
        # 단위 (기본값: INCH, 파일 헤더에서 파싱 필요)
        self.units = "INCH" 

    def parse_matrix(self):
        """matrix/matrix 파일을 파싱하여 레이어 정보를 구축"""
        matrix_path = os.path.join(self.root_path, "matrix", "matrix")
        if not os.path.exists(matrix_path):
            print("Matrix file not found. Skipping layer parsing.")
            return

        print(f"[System] Parsing Matrix: {matrix_path}")
        # 실제 구현에서는 파일을 open하여 파싱해야 함.
        # 여기서는 예시 데이터로 대체합니다.
        self.layers.append(Layer("comp_+_top", "COMPONENT", "BOARD", "POSITIVE", 1))
        self.layers.append(Layer("top", "SIGNAL", "BOARD", "POSITIVE", 2))
        self.layers.append(Layer("bottom", "SIGNAL", "BOARD", "POSITIVE", 3))
        self.layers.append(Layer("comp_+_bot", "COMPONENT", "BOARD", "POSITIVE", 4))

    def parse_eda_data(self, step_name: str):
        """steps/{step}/eda/data 파일을 파싱하여 패키지(PKG) 정보 구축"""
        # 실제 파일 파싱 로직 (간소화됨)
        # PKG 레코드와 PIN 레코드를 읽어 self.packages에 저장
        
        print(f"[System] Parsing EDA Data for step: {step_name}")
        
        # 예시 패키지 데이터 생성 (DIP14, SOIC8 등)
        # 실제로는 파일을 읽어서 `PKG` 키워드와 `PIN` 키워드를 해석해야 함
        
        # Sample Package 1: SOIC-8
        pkg_soic8 = Package("SOIC8", 1.27, BoundBox(-2.5, -2.0, 2.5, 2.0))
        # 핀 추가 (간단한 예시 좌표)
        pkg_soic8.pins["1"] = PinDef("1", -2.0, -1.5, "S", 1)
        pkg_soic8.pins["2"] = PinDef("2", -1.0, -1.5, "S", 2)
        pkg_soic8.pins["8"] = PinDef("8", -2.0, 1.5, "S", 8)
        self.packages["SOIC8"] = pkg_soic8

        # Sample Package 2: 0603 Resistor
        pkg_0603 = Package("R0603", 0.0, BoundBox(-0.8, -0.4, 0.8, 0.4))
        pkg_0603.pins["1"] = PinDef("1", -0.7, 0.0, "S", 1)
        pkg_0603.pins["2"] = PinDef("2", 0.7, 0.0, "S", 2)
        self.packages["R0603"] = pkg_0603

    def parse_components(self, step_name: str, layer_name: str):
        """
        steps/{step}/layers/{layer}/components 파일을 파싱하여 
        배치된 부품(CMP) 정보 구축
        """
        print(f"[System] Parsing Components for layer: {layer_name}")
        
        # 실제 파일 파싱 로직 대신 예시 데이터 생성
        # CMP 레코드 구조: CMP <pkg_ref> <x> <y> <rot> <mirror> <ref_des> <part_name>
        
        if "top" in layer_name:
            # Top 면 부품
            c1 = Component("U1", "MCU", "SOIC8", 10.0, 10.0, 0.0, False, layer_name)
            c2 = Component("R1", "10k", "R0603", 15.0, 10.0, 90.0, False, layer_name)
            self.components.extend([c1, c2])
        elif "bot" in layer_name:
            # Bottom 면 부품 (Mirror True)
            c3 = Component("C1", "100nF", "R0603", 12.0, 12.0, 0.0, True, layer_name)
            self.components.append(c3)

    def link_data(self):
        """파싱 후 Component와 Package 정보를 연결"""
        for comp in self.components:
            if comp.package_name in self.packages:
                comp.package_ref = self.packages[comp.package_name]
            else:
                print(f"[Warning] Package {comp.package_name} not found for {comp.ref_des}")

# ==========================================
# 3. PCB 분석 및 계산기 (Analysis & Calculator)
# 거리 계산 및 설계 규칙 검토
# ==========================================

class PCBCalculator:
    @staticmethod
    def distance(p1: Point, p2: Point) -> float:
        """두 점 사이의 유클리드 거리 계산"""
        return math.sqrt((p1.x - p2.x)**2 + (p1.y - p2.y)**2)

    @staticmethod
    def get_min_pin_to_pin_distance(comp1: Component, comp2: Component) -> float:
        """두 부품 간 핀 대 핀 최단 거리 계산 (O(N*M) - 최적화 필요 가능)"""
        pins1 = comp1.get_pin_absolute_coordinates()
        pins2 = comp2.get_pin_absolute_coordinates()
        
        min_dist = float('inf')
        
        for p1 in pins1.values():
            for p2 in pins2.values():
                d = PCBCalculator.distance(p1, p2)
                if d < min_dist:
                    min_dist = d
        return min_dist

    @staticmethod
    def check_clearance(comp1: Component, comp2: Component, limit: float) -> bool:
        """이격 거리 규칙 검토"""
        dist = PCBCalculator.get_min_pin_to_pin_distance(comp1, comp2)
        return dist >= limit

# ==========================================
# 4. 시각화 및 UI (Visualization)
# Matplotlib을 이용한 Interactive Viewer
# ==========================================

class PCBViewer:
    def __init__(self, parser: ODBParser):
        self.parser = parser
        self.fig, self.ax = plt.subplots(figsize=(10, 8))
        self.selected_annotation = None

    def draw_component(self, comp: Component):
        """부품을 Plot에 그리기"""
        if not comp.package_ref:
            return

        # 부품 외곽선 (간단히 Bounding Box로 표현)
        # 실제로는 회전을 고려하여 Polygon으로 그려야 정확함
        w = comp.package_ref.bbox.width
        h = comp.package_ref.bbox.height
        
        # 중심 기준 회전 처리를 위해 Rectangle 대신 Polygon 사용 권장되나
        # 시각화 단순화를 위해 여기서는 중심점과 핀만 강조
        
        color = 'blue' if 'top' in comp.layer_name else 'red'
        marker = 'o' if not comp.mirror else 's'
        
        # 부품 중심 표시
        self.ax.plot(comp.x, comp.y, marker=marker, color=color, markersize=5, picker=5, label='Component')
        
        # 부품 Text (Ref Des)
        self.ax.text(comp.x, comp.y + 0.5, comp.ref_des, color=color, fontsize=9, ha='center')

        # 핀 표시
        abs_pins = comp.get_pin_absolute_coordinates()
        for pin_name, p_point in abs_pins.items():
            self.ax.plot(p_point.x, p_point.y, '.', color='black', markersize=2)

    def on_pick(self, event):
        """마우스 클릭 이벤트 핸들러"""
        mouse_point = Point(event.mouseevent.xdata, event.mouseevent.ydata)
        
        # 가장 가까운 부품 찾기
        closest_comp = None
        min_dist = float('inf')

        for comp in self.parser.components:
            dist = PCBCalculator.distance(mouse_point, Point(comp.x, comp.y))
            if dist < 2.0: # 클릭 반경 허용치
                if dist < min_dist:
                    min_dist = dist
                    closest_comp = comp
        
        if closest_comp:
            self.show_details(closest_comp)

    def show_details(self, comp: Component):
        """선택된 부품 상세 정보 표시"""
        if self.selected_annotation:
            self.selected_annotation.remove()
        
        info_text = (
            f"Ref: {comp.ref_des}\n"
            f"Part: {comp.part_name}\n"
            f"Pkg: {comp.package_name}\n"
            f"Pos: ({comp.x:.2f}, {comp.y:.2f})\n"
            f"Rot: {comp.rotation}\n"
            f"Layer: {comp.layer_name}\n"
            f"Orient: {comp.package_ref.get_orientation() if comp.package_ref else 'N/A'}"
        )
        
        self.selected_annotation = self.ax.annotate(
            info_text, 
            xy=(comp.x, comp.y), 
            xytext=(comp.x + 2, comp.y + 2),
            arrowprops=dict(facecolor='black', shrink=0.05),
            bbox=dict(boxstyle="round", fc="w")
        )
        self.fig.canvas.draw()
        print(f"[Info] Selected Component: {comp.ref_des} ({comp.layer_name})")

    def show(self):
        """뷰어 실행"""
        self.ax.set_title("ODB++ PCB Viewer (Blue: TOP, Red: BOTTOM)")
        self.ax.set_xlabel("X Coordinate")
        self.ax.set_ylabel("Y Coordinate")
        self.ax.grid(True)
        self.ax.set_aspect('equal')

        # 모든 부품 그리기
        for comp in self.parser.components:
            self.draw_component(comp)

        # 이벤트 연결
        self.fig.canvas.mpl_connect('button_press_event', self.on_pick)
        plt.show()

# ==========================================
# 5. 메인 실행 (Main Execution)
# ==========================================

def main():
    # 1. 시스템 초기화 및 데이터 로드 가상 시나리오
    print("=== ODB++ PCB Automation System Started ===")
    
    # 실제 환경에서는 폴더 경로를 입력받습니다.
    # odb_path = "./my_design.tgz" 
    odb_system = ODBParser(odb_path="dummy_path")

    # 2. 파싱 시뮬레이션
    odb_system.parse_matrix()
    odb_system.parse_eda_data("step_1")
    odb_system.parse_components("step_1", "comp_+_top")
    odb_system.parse_components("step_1", "comp_+_bot")
    odb_system.link_data()

    # 3. 자동화 검토 기능 예시 (Pin-to-Pin 거리 계산)
    if len(odb_system.components) >= 2:
        c1 = odb_system.components[0]
        c2 = odb_system.components[1]
        dist = PCBCalculator.get_min_pin_to_pin_distance(c1, c2)
        print(f"\n[Analysis] Min Distance between {c1.ref_des} and {c2.ref_des}: {dist:.4f}")
        
        is_safe = PCBCalculator.check_clearance(c1, c2, limit=5.0)
        print(f"[DRC Check] Clearance > 5.0? {'PASS' if is_safe else 'FAIL'}")

    # 4. 시각화 실행
    print("\n[Visualizer] Launching Viewer... (Click components for details)")
    viewer = PCBViewer(odb_system)
    viewer.show()

if __name__ == "__main__":
    main()