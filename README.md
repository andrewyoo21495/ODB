# ODB++ PCB Data Processing System

A Python-based system for parsing, visualizing, and running automated checklist checks on ODB++ PCB design files.

> Based on **ODB++ Design Format Specification 8.1**

---

## Table of Contents

1. [Overview](#1-overview)
2. [Project Structure](#2-project-structure)
3. [Setup & Installation](#3-setup--installation)
4. [Quick Start](#4-quick-start)
5. [CLI Reference](#5-cli-reference)
6. [Module Deep-Dive](#6-module-deep-dive)
   - [models.py](#61-modelspy--data-classes)
   - [odb_reader.py](#62-odb_readerpy--loading-odb-files)
   - [parsers/matrix_parser.py](#63-parsersmatrix_parserpy)
   - [parsers/features_parser.py](#64-parsersfeatures_parserpy)
   - [parsers/component_parser.py](#65-parserscomponent_parserpy)
   - [parsers/eda_parser.py](#66-parserseda_parserpy)
   - [parsers/symbol_resolver.py](#67-parserssymbol_resolverpy)
   - [visualizer.py](#68-visualizerpy--pcb-visualization)
   - [checklist/](#69-checklist--automated-checking)
7. [Writing Custom Rules](#7-writing-custom-rules)
8. [ODB++ File Format Reference](#8-odb-file-format-reference)
9. [Extending the System](#9-extending-the-system)

---

## 1. Overview

This system processes ODB++ archives (`.tgz` or `.zip`) or extracted directories and provides:

| Capability | Description |
|---|---|
| **Parsing** | Reads matrix, features, component, and EDA files into typed Python objects |
| **Visualization** | Renders per-layer and full-board PNG images using Matplotlib |
| **Checklist Automation** | Runs configurable rules against the parsed model; exports results to Excel |

The data flow is:

```
ODB++ archive / directory
         |
    [ODBReader]
         |
  [MatrixParser] --> Layer list
  [FeaturesParser] --> Pads, Lines, Arcs, Surfaces per layer
  [ComponentParser] --> Components + Pins per layer
  [EDAParser] --> Nets, connectivity
         |
     ODBModel
      /      \
[PCBVisualizer]  [RuleRegistry]
      |                |
  PNG files      [ExcelReporter]
                  .xlsx report
```

---

## 2. Project Structure

```
ODB/
├── models.py                    # All data classes (ODBModel, Layer, Pad, ...)
├── odb_reader.py                # Top-level loader — .tgz / .zip / directory
├── visualizer.py                # PCBVisualizer — Matplotlib rendering
├── main.py                      # CLI entry point
├── requirements.txt             # pip dependencies
│
├── parsers/
│   ├── __init__.py
│   ├── matrix_parser.py         # matrix/matrix --> Layer list
│   ├── features_parser.py       # layers/<l>/features --> Pad/Line/Arc/Surface/Text
│   ├── component_parser.py      # layers/<l>/components --> Component/Pin
│   ├── eda_parser.py            # steps/<s>/eda/data --> Net/connectivity
│   ├── symbol_resolver.py       # symbol name string --> geometry dict
│   └── stackup_parser.py        # matrix/stackup.xml --> physical properties
│
└── checklist/
    ├── __init__.py
    ├── rule_base.py             # RuleBase (ABC), CheckResult, CheckStatus
    ├── registry.py              # RuleRegistry — registration & batch run
    ├── reporter.py              # ExcelReporter — .xlsx output
    └── rules/
        ├── __init__.py
        ├── ckl_001.py           # CKL-001: Capacitor-Connector Y alignment
        ├── ckl_002.py           # CKL-002: Minimum component spacing
        ├── ckl_003.py           # CKL-003: Component count & breakdown
        └── ckl_004.py           # CKL-004: Polarized component orientation
```

---

## 3. Setup & Installation

### Prerequisites

- Python 3.10 or later
- A virtual environment is recommended (`.odb/` in this project)

### Activate the Virtual Environment

```bash
# Windows
.odb\Scripts\activate

# macOS / Linux
source .odb/bin/activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

| Package | Purpose |
|---|---|
| `matplotlib` | Layer visualization (PNG output) |
| `numpy` | Coordinate transforms, KDTree inputs |
| `scipy` | Spatial indexing for spacing checks |
| `shapely` | Polygon operations on Surface data |
| `openpyxl` | Excel report generation |

---

## 4. Quick Start

### Python API

```python
from odb_reader import ODBReader
from visualizer import PCBVisualizer
from checklist.registry import RuleRegistry
from checklist.reporter import ExcelReporter
from checklist.rules import (
    CapacitorConnectorOppositeRule,
    MinSpacingRule,
    ComponentCountRule,
    PolarizedComponentOrientationRule,
)

# 1. Load ODB++ data
reader = ODBReader(verbose=True)
model = reader.load('path/to/design.tgz')   # also accepts .zip or directory

print(model.product_name)   # e.g. "MyBoard_rev2"
print(model.units)          # "INCH" or "MM"
print(len(model.layers))    # number of layers

# 2. Inspect layer data
for layer in model.layers:
    ld = model.layer_data[layer.name]
    print(f"{layer.name}: {len(ld.pads)} pads, {len(ld.components)} comps")

# 3. Visualize
viz = PCBVisualizer(model)
viz.render_layer('comp_top', show_components=True)      # display single layer
viz.render_all_layers(output_path='board_layers.png')   # save all layers

# 4. Run checklist
registry = RuleRegistry()
registry.register(ComponentCountRule())
registry.register(CapacitorConnectorOppositeRule())
registry.register(MinSpacingRule(min_distance=0.2))
registry.register(PolarizedComponentOrientationRule())

results = registry.run_all(model, verbose=True)

reporter = ExcelReporter()
reporter.export(results, 'checklist.xlsx', model.product_name)
```

---

## 5. CLI Reference

```
python main.py <odb_path> [options]
```

| Option | Description |
|---|---|
| `<odb_path>` | Path to `.tgz`, `.zip`, or extracted ODB++ directory |
| `--visualize` | Render all layers to `pcb_layers.png` |
| `--layer <name>` | Render a single named layer to `layer_<name>.png` |
| `--checklist` | Run all rules, export `checklist_result.xlsx` |
| `--all` | Run both `--visualize` and `--checklist` |
| `--output <dir>` | Output directory (default: current directory) |
| `--min-spacing <n>` | Minimum component spacing threshold (default: `0.2`) |
| `--verbose` / `-v` | Print detailed parsing progress |

### Examples

```bash
# Summarize the board (layer count, feature count, etc.)
python main.py my_board.tgz

# Render all layers verbosely
python main.py my_board.tgz --visualize --verbose --output ./output

# Render only the top copper layer
python main.py my_board.tgz --layer comp_+_top --output ./output

# Run checklist with tighter spacing (0.1 inch)
python main.py my_board.tgz --checklist --min-spacing 0.1 --output ./output

# Full pipeline
python main.py my_board.tgz --all --output ./output
```

---

## 6. Module Deep-Dive

### 6.1 `models.py` — Data Classes

All parsed data is held in typed `dataclass` objects. Understanding these is key to working with the API.

#### Core Hierarchy

```
ODBModel
 ├── layers: List[Layer]
 ├── layer_data: Dict[str, LayerData]
 │    └── LayerData
 │         ├── layer: Layer
 │         ├── pads: List[Pad]
 │         ├── lines: List[Line]
 │         ├── arcs: List[Arc]
 │         ├── surfaces: List[Surface]
 │         ├── texts: List[TextFeature]
 │         └── components: List[Component]
 │              └── pins: List[Pin]
 └── nets: Dict[str, Net]
```

#### Key Fields

**`Layer`**
```python
@dataclass
class Layer:
    name: str         # e.g. "comp_+_top", "silk_top"
    layer_type: str   # SIGNAL, POWER, DRILL, SOLDER_MASK, SILK_SCREEN, COMPONENT
    polarity: str     # POSITIVE or NEGATIVE
    side: str         # TOP, BOTTOM, or INNER
    index: int        # Column number in the stackup (1 = top of stack)
    color: Optional[str] = None
```

**`Pad`** — a single pad aperture placed at a point
```python
@dataclass
class Pad:
    x: float; y: float
    symbol_name: str   # e.g. "r50", "rect100x200" — resolved by SymbolResolver
    polarity: str      # "P" = positive (copper), "N" = negative (cutout)
    rotation: float    # degrees, counter-clockwise
    mirror: bool       # True = X-axis mirrored
```

**`Component`** — placed component with pin coordinates
```python
@dataclass
class Component:
    index: int
    refdes: str        # e.g. "C400", "U1", "J10"
    x: float; y: float # Centroid in board coordinates
    rotation: float    # degrees
    mirror: bool       # True = placed on BOTTOM side
    package_ref: str   # Package name
    pins: List[Pin]
    part_number: Optional[str] = None
    value: Optional[str] = None
```

**`Surface`** — filled polygon area (copper pours, planes)
```python
@dataclass
class Surface:
    polarity: str
    islands: List[List[Tuple[float, float]]]
    # islands[0] = outer boundary vertices
    # islands[1:] = hole boundaries
```

---

### 6.2 `odb_reader.py` — Loading ODB++ Files

`ODBReader` is the single entry point. It handles decompression and orchestrates all parsers.

```python
class ODBReader:
    def load(self, path: str) -> ODBModel:
        ...
```

#### Supported Input Formats

| Format | Example |
|---|---|
| Gzip-compressed tar | `design.tgz`, `design.tar.gz` |
| ZIP archive | `design.zip` |
| Extracted directory | `./my_board/` (must contain a `matrix/` subdirectory) |

#### How It Finds the ODB++ Root

The reader walks up to two directory levels to find a directory containing a `matrix/` subdirectory — that is the ODB++ product model root.

#### Internal Parsing Order

```
load()
  1. _parse_misc()        -- misc/info: units, product name
  2. MatrixParser         -- matrix/matrix: layer definitions
  3. StackupParser        -- matrix/stackup.xml: physical properties (optional)
  4. _find_step()         -- steps/<pcb|panel|...>/
  5. EDAParser            -- steps/<step>/eda/data: nets
  6. FeaturesParser       -- steps/<step>/layers/<layer>/features (per layer)
  7. ComponentParser      -- steps/<step>/layers/<layer>/components (per layer)
  8. EDAParser.resolve_pin_nets()  -- link Pin.net_name from net index
```

---

### 6.3 `parsers/matrix_parser.py`

Parses the `matrix/matrix` text file which defines every layer in the stackup.

#### File Format Handled

```
STEP=pcb

COL 1
LAYER=comp_+_top
CONTEXT=BOARD
TYPE=COMPONENT
POLARITY=POSITIVE

COL 2
LAYER=silk_top
TYPE=SILK_SCREEN
POLARITY=POSITIVE
...
```

Each `COL <n>` block becomes one `Layer` object. The column number is the stack index (1 = topmost).

#### Side Detection Logic

Because the `matrix/matrix` file does not always contain an explicit SIDE field, the parser uses a two-pass heuristic:

**Pass 1 — Name-based hints:**

| Name pattern | Assigned side |
|---|---|
| Contains `top`, `_t_`, `comp_top`, etc. | `TOP` |
| Contains `bot`, `bottom`, `comp_bot`, etc. | `BOTTOM` |

**Pass 2 — Stack position** (for layers without a detected name hint):

- First SIGNAL/COMPONENT layer in column order → `TOP`
- Last SIGNAL/COMPONENT layer → `BOTTOM`
- All between → `INNER`
- DRILL → `INNER`

---

### 6.4 `parsers/features_parser.py`

The most complex parser. Processes the binary-text `features` file for each layer into geometry objects.

#### File Structure

```
UNITS=INCH
ID=10
$0 r50           <-- symbol table: index 0 = "r50" (round, 50 mil diameter)
$1 rect100x200   <-- symbol table: index 1 = rectangle 100x200
@0 .comp_name    <-- attribute name table
&0 U1            <-- attribute string table (value for attribute 0)

P  0.5 0.5 0 P 0 0         <-- Pad record
L  0.0 0.0 1.0 0.0 0 P     <-- Line record
A  1.0 0.0 0.0 1.0 0.0 0.0 0 P Y   <-- Arc record
S  P                         <-- Surface start
OB 0.0 0.0 I                 <-- Outline begin (I=island)
OC 1.0 0.0                   <-- Outline corner
OC 1.0 1.0
OC 0.0 1.0
OS                           <-- Outline end
SE                           <-- Surface end
```

#### Record Formats

| Record | Token Layout | Notes |
|---|---|---|
| `P` (Pad) | `P x y sym_idx pol [dcode] orient` | `sym_idx` references the `$` table |
| `L` (Line) | `L xs ys xe ye sym_idx pol` | Defines a stroked line with width from symbol |
| `A` (Arc) | `A xs ys xe ye xc yc sym_idx pol cw` | `cw` = `Y` (clockwise) or `N` |
| `S` (Surface start) | `S pol` | Followed by `OB`/`OC`/`OS` outline records |
| `OB` | `OB x y [I\|H]` | Outline begin; `I` = island, `H` = hole |
| `OC` | `OC x y` | Outline corner vertex |
| `OS` | `OS` | Closes and stores the current outline |
| `SE` | `SE` | Ends the Surface; stores it in `LayerData` |
| `T` (Text) | `T x y font pol orient xsize ysize width 'text'` | |

#### `decode_orient()` — Orientation Decoding

```python
def decode_orient(tokens: List[str], start_idx: int) -> Tuple[float, bool, int]:
    """Returns (angle_degrees, mirror_flag, tokens_consumed)."""
```

ODB++ encodes rotation/mirror in two formats:

| Mode value | Meaning | Example token(s) |
|---|---|---|
| `0` | 0°, no mirror | `0` |
| `1` | 90°, no mirror | `1` |
| `2` | 180°, no mirror | `2` |
| `3` | 270°, no mirror | `3` |
| `4` | 0°, mirrored | `4` |
| `5` | 90°, mirrored | `5` |
| `6` | 180°, mirrored | `6` |
| `7` | 270°, mirrored | `7` |
| `8 <angle>` | Arbitrary angle, no mirror | `8 45.0` |
| `9 <angle>` | Arbitrary angle, mirrored | `9 135.0` |

Modes 0–7 consume **1 token**; modes 8–9 consume **2 tokens**.

#### Attribute Stripping

Attribute references are appended after a semicolon and are stripped before parsing:

```
P 0.500 0.500 0 P 0 0;1=2;3   -->   P 0.500 0.500 0 P 0 0
```

---

### 6.5 `parsers/component_parser.py`

Parses the `components` file. Each `CMP` record defines one placed component, followed by `TOP` or `BOT` records for each pin.

#### File Format

```
CMP 0  1.200 3.400  0.0  N  U1  SOIC-8
TOP 0  1.100 3.300  0.0  N  2  0  1
TOP 1  1.300 3.300  0.0  N  5  0  2
...
CMP 1  5.000 2.000  90.0 Y  C400  CAP0402
BOT 0  5.000 2.000  90.0 N  12  0  1
```

#### CMP Record Fields

| Field | Description |
|---|---|
| `idx` | Component index (0-based) |
| `x`, `y` | Centroid in board coordinates |
| `rot` | Rotation in degrees (counter-clockwise) |
| `mirror` | `Y` = bottom side, `N` = top side |
| `refdes` | Reference designator (e.g., `C400`, `U1`) |
| `pkg_ref` | Package/footprint name |

#### TOP/BOT Record Fields

| Field | Description |
|---|---|
| `pin_idx` | Pin ordinal (for ordering only) |
| `x`, `y` | Pin center in board coordinates |
| `rot` | Pin rotation |
| `mirror` | Pin-level mirror flag |
| `net_idx` | Index into the net table (resolved to name by EDAParser) |
| `subnet_idx` | Subnet index |
| `pin_num` | Pin number string (e.g., `"1"`, `"A3"`) |

---

### 6.6 `parsers/eda_parser.py`

Parses the `eda/data` file and provides a `net_idx_to_name` mapping used to annotate `Pin.net_name`.

#### Handled Records

| Record | Description |
|---|---|
| `NET <name>` | Defines a net; assigned sequential index |
| `PKG <name> <num_pins>` | Package definition |
| `PIN <pin_num> <x> <y>` | Pin position within a package |
| `SNT <subnet_name>` | Subnet record (noted, not deeply processed) |

#### Post-processing — `resolve_pin_nets()`

After parsing components, call this to fill in `Pin.net_name`:

```python
eda_parser = EDAParser()
nets, net_idx_to_name = eda_parser.parse('eda/data')
eda_parser.resolve_pin_nets(component_list, net_idx_to_name)
```

---

### 6.7 `parsers/symbol_resolver.py`

Converts ODB++ symbol name strings into geometry parameter dictionaries via regex pattern matching.

#### Standard Symbol Patterns

| Symbol Pattern | Returned Dict |
|---|---|
| `r<d>` | `{'type': 'circle', 'diameter': d}` |
| `sq<s>` | `{'type': 'rect', 'w': s, 'h': s}` |
| `rect<w>x<h>` | `{'type': 'rect', 'w': w, 'h': h}` |
| `oval<w>x<h>` | `{'type': 'oval', 'w': w, 'h': h}` |
| `di<w>x<h>` | `{'type': 'diamond', 'w': w, 'h': h}` |
| `oct<w>x<h>x<cx>x<cy>` | `{'type': 'octagon', 'w': w, 'h': h, 'cx': cx, 'cy': cy}` |
| `hex_l<w>x<h>x<r>` | `{'type': 'hexagon', 'w': w, 'h': h, 'r': r}` |
| `donut_r<od>x<id>` | `{'type': 'donut_round', 'od': od, 'id': id}` |
| `rndrect<w>x<h>x<r>` | `{'type': 'rndrect', 'w': w, 'h': h, 'r': r}` |

User-defined symbols (found under `symbols/<name>/features`) return:
```python
{'type': 'user_defined', 'name': name, 'features_path': '...'}
```

#### Usage

```python
from parsers.symbol_resolver import SymbolResolver

sr = SymbolResolver(symbols_dir='/path/to/odb/symbols')
info = sr.resolve('rect100x200')
# --> {'type': 'rect', 'w': 100.0, 'h': 200.0}

lw = SymbolResolver.get_line_width(info)
# --> 100.0  (min of w, h)
```

Results are **cached** internally — each name is resolved only once.

---

### 6.8 `visualizer.py` — PCB Visualization

`PCBVisualizer` renders `ODBModel` data onto Matplotlib axes.

#### Layer Color Scheme

Colors are assigned per `layer_type` and `side`:

| Type | TOP | BOTTOM | INNER |
|---|---|---|---|
| SIGNAL | `#CC0000` (red) | `#0000CC` (blue) | `#CC6600` (orange) |
| SOLDER_MASK | `#00CC44` | `#009933` | |
| SILK_SCREEN | `#FFFFFF` | `#FFFF00` | |
| DRILL | `#888888` (grey) | | |
| COMPONENT | `#FF88FF` | `#88FFFF` | |

Background is `#1a1a1a` (near-black).

#### Rendering Pipeline per Layer

```
render_layer()
  1. _draw_surfaces()    -- PathPatch polygons (copper pours)
  2. _draw_lines()       -- ax.plot() with symbol-derived line width
  3. _draw_arcs()        -- Arc converted to polyline via _arc_to_polyline()
  4. _draw_pads()        -- Circle / Rectangle / Ellipse / Polygon patches
  5. _draw_texts()       -- ax.text() with rotation
  6. _draw_components()  -- refdes labels (white, with black background box)
```

#### Arc-to-Polyline Conversion

Arcs are approximated as 32-segment polylines:

```python
@staticmethod
def _arc_to_polyline(arc: Arc, segments: int = 32) -> List[Tuple[float, float]]:
    """
    Calculates center, radius, and angular sweep from start/end/center points.
    Handles both clockwise and counter-clockwise winding.
    """
```

#### Negative Polarity

Features with `polarity == 'N'` are drawn in the background color (`#1a1a1a`), visually erasing underlying copper — matching ODB++'s negative polarity semantics.

---

### 6.9 `checklist/` — Automated Checking

#### CheckStatus & CheckResult

```python
class CheckStatus(Enum):
    PASS    = 'PASS'     # Rule passed
    FAIL    = 'FAIL'     # Violation found
    WARNING = 'WARNING'  # Potential issue, not a hard failure
    SKIP    = 'SKIP'     # Rule not applicable to this design
```

```python
@dataclass
class CheckResult:
    rule_id:   str           # e.g. "CKL-001"
    rule_name: str           # Human-readable name
    status:    CheckStatus
    message:   str           # Summary message
    details:   Optional[List]  # List of specific violation strings
```

#### RuleRegistry

```python
registry = RuleRegistry()
registry.register(MyRule())          # Add one rule
registry.register_all([r1, r2, r3]) # Add multiple at once

results = registry.run_all(model, verbose=True)  # Run all, print each result

summary = RuleRegistry.summary(results)
# --> {'PASS': 3, 'FAIL': 1, 'WARNING': 0, 'SKIP': 0}
```

Rules that raise unhandled exceptions are caught and returned as `FAIL` with the exception message — preventing one broken rule from stopping the others.

#### Built-in Rules

| Rule ID | Class | What It Checks |
|---|---|---|
| CKL-001 | `CapacitorConnectorOppositeRule` | TOP capacitors horizontally aligned with BOTTOM connectors (Y tolerance) |
| CKL-002 | `MinSpacingRule` | Center-to-center distance < threshold for any two components on the same side |
| CKL-003 | `ComponentCountRule` | Board has components; reports count by prefix |
| CKL-004 | `PolarizedComponentOrientationRule` | Diodes/LEDs: flags suspicious uniform rotation |

#### ExcelReporter

Writes a two-sheet `.xlsx` file:

- **Sheet 1: "Checklist Results"** — one row per rule with color-coded status cells
- **Sheet 2: "Summary"** — product name, timestamp, PASS/FAIL/WARNING/SKIP totals

| Status | Cell Color |
|---|---|
| PASS | Green `#00CC44` |
| FAIL | Red `#CC0000` |
| WARNING | Amber `#FFAA00` |
| SKIP | Grey `#888888` |

---

## 7. Writing Custom Rules

Create a new file under `checklist/rules/` and subclass `RuleBase`:

```python
# checklist/rules/ckl_005.py
from checklist.rule_base import RuleBase, CheckResult
from models import ODBModel

class NoUnplacedComponentsRule(RuleBase):
    rule_id   = 'CKL-005'
    rule_name = 'No Unplaced Components'
    description = 'Checks that every component has a valid x,y position.'

    def check(self, model: ODBModel) -> CheckResult:
        unplaced = []
        for ld in model.layer_data.values():
            for comp in ld.components:
                if comp.x == 0.0 and comp.y == 0.0:
                    unplaced.append(comp.refdes)

        if unplaced:
            return self._fail(
                f'{len(unplaced)} component(s) at origin (possibly unplaced)',
                unplaced,
            )
        return self._pass()
```

Then register it:

```python
from checklist.rules.ckl_005 import NoUnplacedComponentsRule

registry = RuleRegistry()
registry.register(NoUnplacedComponentsRule())
```

### Helper Methods Available in `RuleBase`

| Method | Returns |
|---|---|
| `self._pass(message)` | `CheckResult` with status `PASS` |
| `self._fail(message, details)` | `CheckResult` with status `FAIL` |
| `self._warn(message, details)` | `CheckResult` with status `WARNING` |
| `self._skip(reason)` | `CheckResult` with status `SKIP` |
| `self._get_comps_by_prefix(model, ['C', 'D'], side='TOP')` | Filtered component list |
| `self._all_components(model, side='BOTTOM')` | All components on a side |

---

## 8. ODB++ File Format Reference

### Directory Layout Expected

```
<product_model>/
  misc/
    info              # UNITS=, PRODUCT_MODEL_NAME=
    attrlist          # Global attribute definitions
  matrix/
    matrix            # Layer definitions (COL blocks)
    stackup.xml       # Physical stackup (optional)
  steps/
    pcb/              # (or panel, or any step name)
      eda/
        data          # NET, PKG, PIN, CMP records
      layers/
        <layer_name>/
          features    # Pad, Line, Arc, Surface, Text records
          components  # CMP, TOP/BOT pin records
  symbols/
    <symbol_name>/
      features        # User-defined symbol geometry
  fonts/
  wheels/
```

### Polarity Semantics

ODB++ supports positive and negative polarity for every feature:

- **Positive (`P`)**: Adds copper (or silk, or mask opening)
- **Negative (`N`)**: Removes copper — drawn in background color, acting as an eraser over previous positive features

Surfaces follow the same rule: a negative Surface punches a hole through any underlying positive Surface.

### Units

Units are declared in `misc/info` as `UNITS=INCH` or `UNITS=MM`. All coordinate values in `features` and `components` files use these same units. The `ODBModel.units` field stores the resolved value.

---

## 9. Extending the System

### Adding a New Parser

1. Create `parsers/my_parser.py` with a class exposing a `parse(file_path) -> <result>` method.
2. Import and call it from `odb_reader.py` inside `_build_model()`.
3. Export it from `parsers/__init__.py`.

### Adding New Symbol Types

Edit `parsers/symbol_resolver.py` and add a new regex branch inside `_parse_standard()`:

```python
# Trapezoid: trap<w1>x<w2>x<h>
m = re.match(r'^trap([\d.]+)x([\d.]+)x([\d.]+)$', n)
if m:
    return {'type': 'trapezoid',
            'w1': float(m.group(1)), 'w2': float(m.group(2)),
            'h': float(m.group(3))}
```

Then handle the new `'type'` value in `visualizer.py`'s `_make_pad_patch()`.

### Interactive Visualization

The `PCBVisualizer` returns Matplotlib `Axes` objects, so you can layer on any standard Matplotlib functionality:

```python
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(20, 15))
viz.render_layer('comp_+_top', ax=ax, show_components=True)

# Highlight a specific component
comp = next(c for ld in model.layer_data.values()
            for c in ld.components if c.refdes == 'U1')
ax.plot(comp.x, comp.y, 'yo', markersize=12, label='U1')
ax.legend()

plt.show()
```

---

*For questions or issues, refer to the `ODB_System_Design.md` for the full specification rationale.*
