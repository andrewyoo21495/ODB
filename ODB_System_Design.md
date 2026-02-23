# ODB++ Based PCB Data Processing System
## Design & Implementation Guide
### Visualization Program · Checklist Automation Program

> Based on ODB++ Design Format Specification 8.1

---

## 1. Understanding the ODB++ File Structure

ODB++ is a hierarchical file system structure for transferring PCB design data. The entire product model is organized as a directory tree, typically distributed as a compressed `.tgz` or `.zip` archive.

### 1.1 Directory Hierarchy

| Path | Role |
|------|------|
| `<product_model>/` | Root directory (entire product model) |
| `misc/` | Global information (units, info, attrlist, metadata.xml) |
| `matrix/` | Layer stackup definition (matrix file, stackup.xml) |
| `steps/<step_name>/` | Step-level data (typically 'pcb' or 'panel') |
| `steps/<step>/layers/<layer>/` | Per-layer feature data (features, components, etc.) |
| `steps/<step>/eda/` | EDA data (data file: nets, components, packages) |
| `symbols/` | User-defined symbol shape definitions |
| `fonts/` | Font definitions |
| `wheels/` | Drill symbol definitions |

### 1.2 Key File Roles

#### matrix/matrix — Layer Definition
Defines the complete list of all PCB layers, their order, type (SIGNAL/POWER/DRILL/SOLDER_MASK, etc.), and polarity (POSITIVE/NEGATIVE). Layer ordering and color mapping for visualization are determined from this file.

#### steps/\<step\>/layers/\<layer\>/features — Feature Data
The core file where actual geometry data (pads, lines, arcs, surfaces, text) for each layer is stored. This is the primary data source for visualization.

#### steps/\<step\>/layers/\<layer\>/components — Component Placement
Contains the position (x, y), rotation angle, mirror flag, reference designator, and pin coordinates of components placed on that layer (TOP/BOTTOM). This is the primary data source for checklist automation.

#### steps/\<step\>/eda/data — Netlist & EDA
EDA data containing NET, CMP (component), PKG (package), PIN, and SNT (subnet) records. Used for electrical connectivity information and component-to-package mapping.

---

## 2. Python Parser Design

### 2.1 Overall Parser Architecture

ODB++ files are a mix of structured text-based Line Record format and XML format. Separating the parser into modules ensures maintainability and extensibility.

| Module | Responsible File | Output Data |
|--------|-----------------|-------------|
| `ODBReader` | Entry point, decompression, directory traversal | ODBModel object |
| `MatrixParser` | matrix/matrix | Layer list + type information |
| `FeaturesParser` | layers/\<layer\>/features | Pad/Line/Arc/Surface/Text lists |
| `ComponentParser` | layers/\<layer\>/components | Component + Pin lists |
| `EDAParser` | eda/data | Net/Package/Pin connection info |
| `SymbolResolver` | symbols/ + standard spec symbols | Symbol → geometry conversion |
| `StackupParser` | matrix/stackup.xml | Layer physical properties |

### 2.2 Features File Parsing

The features file consists of a header section followed by a record section.

#### File Structure

```
UNITS=INCH
ID=<id>
$0 r120          # Symbol index table
$1 rect20x60 M
@0 .smd          # Attribute name table
&0 some_string   # Attribute string table
# Record section
P 1.0 2.0 0 P 4 0          # Pad record
L 0.0 0.0 1.0 1.0 1 P 0 0  # Line record
A xs ys xe ye xc yc sym P 0 Y  # Arc record
S P 0              # Surface start
OB x y I           # Outline begin
OS                 # Outline end
SE                 # Surface end
```

#### Record Type Parsing Rules

| Record | Format Summary | Key Fields |
|--------|---------------|------------|
| `P` (Pad) | `P x y apt_def pol dcode orient_def` | x,y position, symbol index, polarity, rotation/mirror |
| `L` (Line) | `L xs ys xe ye sym_num pol dcode` | Start/end points, symbol (line width), polarity |
| `A` (Arc) | `A xs ys xe ye xc yc sym pol dcode cw` | Start/end/center points, direction (CW/CCW) |
| `S` (Surface) | `S pol dcode` | Polygon area, island + hole structure |
| `T` (Text) | `T x y font pol orient xsize ysize width 'text'` | Position, font, orientation, size, string |
| `OB/OC` | `OB x y type` | Surface outline begin (I=island) |
| `OS` | `OS` | Outline end |
| `SE` | `SE` | Surface end |

#### orient_def Decoding

Orientation values come in two formats: legacy (0–7) and new-style (8/9 + angle).

```python
def decode_orient(orient_str):
    parts = orient_str.split()
    mode = int(parts[0])
    if mode <= 7:  # Legacy: 45-degree increments
        angles = [0, 90, 180, 270, 0, 90, 180, 270]
        mirror = mode >= 4
        return angles[mode], mirror
    else:  # New-style: arbitrary angle
        angle = float(parts[1]) if len(parts) > 1 else 0.0
        mirror = (mode == 9)
        return angle, mirror
```

### 2.3 Component File Parsing

The CMP record holds component placement information, and subsequent TOP/BOT records represent the position of each pin.

```
CMP <idx> <x> <y> <rot> <mirror> <refdes> <pkg_ref>
TOP <pin_idx> <x> <y> <rot> <mirror> <net_idx> <subnet_idx> <pin_num>
```

| Field | Description |
|-------|-------------|
| `idx` | Component index (0-based) |
| `x, y` | Component origin coordinates (inches or mm) |
| `rot` | Rotation angle (degrees, counter-clockwise) |
| `mirror` | Y = mirrored (bottom placement), N = not mirrored (top placement) |
| `refdes` | Reference designator (e.g., C400, U1, J10) |
| `pkg_ref` | Package reference (symbol name) |
| `TOP/BOT` | Pin position records (TOP = top-side pins, BOT = bottom-side pins) |

### 2.4 Symbol Processing

ODB++ symbols fall into two categories: standard symbols and user-defined symbols. For visualization, symbol names must be converted into actual geometry parameters.

#### Key Standard Symbol Parsing Rules

| Symbol Pattern | Shape | Parameter Extraction |
|---------------|-------|---------------------|
| `r<d>` | Round (circle) | d = diameter |
| `rect<w>x<h>` | Rectangle | w = width, h = height |
| `oval<w>x<h>` | Oval | w = width, h = height |
| `sq<s>` | Square | s = size |
| `di<w>x<h>` | Diamond | w = width, h = height |
| `oct<w>x<h>x<cx>x<cy>` | Octagon | w,h = outer size, cx,cy = corner cut |
| `hex_l<w>x<h>x<r>` | Horizontal hexagon | w,h = size, r = corner radius |
| `donut_r<od>x<id>` | Round donut | od = outer diameter, id = inner diameter |
| `rc_tho<w>x<h>x...` | Rectangular thermal | Spoke pattern |

```python
import re

def parse_symbol(name):
    # Round
    m = re.match(r'^r([\d.]+)$', name)
    if m: return {'type': 'circle', 'diameter': float(m[1])}
    # Rectangle
    m = re.match(r'^rect([\d.]+)x([\d.]+)$', name)
    if m: return {'type': 'rect', 'w': float(m[1]), 'h': float(m[2])}
    # Oval
    m = re.match(r'^oval([\d.]+)x([\d.]+)$', name)
    if m: return {'type': 'oval', 'w': float(m[1]), 'h': float(m[2])}
    # User-defined symbol → refer to symbols/<n>/features
    return {'type': 'user_defined', 'name': name}
```

---

## 3. Python Data Model Design

Below is the Python class structure for holding parsed data. `dataclass` is used to build a clear, type-safe model.

### 3.1 Core Data Classes

```python
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

@dataclass
class Layer:
    name: str
    layer_type: str       # SIGNAL, POWER, DRILL, SOLDER_MASK, SILK_SCREEN, ...
    polarity: str         # POSITIVE, NEGATIVE
    side: str             # TOP, BOTTOM, INNER
    index: int            # Stack order
    color: Optional[str] = None

@dataclass
class Pad:
    x: float; y: float
    symbol_name: str      # Resolved symbol name
    polarity: str         # P/N
    rotation: float = 0.0
    mirror: bool = False
    attributes: dict = field(default_factory=dict)

@dataclass
class Line:
    x1: float; y1: float; x2: float; y2: float
    symbol_name: str      # Line width symbol
    polarity: str

@dataclass
class Arc:
    xs: float; ys: float  # Start point
    xe: float; ye: float  # End point
    xc: float; yc: float  # Center point
    symbol_name: str
    polarity: str
    clockwise: bool

@dataclass
class Surface:
    polarity: str
    islands: List[List[Tuple]]  # Outer polygon + holes

@dataclass
class Pin:
    pin_num: int
    x: float; y: float
    rotation: float
    net_index: int
    net_name: Optional[str] = None

@dataclass
class Component:
    index: int
    refdes: str           # e.g., C400, U1
    x: float; y: float
    rotation: float
    mirror: bool          # True = bottom side
    package_ref: str
    pins: List[Pin] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    part_number: Optional[str] = None
    value: Optional[str] = None

@dataclass
class LayerData:
    layer: Layer
    pads: List[Pad] = field(default_factory=list)
    lines: List[Line] = field(default_factory=list)
    arcs: List[Arc] = field(default_factory=list)
    surfaces: List[Surface] = field(default_factory=list)
    components: List[Component] = field(default_factory=list)

@dataclass
class ODBModel:
    product_name: str
    units: str            # INCH / MM
    layers: List[Layer]
    layer_data: dict      # {layer_name: LayerData}
    nets: dict            # {net_name: [Pin, ...]}
```

---

## 4. Layer Visualization Program

### 4.1 Visualization Library Selection

| Library | Pros | Cons | Recommended Use |
|---------|------|------|-----------------|
| Matplotlib | General-purpose, simple static output | Slow for large feature sets | Prototyping, reports |
| Shapely + Matplotlib | Strong complex polygon handling | Limited interactivity | Surface rendering |
| PyQtGraph | Fast rendering, zoom/pan | Qt dependency | Real-time interactive |
| Plotly | Web-based, easy sharing | No PCB-specific features | Sharing results |
| Vispy/OpenGL | Ultra-fast for large datasets | Complex to implement | Millions of features |

> **Recommended**: Dual support structure — Matplotlib (static/basic) + PyQtGraph or Plotly (interactive)

### 4.2 Symbol Rendering Implementation

#### Standard Symbol → Matplotlib Patch Conversion

```python
from matplotlib.patches import Circle, Rectangle, Ellipse, Polygon
from matplotlib.transforms import Affine2D
import numpy as np

def symbol_to_patch(sym_info, x, y, rotation, mirror, polarity, layer_color):
    color = layer_color if polarity == 'P' else 'white'
    t = Affine2D().rotate_deg(rotation)
    if mirror:
        t = t.scale(-1, 1)
    t = t.translate(x, y)

    stype = sym_info['type']
    if stype == 'circle':
        d = sym_info['diameter']
        patch = Circle((0, 0), d / 2, color=color)
    elif stype == 'rect':
        w, h = sym_info['w'], sym_info['h']
        patch = Rectangle((-w / 2, -h / 2), w, h, color=color)
    elif stype == 'oval':
        w, h = sym_info['w'], sym_info['h']
        patch = Ellipse((0, 0), w, h, color=color)
    # ... handle additional symbol types
    patch.set_transform(t + ax.transData)
    return patch
```

#### Surface (Polygon) Rendering

```python
from matplotlib.patches import PathPatch
from matplotlib.path import Path

def surface_to_patch(surface, color):
    # First island is the outer boundary; remaining are holes
    verts = []
    codes = []
    for i, island in enumerate(surface.islands):
        verts.extend(island)
        codes.append(Path.MOVETO)
        codes.extend([Path.LINETO] * (len(island) - 2))
        codes.append(Path.CLOSEPOLY)
    path = Path(verts, codes)
    return PathPatch(path, facecolor=color, edgecolor='none')
```

### 4.3 Layer Visualization Class

```python
class PCBVisualizer:
    LAYER_COLORS = {
        'SIGNAL':      {'TOP': '#CC0000', 'BOTTOM': '#0000CC', 'INNER': '#CC6600'},
        'SOLDER_MASK': {'TOP': '#00CC44', 'BOTTOM': '#009933'},
        'SILK_SCREEN': {'TOP': '#FFFFFF', 'BOTTOM': '#FFFF00'},
        'DRILL':       '#888888',
        'POWER':       '#FF6600',
    }

    def __init__(self, odb_model: ODBModel):
        self.model = odb_model

    def render_layer(self, layer_name, ax=None, show_components=True):
        import matplotlib.pyplot as plt
        if ax is None:
            fig, ax = plt.subplots(figsize=(16, 12))
        ax.set_aspect('equal')
        ax.set_facecolor('#1a1a1a')

        ld = self.model.layer_data[layer_name]
        color = self._get_layer_color(ld.layer)

        # Surfaces (filled areas) first
        for surf in ld.surfaces:
            patch = surface_to_patch(surf, color)
            ax.add_patch(patch)

        # Lines
        for line in ld.lines:
            sym = parse_symbol(line.symbol_name)
            lw = sym.get('diameter', 0.01)
            ax.plot([line.x1, line.x2], [line.y1, line.y2],
                    color=color, lw=lw * 100, solid_capstyle='round')

        # Pads
        for pad in ld.pads:
            sym = parse_symbol(pad.symbol_name)
            patch = symbol_to_patch(sym, pad.x, pad.y,
                                    pad.rotation, pad.mirror,
                                    pad.polarity, color)
            ax.add_patch(patch)

        # Component overlay
        if show_components:
            for comp in ld.components:
                ax.text(comp.x, comp.y, comp.refdes,
                        color='white', fontsize=5, ha='center')
        return ax

    def render_all_layers(self, output_path=None):
        import matplotlib.pyplot as plt
        n = len(self.model.layers)
        cols = min(4, n)
        rows = (n + cols - 1) // cols
        fig, axes = plt.subplots(rows, cols, figsize=(cols * 6, rows * 5))
        for i, layer in enumerate(self.model.layers):
            ax = axes.flat[i]
            self.render_layer(layer.name, ax)
            ax.set_title(f"{layer.name} ({layer.layer_type})")
        if output_path:
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
        else:
            plt.show()
```

---

## 5. Checklist Automation Program

### 5.1 Design Overview

The checklist automation system takes an ODBModel as input, executes a set of pre-defined rules, and outputs Pass/Fail results to an Excel file.

| Component | Role |
|-----------|------|
| `RuleBase` (abstract class) | Defines the common interface for all checklist rules |
| `RuleRegistry` | Registers/manages rules and runs them in batch |
| `CheckResult` | Stores Pass/Fail/WARNING + detailed messages for each rule |
| `ExcelReporter` | Outputs results to a formatted Excel file using openpyxl |
| `SpatialIndex` | Optimizes inter-component distance calculations (rtree or KDTree) |

### 5.2 Rule-Based Class Structure

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import List

class CheckStatus(Enum):
    PASS    = 'PASS'
    FAIL    = 'FAIL'
    WARNING = 'WARNING'
    SKIP    = 'SKIP'      # Not applicable

@dataclass
class CheckResult:
    rule_id:   str
    rule_name: str
    status:    CheckStatus
    message:   str
    details:   list = None  # Failure locations, related component list, etc.

class RuleBase(ABC):
    rule_id:     str = ''
    rule_name:   str = ''
    description: str = ''

    @abstractmethod
    def check(self, model: 'ODBModel') -> CheckResult:
        pass

class RuleRegistry:
    def __init__(self):
        self._rules: List[RuleBase] = []

    def register(self, rule: RuleBase):
        self._rules.append(rule)

    def run_all(self, model) -> List[CheckResult]:
        return [rule.check(model) for rule in self._rules]
```

### 5.3 Checklist Rule Implementation Examples

#### Example 1: Capacitor–Connector Horizontal Alignment Check

```python
class CapacitorConnectorOppositeRule(RuleBase):
    rule_id   = 'CKL-001'
    rule_name = 'Capacitor-Connector Opposite-Side Horizontal Alignment'
    CAP_PREFIX  = ['C']        # Capacitor reference prefix
    CON_PREFIX  = ['J', 'CN']  # Connector reference prefix
    TOLERANCE_Y = 0.5          # Horizontal tolerance (mm or inch)

    def check(self, model) -> CheckResult:
        caps = self._get_comps_by_prefix(model, self.CAP_PREFIX, side='TOP')
        cons = self._get_comps_by_prefix(model, self.CON_PREFIX, side='BOTTOM')
        fails = []
        for cap in caps:
            for con in cons:
                # Check if Y-coordinate difference exceeds tolerance
                if abs(cap.y - con.y) > self.TOLERANCE_Y:
                    fails.append(
                        f'{cap.refdes} vs {con.refdes}: dy={abs(cap.y - con.y):.3f}'
                    )
        if fails:
            return CheckResult(self.rule_id, self.rule_name,
                               CheckStatus.FAIL, f'{len(fails)} violation(s)', fails)
        return CheckResult(self.rule_id, self.rule_name, CheckStatus.PASS, 'All passed')
```

#### Example 2: Minimum Component Spacing Check

```python
from scipy.spatial import KDTree
import numpy as np

class MinSpacingRule(RuleBase):
    rule_id      = 'CKL-002'
    rule_name    = 'Minimum Component Spacing'
    MIN_DISTANCE = 0.2  # inch

    def check(self, model) -> CheckResult:
        top_comps = [c for ld in model.layer_data.values()
                     for c in ld.components if not c.mirror]
        positions = np.array([[c.x, c.y] for c in top_comps])
        if len(positions) < 2:
            return CheckResult(self.rule_id, self.rule_name,
                               CheckStatus.SKIP, 'Insufficient component count')
        tree  = KDTree(positions)
        pairs = tree.query_pairs(self.MIN_DISTANCE)
        fails = [(top_comps[i].refdes, top_comps[j].refdes) for i, j in pairs]
        if fails:
            return CheckResult(self.rule_id, self.rule_name,
                               CheckStatus.FAIL, f'{len(fails)} spacing violation(s)', fails)
        return CheckResult(self.rule_id, self.rule_name, CheckStatus.PASS, 'All passed')
```

### 5.4 Excel Output

```python
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment

class ExcelReporter:
    STATUS_COLORS = {
        'PASS':    '00CC44',
        'FAIL':    'CC0000',
        'WARNING': 'FFAA00',
        'SKIP':    '888888',
    }

    def export(self, results: list, output_path: str, pcb_name: str):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Checklist Results'

        # Header row
        headers = ['ID', 'Rule Name', 'Result', 'Message', 'Details']
        for col, h in enumerate(headers, 1):
            cell = ws.cell(1, col, h)
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='1F4E79')

        # Data rows
        for row, result in enumerate(results, 2):
            ws.cell(row, 1, result.rule_id)
            ws.cell(row, 2, result.rule_name)
            status_cell = ws.cell(row, 3, result.status.value)
            color = self.STATUS_COLORS[result.status.value]
            status_cell.fill = PatternFill('solid', fgColor=color)
            status_cell.font = Font(bold=True, color='FFFFFF')
            ws.cell(row, 4, result.message)
            ws.cell(row, 5, str(result.details or ''))

        # Summary sheet
        ws2 = wb.create_sheet('Summary')
        pass_count = sum(1 for r in results if r.status.value == 'PASS')
        fail_count = sum(1 for r in results if r.status.value == 'FAIL')
        ws2['A1'] = f'PCB: {pcb_name}'
        ws2['A2'] = f'PASS: {pass_count}'
        ws2['A3'] = f'FAIL: {fail_count}'
        wb.save(output_path)
```

---

## 6. Full System Execution Flow

### 6.1 Entry Point Code

```python
from odb_reader import ODBReader
from visualizer import PCBVisualizer
from checklist import RuleRegistry, ExcelReporter
from rules import CapacitorConnectorOppositeRule, MinSpacingRule

# 1. Load ODB++ file
reader = ODBReader()
model = reader.load('path/to/design.tgz')   # Also supports .zip and directory

# 2. Visualization
viz = PCBVisualizer(model)
viz.render_layer('comp_top', show_components=True)  # Single layer
viz.render_all_layers(output_path='pcb_layers.png') # All layers

# 3. Checklist
registry = RuleRegistry()
registry.register(CapacitorConnectorOppositeRule())
registry.register(MinSpacingRule())
# ... add more rules as needed

results = registry.run_all(model)

reporter = ExcelReporter()
reporter.export(results, 'checklist_result.xlsx', model.product_name)
print(f'PASS: {sum(1 for r in results if r.status.value == "PASS")}')
print(f'FAIL: {sum(1 for r in results if r.status.value == "FAIL")}')
```

### 6.2 Package Structure

| File | Role |
|------|------|
| `odb_reader.py` | Decompression, directory traversal, parsing orchestration |
| `parsers/matrix_parser.py` | Parses matrix/matrix → Layer list |
| `parsers/features_parser.py` | Parses features file → Pad/Line/Arc/Surface/Text |
| `parsers/component_parser.py` | Parses components file → Component/Pin |
| `parsers/eda_parser.py` | Parses eda/data → Net/Package information |
| `parsers/symbol_resolver.py` | Symbol name → geometry parameter conversion |
| `models.py` | Data classes: ODBModel, Layer, Component, Pad, etc. |
| `visualizer.py` | Per-layer Matplotlib/Plotly rendering |
| `checklist/rule_base.py` | RuleBase, CheckResult, CheckStatus |
| `checklist/rules/*.py` | Individual checklist rule implementations |
| `checklist/registry.py` | RuleRegistry — rule management and batch execution |
| `checklist/reporter.py` | ExcelReporter — Excel output of results |
| `main.py` | CLI entry point |

### 6.3 Required Python Packages

| Package | Purpose |
|---------|---------|
| `matplotlib` | Per-layer static visualization |
| `shapely` | Polygon operations (Surface processing, distance calculation) |
| `numpy` | Numerical computation, coordinate transformation |
| `scipy` | KDTree-based spatial indexing (spacing checks) |
| `openpyxl` | Excel result output |
| `lxml` / `xml.etree` | XML file parsing (stackup.xml, metadata.xml) |
| `plotly` *(optional)* | Interactive web-based visualization |
| `pyqtgraph` *(optional)* | High-performance desktop GUI visualization |

---

## 7. Implementation Roadmap

| Phase | Task | Deliverable |
|-------|------|-------------|
| Phase 1 | Parse matrix → confirm layer list | Layer list output |
| Phase 2 | Parse features → basic Pad/Line/Arc/Surface handling | Simple layer visualization |
| Phase 3 | Implement standard symbol rendering (r, rect, oval first) | Accurate symbol rendering |
| Phase 4 | Parse components + map pin coordinates | Component overlay visualization |
| Phase 5 | Parse EDA (net) → pin-to-net connectivity | Net highlighting |
| Phase 6 | Build checklist Rule framework | Rule-based check execution |
| Phase 7 | Implement individual checklist rules (highest priority first) | Pass/Fail verdicts |
| Phase 8 | Implement Excel reporter | Result file output |
| Phase 9 | Performance optimization (large feature set handling) | Capable of processing real PCBs |

---

## 8. Key Implementation Considerations

### Coordinate Unit Conversion
ODB++ files use either INCH or MM units. Always check the `units` value at parse time and normalize to a single unit system internally. MM units are generally more intuitive for visualization output.

### Negative Polarity Handling
Features with Negative polarity (`N`) in ODB++ act as erasers, removing previously added features. During rendering, these should be drawn in the layer background color (or substrate color). A Negative Surface effectively punches a hole through any underlying Surface.

### Surface Island/Hole Handling
A Surface consists of one or more islands (outer boundary, clockwise winding) and their interior holes (counter-clockwise winding). These can be processed using Matplotlib's `PathPatch` or converted into Shapely's `Polygon(exterior, interiors)` structure.

### Large File Performance Optimization
Feature files for real-world PCBs can contain hundreds of thousands of features or more. Consider per-layer lazy loading, viewport-based culling (skip rendering features outside the visible area), and using Matplotlib's blitting or PyQtGraph for better performance.

### User-Defined Symbols
User-defined symbols under the `symbols/` directory have their own features file. Recursively invoke `FeaturesParser` to convert symbols into geometry, and cache results to maintain performance.

---

*Following this document and implementing each module in order will allow you to build a complete visualization and checklist automation system for real-world PCB ODB++ files.*
