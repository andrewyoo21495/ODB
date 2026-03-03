# ODB++ Processing System - Design Document

## 1. High-Level System Architecture

The system is composed of three major subsystems that share a common data foundation:

```
                        +---------------------------+
                        |     ODB++ Archive File    |
                        |  (.tgz / directory tree)  |
                        +-------------+-------------+
                                      |
                                      v
                        +-------------+-------------+
                        |        odb_loader         |
                        |  (Extract + Discover)     |
                        +-------------+-------------+
                                      |
                    +-----------------+-----------------+
                    |                 |                 |
                    v                 v                 v
          +---------+------+  +------+--------+  +-----+---------+
          |    parsers/    |  |    parsers/   |  |    parsers/   |
          | matrix_parser  |  | feature_parser|  | component_    |
          | eda_parser     |  | symbol_parser |  |   parser      |
          | profile_parser |  | font_parser   |  | netlist_parser|
          | stackup_parser |  |               |  | misc_parser   |
          +-------+--------+  +------+--------+  +------+--------+
                  |                   |                   |
                  +-------------------+-------------------+
                                      |
                                      v
                        +-------------+-------------+
                        |         models.py         |
                        |   (Dataclass definitions)  |
                        +-------------+-------------+
                                      |
                    +-----------------+-----------------+
                    |                 |                 |
                    v                 v                 v
          +---------+------+  +------+--------+  +-----+---------+
          |   JSON Cache   |  |  Visualizer   |  |   Checklist   |
          | (cache_manager)|  | (visualizer/) |  | (checklist/)  |
          +----------------+  +---------------+  +---------------+
```

### Data Flow Summary

1. **Input**: ODB++ `.tgz` archive or extracted directory
2. **Loading**: `odb_loader` extracts the archive (if needed) and discovers the directory structure
3. **Parsing**: Dedicated parsers read each file type into Python dataclass models
4. **Caching**: Parsed data is serialized to JSON files for fast subsequent access
5. **Visualization**: Renders PCB layers using matplotlib, reading from cache or parsed models
6. **Checklist**: Evaluates design rules against component/geometry data, exports results to Excel

---

## 2. Proposed Directory Structure

```
ODB/
├── data/                          # ODB++ input files (.tgz archives)
│   └── designodb_rigidflex.tgz
├── cache/                         # Generated JSON cache output
│   └── <job_name>/
│       ├── job_info.json          # misc/info data
│       ├── matrix.json            # Layer stack definition
│       ├── stackup.json           # Stackup XML data (if present)
│       ├── profile.json           # Board outline
│       ├── nets.json              # Net names and connectivity
│       ├── packages.json          # EDA package definitions
│       ├── components_top.json    # Top-side components
│       ├── components_bot.json    # Bottom-side components
│       ├── symbols/               # Resolved symbol geometries
│       │   ├── standard.json      # Standard symbol parameter cache
│       │   └── user_defined.json  # User-defined symbol features
│       └── layers/                # Per-layer feature data
│           ├── signal_1.json
│           ├── soldermask_top.json
│           └── ...
├── output/                        # Generated outputs
│   └── checklist_report.xlsx
│
├── src/                           # Source code root
│   ├── __init__.py
│   ├── models.py                  # All dataclass/data model definitions
│   ├── odb_loader.py              # Archive extraction + directory discovery
│   ├── cache_manager.py           # JSON serialization/deserialization
│   │
│   ├── parsers/                   # One parser per ODB++ file type
│   │   ├── __init__.py
│   │   ├── base_parser.py         # Shared parsing utilities
│   │   ├── matrix_parser.py       # matrix/matrix file
│   │   ├── misc_parser.py         # misc/info, misc/attrlist
│   │   ├── profile_parser.py      # step profile + layer profiles
│   │   ├── feature_parser.py      # layer features files (L/P/A/T/B/S)
│   │   ├── component_parser.py    # comp_+_top, comp_+_bot components
│   │   ├── eda_parser.py          # eda/data (PKG, NET, PIN, SNT, FID)
│   │   ├── netlist_parser.py      # netlists/cadnet/netlist
│   │   ├── symbol_resolver.py     # Standard symbol geometry generation
│   │   ├── symbol_parser.py       # User-defined symbol features
│   │   ├── font_parser.py         # fonts/standard
│   │   ├── stackup_parser.py      # matrix/stackup.xml
│   │   └── stephdr_parser.py      # step header
│   │
│   ├── visualizer/                # Layer-by-layer PCB visualization
│   │   ├── __init__.py
│   │   ├── renderer.py            # Main rendering orchestrator
│   │   ├── layer_renderer.py      # Render features (pads/lines/arcs/surfaces)
│   │   ├── symbol_renderer.py     # Render standard + user-defined symbols
│   │   ├── component_overlay.py   # Component outlines + reference designators
│   │   └── viewer.py              # Interactive matplotlib viewer (layer toggle)
│   │
│   └── checklist/                 # Automated design-rule checklist
│       ├── __init__.py
│       ├── engine.py              # Rule evaluation engine
│       ├── rule_base.py           # Base class for checklist rules
│       ├── reporter.py            # Excel report generation (openpyxl)
│       └── rules/                 # Individual rule implementations
│           ├── __init__.py
│           ├── ckl_component_alignment.py
│           ├── ckl_spacing.py
│           ├── ckl_placement.py
│           └── ...
│
├── main.py                        # CLI entry point
├── requirements.txt
└── ODB_System_Design.md           # This document
```

---

## 3. Module Responsibilities

### 3.1 `src/models.py` - Data Models

Central dataclass definitions that all modules share. No parsing logic lives here.

| Model | Purpose | Key Fields |
|-------|---------|------------|
| `JobInfo` | Product model metadata | `job_name`, `odb_version`, `units`, `creation_date`, `max_uid` |
| `MatrixStep` | Step entry in matrix | `col`, `name`, `id` |
| `MatrixLayer` | Layer entry in matrix | `row`, `name`, `context`, `type`, `polarity`, `add_type`, `start_name`, `end_name`, `form` |
| `StepHeader` | Step header data | `units`, `x_datum`, `y_datum`, `x_origin`, `y_origin`, `step_repeats[]` |
| `StepRepeat` | Step-and-repeat entry | `name`, `x`, `y`, `dx`, `dy`, `nx`, `ny`, `angle`, `flip`, `mirror` |
| `Point` | 2D coordinate | `x`, `y` |
| `Contour` | Closed polygon | `is_island`, `segments[]` (LineSegment or ArcSegment) |
| `LineSegment` | Straight segment | `end: Point` |
| `ArcSegment` | Arc segment | `end: Point`, `center: Point`, `clockwise: bool` |
| `Surface` | Polygon area | `polarity`, `contours[]` |
| `Profile` | Board/layer outline | `surface: Surface` |
| `SymbolRef` | Symbol table entry | `index`, `name`, `unit_override` (None/'I'/'M') |
| `StandardSymbol` | Parsed standard symbol | `type` (round/rect/oval/...), `params: dict` |
| `UserSymbol` | User-defined symbol | `name`, `features[]` |
| `PadRecord` | Pad feature | `x`, `y`, `symbol_idx`, `polarity`, `rotation`, `mirror`, `attributes` |
| `LineRecord` | Line feature | `xs`, `ys`, `xe`, `ye`, `symbol_idx`, `polarity`, `attributes` |
| `ArcRecord` | Arc feature | `xs`, `ys`, `xe`, `ye`, `xc`, `yc`, `symbol_idx`, `polarity`, `clockwise`, `attributes` |
| `TextRecord` | Text feature | `x`, `y`, `font`, `polarity`, `orient`, `xsize`, `ysize`, `width_factor`, `text` |
| `SurfaceRecord` | Surface feature | `polarity`, `contours[]`, `attributes` |
| `LayerFeatures` | All features in a layer | `units`, `symbols[]`, `attr_names{}`, `attr_texts{}`, `features[]` |
| `Net` | Electrical net | `name`, `index`, `subnets[]`, `attributes` |
| `Subnet` | Subnet within a net | `type` (VIA/TRC/PLN/TOP), `feature_ids[]` |
| `FeatureId` | Cross-reference | `type` (C/L/H), `layer_idx`, `feature_idx` |
| `Package` | EDA package def | `name`, `pitch`, `bbox`, `pins[]`, `outlines[]` |
| `Pin` | Pin in package | `name`, `type`, `center`, `finished_hole_size`, `electrical_type`, `mount_type` |
| `Component` | Placed component | `pkg_ref`, `x`, `y`, `rotation`, `mirror`, `comp_name`, `part_name`, `properties{}`, `toeprints[]`, `bom_data` |
| `Toeprint` | Pin placement | `pin_num`, `x`, `y`, `rotation`, `mirror`, `net_num`, `subnet_num`, `name` |
| `FontChar` | Font character def | `char`, `strokes[]` |
| `StrokeFont` | Complete font | `xsize`, `ysize`, `characters{}` |

### 3.2 `src/odb_loader.py` - Archive Extraction & Discovery

**Responsibility**: Given a `.tgz` file path or an extracted directory path, discover and validate the ODB++ structure.

| Function | Description |
|----------|-------------|
| `load(path) -> OdbJob` | Main entry: extract if `.tgz`, validate directory tree, return `OdbJob` handle |
| `extract_archive(tgz_path, dest_dir)` | Extract `.tgz` to a working directory |
| `discover_structure(root_dir) -> OdbJob` | Walk the directory tree, identify steps, layers, symbols |
| `decompress_file(path)` | Handle `.Z` (UNIX compress) files transparently |

`OdbJob` is a lightweight container holding resolved paths:
- `root_dir`, `matrix_path`, `misc_info_path`, `font_path`
- `steps: dict[str, StepPaths]` where `StepPaths` holds paths to `stephdr`, `profile`, `eda/data`, `netlists/`, and `layers/`
- `symbols: dict[str, Path]` mapping symbol names to their feature files
- `wheels: dict[str, Path]`

### 3.3 `src/parsers/base_parser.py` - Shared Utilities

Common parsing functions reused by all parsers:

| Function | Description |
|----------|-------------|
| `read_file(path) -> list[str]` | Read file, strip comments (`#` lines), handle `.Z` decompression |
| `parse_units(line) -> str` | Extract `UNITS=MM\|INCH` |
| `parse_structured_text(lines) -> dict` | Parse `KEY=VALUE` + `NAME { ... }` blocks |
| `parse_symbol_table(lines) -> list[SymbolRef]` | Parse `$N <name> [I\|M]` entries |
| `parse_attr_lookup(lines) -> (dict, dict)` | Parse `@N <name>` and `&N <value>` tables |
| `parse_attributes(attr_str) -> dict` | Decode `;0=1,2=0;ID=123` into `{attr_name: value}` |
| `parse_contour(lines, idx) -> (Contour, int)` | Parse `OB/OS/OC/OE` block, return contour + next line index |
| `parse_surface(lines, idx) -> (Surface, int)` | Parse `S ... SE` block |

### 3.4 `src/parsers/matrix_parser.py` - Matrix Parser

**Input**: `matrix/matrix` (structured text)
**Output**: `list[MatrixStep]`, `list[MatrixLayer]`

Parses `STEP { ... }` and `LAYER { ... }` blocks. Sorts layers by `ROW` for physical stacking order. Identifies layer types (SIGNAL, COMPONENT, DRILL, etc.) and flex/rigid form.

### 3.5 `src/parsers/misc_parser.py` - Miscellaneous Parser

**Input**: `misc/info`, `misc/attrlist`
**Output**: `JobInfo`

Parses simple key=value files for job name, ODB version, units, creation date, etc.

### 3.6 `src/parsers/stephdr_parser.py` - Step Header Parser

**Input**: `steps/<step>/stephdr` (structured text)
**Output**: `StepHeader`

Parses step header including datum/origin coordinates and `STEP-REPEAT { ... }` blocks for panelization data.

### 3.7 `src/parsers/profile_parser.py` - Profile Parser

**Input**: `steps/<step>/profile` or `layers/<layer>/profile` (features file with single surface)
**Output**: `Profile`

Parses the board outline (or layer outline for rigid-flex). The profile is a single surface feature containing one island contour (the board boundary) and optional hole contours (internal cutouts).

### 3.8 `src/parsers/feature_parser.py` - Layer Features Parser (Core)

**Input**: `layers/<layer>/features` (line record text, may be `.Z` compressed)
**Output**: `LayerFeatures`

This is the most complex and performance-critical parser. It handles:

1. Parse `UNITS`, `ID`, `F` (feature count) header
2. Build symbol table from `$` lines
3. Build attribute lookup tables from `@` and `&` lines
4. Parse feature records:
   - **L** (Line): start point, end point, symbol index, polarity
   - **P** (Pad): center, symbol/aperture, polarity, orientation (0-9 system)
   - **A** (Arc): start, end, center, symbol, polarity, clockwise flag
   - **T** (Text): position, font, size, text string
   - **B** (Barcode): position, type, dimensions, text
   - **S...SE** (Surface): polarity + contour polygons (OB/OS/OC/OE)

Pad orientation decoding:
- `0-3`: 0/90/180/270 degrees, no mirror
- `4-7`: 0/90/180/270 degrees, mirrored
- `8 <angle>`: arbitrary angle, no mirror
- `9 <angle>`: arbitrary angle, mirrored

### 3.9 `src/parsers/component_parser.py` - Component Parser

**Input**: `layers/comp_+_top/components`, `layers/comp_+_bot/components`
**Output**: `list[Component]`

Parses:
- Attribute lookup tables (`@`/`&` lines)
- `CMP` records: package reference, placement (x, y, rotation, mirror), reference designator, part name
- `PRP` records: component properties (part number, type, description, value)
- `TOP` records: toeprint/pin placements with net connectivity
- BOM data records: `CPN`, `PKG`, `IPN`, `DSC`, `VPL_VND`, `VPL_MPN`, `VND`, `MPN`

### 3.10 `src/parsers/eda_parser.py` - EDA Data Parser

**Input**: `steps/<step>/eda/data` (line record text, compressed)
**Output**: `EdaData` containing nets, packages, pins

Parses:
- `HDR`: EDA source identifier
- `LYR`: Layer name list (establishes index-to-name mapping for FID records)
- `NET`: Net records with names and attribute assignments
- `SNT`: Subnet records (TOP/VIA/TRC/PLN) with connectivity type
- `FID`: Feature ID cross-references (type, layer index, feature index)
- `PKG`: Package definitions with bounding box and pitch
- `PIN`: Pin definitions (name, type, center, hole size, electrical/mount type)
- Outline records (`RC/CR/SQ/CT/OB/OS/OC/OE/CE`): Package and pin outlines

### 3.11 `src/parsers/netlist_parser.py` - Netlist Parser

**Input**: `steps/<step>/netlists/cadnet/netlist`
**Output**: `dict[int, str]` (net index to net name mapping)

Parses the header (`H optimize ...`) and indexed net name table (`$N <net_name>`).

### 3.12 `src/parsers/symbol_resolver.py` - Standard Symbol Resolver

**Input**: Symbol name string (e.g., `r120`, `rect20x60`, `donut_r78.74x27.559`)
**Output**: `StandardSymbol` with computed geometry (vertices/arcs for rendering)

Implements the complete standard symbol naming grammar from Appendix A:

| Pattern | Symbol Type | Example |
|---------|------------|---------|
| `r<d>` | Round (circle) | `r120` |
| `s<s>` | Square | `s50` |
| `rect<w>x<h>` | Rectangle | `rect20x60` |
| `rect<w>x<h>xr<rad>` | Rounded rectangle | `rect100x50xr10` |
| `rect<w>x<h>xc<rad>` | Chamfered rectangle | `rect100x50xc8` |
| `oval<w>x<h>` | Oval/oblong | `oval30x80` |
| `di<w>x<h>` | Diamond | `di40x60` |
| `oct<w>x<h>x<r>` | Octagon | `oct50x50x10` |
| `donut_r<od>x<id>` | Round donut | `donut_r78.74x27.559` |
| `donut_s<od>x<id>` | Square donut | `donut_s100x60` |
| `donut_rc<ow>x<oh>x<lw>` | Rectangular donut | `donut_rc100x80x10` |
| `thr<od>x<id>x<a>x<n>x<g>` | Round thermal (rounded) | `thr200x100x45x4x30` |
| `ths<od>x<id>x<a>x<n>x<g>` | Round thermal (squared) | `ths200x100x0x4x20` |
| `s_ths<os>x<is>x<a>x<n>x<g>` | Square thermal | `s_ths200x100x45x4x20` |
| `el<w>x<h>` | Ellipse | `el30x50` |
| `moire<rw>x<rg>x<nr>x...` | Moire pattern | (test/alignment) |

Symbol dimensions are in **mils** (imperial) or **microns** (metric), determined by the `I`/`M` suffix on the `$` line, or the file's `UNITS` setting.

### 3.13 `src/parsers/symbol_parser.py` - User-Defined Symbol Parser

**Input**: `symbols/<name>/features`
**Output**: `UserSymbol`

Uses the same feature parsing logic as `feature_parser.py` to parse user-defined symbol geometry. These symbols are typically pad shapes (SMD footprint pads) defined as surface contours.

### 3.14 `src/parsers/font_parser.py` - Font Parser

**Input**: `fonts/standard`
**Output**: `StrokeFont`

Parses character definitions (`CHAR <c>` ... `ECHAR` blocks) where each character is composed of `LINE` stroke records. Used by the visualizer to render text features.

### 3.15 `src/parsers/stackup_parser.py` - Stackup XML Parser

**Input**: `matrix/stackup.xml` (if present)
**Output**: Stackup data (materials, dielectric properties, impedance specs)

Uses Python's `xml.etree.ElementTree` to parse the XML stackup file. Not all ODB++ files include this.

### 3.16 `src/cache_manager.py` - JSON Cache Manager

**Responsibility**: Serialize parsed data to JSON and load from cache for fast access.

| Function | Description |
|----------|-------------|
| `cache_job(job, parsed_data, cache_dir)` | Write all parsed data to JSON files |
| `load_cache(cache_dir) -> dict` | Load all cached JSON data |
| `is_cache_valid(cache_dir, source_path) -> bool` | Check if cache is newer than source |
| `cache_layer(layer_name, features, cache_dir)` | Cache individual layer data |
| `load_layer(layer_name, cache_dir)` | Load individual layer from cache |

**JSON Cache Structure**:

```json
// job_info.json
{
  "job_name": "designodb_rigidflex",
  "odb_version": "8.1",
  "units": "INCH",
  "creation_date": "20161024.101454"
}

// matrix.json
{
  "steps": [{"col": 1, "name": "cellular_flip-phone", "id": 544796}],
  "layers": [
    {"row": 1, "name": "comp_+_top", "type": "COMPONENT", "context": "BOARD", "polarity": "POSITIVE"},
    {"row": 4, "name": "signal_1", "type": "SIGNAL", "context": "BOARD", "polarity": "POSITIVE"},
    ...
  ]
}

// components_top.json
{
  "components": [
    {
      "comp_name": "R56",
      "part_name": "1000-0243",
      "pkg_ref": 48,
      "x": 1.6755908, "y": 0.9277626,
      "rotation": 90.0, "mirror": false,
      "properties": {"PART_NO": "1000-0243", "TYPE": "Resistor", "VALUE": "3.3Kohms"},
      "toeprints": [{"pin_num": 1, "x": 1.675, "y": 0.917, "net_num": 20}]
    }
  ]
}

// layers/signal_1.json
{
  "units": "INCH",
  "symbols": [{"index": 0, "name": "r10.827"}, ...],
  "features": [
    {"type": "pad", "x": 2.385, "y": 0.116, "symbol_idx": 0, "polarity": "P"},
    {"type": "line", "xs": 0.003, "ys": 1.19, "xe": 0.003, "ye": 1.22, "symbol_idx": 0, "polarity": "P"},
    {"type": "surface", "polarity": "P", "contours": [{"is_island": true, "segments": [...]}]}
  ]
}
```

### 3.17 `src/visualizer/renderer.py` - Main Rendering Orchestrator

**Responsibility**: Coordinates the rendering pipeline.

| Function | Description |
|----------|-------------|
| `render_board(job_data, layers, options)` | Render selected layers to a matplotlib figure |
| `setup_figure(profile)` | Create figure with board outline, set axis limits/aspect |
| `apply_layer_colors(layer_type)` | Assign default colors by layer type |

### 3.18 `src/visualizer/layer_renderer.py` - Feature Renderer

**Responsibility**: Convert parsed feature records into matplotlib drawing primitives.

| Function | Description |
|----------|-------------|
| `render_layer(ax, layer_features, color, alpha)` | Render all features of a layer |
| `draw_line(ax, line_rec, symbol, color)` | Draw a line with proper width from symbol |
| `draw_pad(ax, pad_rec, symbol, color)` | Draw a pad with resolved symbol geometry |
| `draw_arc(ax, arc_rec, symbol, color)` | Draw an arc with proper width |
| `draw_surface(ax, surface_rec, color)` | Draw filled polygon(s) with holes |
| `draw_text(ax, text_rec, font, color)` | Render text using stroke font |

Key rendering considerations:
- **Polarity**: Positive features add material; negative features remove. Use clipping or layered rendering with background color.
- **Symbol width**: Lines and arcs have width defined by their symbol (e.g., `r10.827` = 10.827 mil round aperture).
- **Pad rotation**: Apply the 0-9 orientation system correctly.
- **Surfaces**: Render as matplotlib `PathPatch` with island/hole winding rules.
- **Arc discretization**: Convert arc segments to polyline approximation for matplotlib.

### 3.19 `src/visualizer/symbol_renderer.py` - Symbol Renderer

**Responsibility**: Generate drawable geometry from symbol definitions.

| Function | Description |
|----------|-------------|
| `resolve_symbol(name, units) -> Polygon/Circle` | Parse standard symbol name, return shapely geometry |
| `render_user_symbol(symbol_features) -> Polygon` | Convert user-defined symbol features to geometry |
| `get_symbol_width(name, units) -> float` | Get line width for trace symbols (round apertures) |

### 3.20 `src/visualizer/component_overlay.py` - Component Overlay

**Responsibility**: Render component outlines and reference designators on top of layer rendering.

| Function | Description |
|----------|-------------|
| `draw_components(ax, components, packages)` | Draw component bounding boxes and ref-des labels |
| `draw_package_outline(ax, pkg, x, y, rot, mirror)` | Draw package outline from PKG outlines |
| `draw_pin_markers(ax, toeprints)` | Mark pin 1 indicators |

### 3.21 `src/visualizer/viewer.py` - Interactive Viewer

**Responsibility**: Provide an interactive matplotlib window with layer toggling.

| Feature | Description |
|---------|-------------|
| Layer checkboxes | Toggle visibility of individual layers |
| Layer type groups | Toggle all signal/mask/drill layers at once |
| Zoom/pan | Standard matplotlib navigation toolbar |
| Component info | Click to identify component (reference designator, part, net) |
| Coordinate display | Show cursor position in board units |
| Export | Save current view as PNG/SVG |

### 3.22 `src/checklist/engine.py` - Checklist Engine

**Responsibility**: Orchestrate rule evaluation.

| Function | Description |
|----------|-------------|
| `run_checklist(job_data, rules) -> list[RuleResult]` | Evaluate all rules against job data |
| `load_rules(config) -> list[Rule]` | Load rule definitions from config |
| `evaluate_rule(rule, job_data) -> RuleResult` | Run a single rule, return pass/fail with details |

### 3.23 `src/checklist/rule_base.py` - Rule Base Class

```python
class ChecklistRule:
    """Base class for all checklist rules."""
    rule_id: str        # e.g., "CKL-001"
    description: str    # Human-readable description
    category: str       # "placement", "spacing", "alignment", etc.

    def evaluate(self, job_data) -> RuleResult:
        """Override in subclasses. Return pass/fail with details."""
        raise NotImplementedError
```

`RuleResult` contains: `rule_id`, `passed: bool`, `message: str`, `affected_components: list`, `details: dict`

### 3.24 `src/checklist/rules/` - Individual Rules

Example rules that can be implemented:

| Rule ID | Description | Logic |
|---------|-------------|-------|
| CKL-001 | Capacitor-connector alignment | Check if specific capacitors on Top are horizontally aligned with connectors on Bottom |
| CKL-002 | Component spacing | Verify minimum distance between components using KDTree (scipy) |
| CKL-003 | Component placement zone | Check components are within board outline profile |
| CKL-004 | Solder paste coverage | Verify paste layer features cover component pads |
| CKL-005 | Via-to-component clearance | Check minimum distance from vias to component bodies |

Rules use `shapely` for geometric operations (containment, distance, intersection) and `scipy.spatial.KDTree` for efficient nearest-neighbor spacing checks.

### 3.25 `src/checklist/reporter.py` - Excel Report Generator

**Responsibility**: Generate a formatted Excel report using `openpyxl`.

Report structure:
| Column | Content |
|--------|---------|
| Rule ID | CKL-001 |
| Category | Alignment |
| Description | Capacitor-connector horizontal alignment |
| Status | PASS / FAIL |
| Affected Components | R56, C12, ... |
| Details | Detailed finding message |

Includes conditional formatting (green=PASS, red=FAIL), summary sheet, and per-rule detail sheets.

### 3.26 `main.py` - CLI Entry Point

```
Usage:
  python main.py cache   <odb_path>              # Parse and cache to JSON
  python main.py view    <odb_path> [--layers ...]  # Launch visualizer
  python main.py check   <odb_path> [--rules ...]   # Run checklist
  python main.py info    <odb_path>              # Print job summary
```

---

## 4. Key Design Decisions

### 4.1 Parsing Strategy
- **Lazy parsing**: Only parse files when requested (e.g., don't parse all layer features upfront)
- **Streaming for large files**: Feature files can have 10,000+ records. Use line-by-line parsing, not full file loading into memory for processing
- **Decompression handling**: Transparently handle `.Z` compressed files using Python's `zlib` or subprocess call to `uncompress`

### 4.2 Coordinate System
- All internal coordinates stored in the file's native units (INCH or MM)
- Conversion to a common unit (MM) happens at the visualization/analysis layer
- Symbol dimensions are in mils (imperial) or microns (metric) - converted at symbol resolution time

### 4.3 Symbol Resolution
- Standard symbols are generated on-the-fly from their name parameters
- User-defined symbols are parsed once and cached
- For visualization, symbols are converted to `shapely` polygons
- For simple apertures (round, square), optimized rendering paths are used (matplotlib Circle, Rectangle)

### 4.4 Caching Strategy
- Cache is keyed by job name and source file modification timestamp
- Individual layers can be cached/loaded independently (important for large designs)
- JSON chosen for human-readability and debugging; MessagePack or pickle could be used for performance if needed

### 4.5 Technology Stack

| Library | Purpose |
|---------|---------|
| `matplotlib` | Layer visualization and interactive viewer |
| `shapely` | Polygon operations, geometry validation, distance calculations |
| `numpy` | Coordinate transforms, array operations |
| `scipy` | KDTree for spatial indexing (spacing checks) |
| `openpyxl` | Excel report generation |
| `zlib` / `gzip` | `.Z` file decompression |
| `xml.etree.ElementTree` | Stackup XML parsing |
| `dataclasses` | Model definitions (stdlib) |
| `json` | Cache serialization (stdlib) |
| `argparse` | CLI argument parsing (stdlib) |
| `tarfile` | `.tgz` extraction (stdlib) |
| `re` | Symbol name pattern matching (stdlib) |
