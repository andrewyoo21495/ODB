# ODB++ Processing System - Usage Guide

## Prerequisites

### Python Environment

Python 3.10 or higher is required. Install dependencies from the project root:

```bash
pip install -r requirements.txt
```

Required packages:
| Package | Purpose |
|---------|---------|
| matplotlib | PCB visualization and interactive viewer |
| shapely | Polygon operations for geometry checks |
| numpy | Coordinate transforms and array operations |
| scipy | Spatial indexing for spacing checks (KDTree) |
| openpyxl | Excel checklist report generation |

### ODB++ Input Data

The system accepts two input formats:
- A `.tgz` archive containing an ODB++ product model (e.g., `data/designodb_rigidflex.tgz`)
- A pre-extracted ODB++ directory (the root folder containing `matrix/`, `steps/`, `misc/`, etc.)

All commands below use `<odb_path>` to refer to either format.

---

## Commands Overview

All commands are run from the project root directory through `main.py`:

```
python main.py <command> <odb_path> [options]
```

| Command | Description |
|---------|-------------|
| `info` | Print a summary of the ODB++ job (layers, steps, version) |
| `cache` | Parse all data, normalize units, and export to JSON cache files |
| `view` | Launch the interactive PCB layer visualizer — loads from cache (auto-builds if missing) |
| `view-comp` | Launch the component-focused viewer — loads from cache (auto-builds if missing) |
| `check` | Run the automated design checklist — loads from cache (auto-builds if missing) |
| `copper-calculate` | Launch the copper ratio batch calculator GUI — processes all signal layers and exports to Excel |

### Recommended Workflow

```
python main.py cache data/my_design.tgz     # Parse once, cache to JSON
python main.py view  data/my_design.tgz     # Visualize using cached data
python main.py check data/my_design.tgz     # Run rules using cached data
```

The `view`, `view-comp`, and `check` commands read directly from the JSON cache. If no cache exists for the given file, caching runs automatically before the command proceeds. Running `cache` explicitly upfront is recommended for large files so the one-time parsing cost is paid on its own.

---

## 1. Inspecting a Job (`info`)

Use `info` to quickly see what an ODB++ file contains before doing any processing.

```bash
python main.py info data/designodb_rigidflex.tgz
```

Output includes:
- ODB++ version, source EDA tool, creation/save dates
- List of all steps (designs) in the file
- Full layer stackup with type, row number, and subtype (e.g., COVERLAY, PG_FLEX)
- Number of user-defined symbols and wheels

This is the recommended first step when working with a new ODB++ file. The layer names shown here are the names you use with `--layers` in the `view` command.

---

## 2. JSON Caching (`cache`)

Parsing ODB++ files from the raw directory structure is time-consuming for large designs. The `cache` command parses everything once and stores the results as JSON files for fast subsequent access.

### Basic Usage

```bash
python main.py cache data/designodb_rigidflex.tgz
```

### Custom Cache Directory

```bash
python main.py cache data/designodb_rigidflex.tgz --cache-dir my_cache
```

### What Gets Cached

The cache folder is named after the **input file** (without extension), not the internal ODB++ job name. For example, caching `data/designodb_rigidflex.tgz` creates `cache/designodb_rigidflex/`.

During caching, component placement coordinates and EDA package geometry that are declared in inches are automatically multiplied by 25.4 and saved in millimetres. The board profile (outline) is stored exactly as it appears in the ODB++ source and serves as the ground-truth coordinate system for rendering. The `view`, `view-comp`, and `check` commands use this cached, unit-normalized data directly.

The cache directory will contain:

```
cache/<input_filename>/
    job_info.json            # ODB++ version, source, dates, units
    matrix_steps.json        # Step definitions
    matrix_layers.json       # Full layer stackup
    step_header.json         # Step datum, origin, units
    profile.json             # Board outline geometry
    eda_data.json            # Nets, packages, pins, connectivity
    netlist.json             # Net name table
    components_top.json      # Top-side component placements + BOM
    components_bot.json      # Bottom-side component placements + BOM
    font.json                # Stroke font character definitions
    symbols.json             # User-defined symbol geometries
    layers/
        signal_1.json        # Per-layer feature data (pads, lines, arcs, surfaces)
        signal_2.json
        soldermask_top.json
        ...
```

Each layer's feature file is stored separately so that the visualizer and other tools can load individual layers without reading everything into memory.

A `components_top_units.json` and `components_bot_units.json` file record the unit system of the stored component coordinates (`"MM"` after normalization), allowing the renderer to apply the correct scale when overlaying components on the profile.

---

## 3. Visualization (`view`)

The visualizer renders PCB layers in a matplotlib window with interactive controls. Data is read from the JSON cache — if no cache exists for the given file, it is built automatically.

By default (no `--layers`), the viewer shows all cached layers but starts with only the **PCB outline** visible. Enable individual layers and component overlays via the checkbox panel.

```bash
python main.py view data/designodb_rigidflex.tgz
```

To use a non-default cache location:

```bash
python main.py view data/designodb_rigidflex.tgz --cache-dir my_cache
```

When `--layers` is specified, only those layers are pre-selected in the checkbox panel (all cached layers remain available). Layer names are case-insensitive and match the names shown by the `info` command:

```bash
# View only signal layers
python main.py view data/designodb_rigidflex.tgz --layers signal_1 signal_2 signal_3

# View top-side assembly (copper + mask + silk)
python main.py view data/designodb_rigidflex.tgz --layers signal_1 soldermask_top spt

# View drill layers
python main.py view data/designodb_rigidflex.tgz --layers d_1_2 d_1_10 d_3_8

# View flex-specific layers
python main.py view data/designodb_rigidflex.tgz --layers flex_5 flex_6 covertop coverbottom bend_area
```

Component overlays (top and bottom) are always available as checkbox entries in the panel. Select "Components Top" or "Components Bot" to display component placements.

Top-side components are rendered in **sky blue**; bottom-side components are rendered in **light pink** for easy visual distinction.

Component geometries are derived from the EDA package data. For each placed component, the system looks up its package definition via the `pkg_ref` index and renders the actual pad shapes stored in that package:

| Shape type | Description |
|------------|-------------|
| `RC` | Rectangular pad (lower-left corner + width/height) |
| `CR` / `CT` | Circular pad (centre + radius) |
| `SQ` | Square pad (centre + half-side) |
| `CONTOUR` | Arbitrary polygon pad from arc/line contour data |

Package-level courtyard and silkscreen outlines are drawn as dashed lines at reduced opacity. When a package has no outline data, a dashed bounding box is used as a fallback.

### Viewer Layout

The viewer window is divided into three sections:

| Section | Location | Content |
|---------|----------|---------|
| **Layer checkboxes** | Top-left | Toggle individual layers, component overlays, and outlines on/off. |
| **Component info** | Bottom-left | Displays metadata for the component selected by clicking on the board. |
| **Board canvas** | Right (main area) | The PCB visualization — layers, pads, outlines, and board profile. |

### Interactive Controls

| Control | Action |
|---------|--------|
| **Layer checkboxes** (top-left) | Toggle individual layer visibility on/off. The viewer redraws automatically. Includes "Components Top", "Components Bot", and "Comp. Outlines" entries. DRILL and DIELECTRIC layers are excluded (they can still be loaded via `--layers`). |
| **Comp. Outlines checkbox** | Draws yellow dashed outlines around component boundaries. When neither Top nor Bot components are checked, outlines are drawn for all components. |
| **Click on board** | Click on or near a component pin to select it. The component's metadata appears in the bottom-left info panel. |
| **Scroll wheel on checkbox panel** | When the layer list is longer than the panel height, scroll up/down over the checkbox panel to reveal additional layers. |
| **Zoom** | Use the scroll wheel over the board area, or use the magnifying glass icon in the toolbar to zoom into a region. |
| **Pan** | Click the cross-arrow icon in the toolbar, then click and drag to pan. |
| **Home** | Click the house icon to reset the view to the full board extent. |
| **Save** | Click the floppy disk icon to export the current view as PNG or SVG. |
| **Coordinate display** | The bottom-left of the window shows the cursor position in board units (inches or mm). |

### Component Info Panel

When you click on a component pin in the board canvas, the bottom-left panel shows:

- **Component name** (ref-des) and **part name**
- **Classification** (Capacitor, Connector, IC, etc. from the component classifier)
- **Properties** — TYPE, DEVICE_TYPE, VALUE (when available)
- **Position** and **rotation**
- **Net names** connected to the component (up to 6)
- **BOM data** — CPN, description, MPN (when available)

### Layer Color Coding

Each layer type is rendered with a distinct default color:

| Layer Type | Color |
|------------|-------|
| SIGNAL | Red |
| POWER_GROUND | Blue |
| SOLDER_MASK | Green |
| SOLDER_PASTE | Gray |
| SILK_SCREEN | Yellow |
| DRILL | Magenta |
| ROUT | Orange |
| COMPONENT | Cyan |
| DOCUMENT | Dark Gray |

> **Note:** DRILL and DIELECTRIC layers are not shown in the checkbox panel because they contain no renderable features. They can still be loaded directly using `--layers d_1_2 ...` if needed.

Component overlays render actual pad geometries (rectangles, circles, squares, contours) derived from the EDA package definitions. Top-side components are sky blue; bottom-side components are light pink. Component names are not shown on the board — click a pin to see component details in the info panel instead.

### Unit Normalization

ODB++ files may declare different units (INCH vs MM) for component placement data and EDA package geometry. The `cache` command normalizes these to millimetres at cache time. The board profile (outline) is always stored and rendered using its original coordinate values, which serve as the ground truth for the plot axes. The renderer automatically applies the correct scale factor when overlaying components on the profile.

### Performance Note

The viewer reads from the JSON cache, so startup is fast regardless of how many layers are present. The one-time parsing cost is paid when the cache is first built (either via an explicit `cache` command or automatically on first run).

---

## 4. Component Viewer (`view-comp`)

The component viewer provides a focused, component-centric inspection mode. Only component geometry is shown — layer copper features are not rendered. Data is read from the JSON cache (auto-built if missing).

```bash
python main.py view-comp data/designodb_rigidflex.tgz
```

To use a non-default cache location:

```bash
python main.py view-comp data/designodb_rigidflex.tgz --cache-dir my_cache
```

### Viewer Layout

The left control panel contains all interaction controls (top → bottom); the right panel is the board canvas.

| Section | Location | Content |
|---------|----------|---------|
| **Layer Selection** | Top-left | RadioButtons: choose Top, Bottom, or Both |
| **Component Selection** | Mid-left | Scrollable checkbox list of component reference designators |
| **Display Options** | Lower-left | "Show Pins", "Show Component Outline", and "Show Via" checkboxes |
| **Update Visualization** | Lower-left | Button that applies current selections to the board canvas |
| **Component Info** | Bottom-left | Metadata for the pin clicked on the board |
| **Board canvas** | Right (main area) | PCB outline and selected component geometry |

### Workflow

1. **Select layer** — choose Top, Bottom, or Both. The Component Selection list rebuilds to show components on the chosen layer(s).
2. **Select components** — tick one or more reference designators in the list. Scroll with the mouse wheel when the list overflows.
3. **Set display options**:
   - **Show Pins** (default on) — renders the individual pad shapes for each selected component.
   - **Show Component Outline** — also draws the package-level courtyard/silkscreen outlines as dashed lines. Can be combined with Show Pins or used alone.
   - **Show Via** — overlays SNT VIA pad features in dark grey, filtered to match the selected layer (Top/Bottom/Both). VIAs are drawn beneath component geometry.
4. **Click "Update Visualization"** — the board canvas redraws with only the selected components and the chosen display options applied.
5. **Click a pin** — the Component Info panel at the bottom-left shows that component's metadata.

### Color Coding

Top-side components are rendered in **blue** (`#00B7FF`); bottom-side components in **red** (`#FF3150`), matching the standard viewer's component colors.

---

## 5. Automated Checklist (`check`)

The checklist system evaluates predefined design rules against component placement and geometry data from the JSON cache, then exports the results to an Excel file. The cache is auto-built if it does not yet exist.

### Run All Rules

```bash
python main.py check data/designodb_rigidflex.tgz
```

### Run Specific Rules

```bash
python main.py check data/designodb_rigidflex.tgz --rules CKL-01-001 CKL-03-015
```

### Custom Output Path

```bash
python main.py check data/designodb_rigidflex.tgz --output reports/my_report.xlsx
```

### Custom Cache Directory

```bash
python main.py check data/designodb_rigidflex.tgz --cache-dir my_cache
```

Default output path: `output/checklist_report.xlsx`

### Built-in Rules

Rules are listed in the [Checklist Documentation](checklist_documentation.html). Use the `--rules` flag to run specific rules by ID (e.g. `CKL-01-001`, `CKL-03-015`).

### Console Output

The checklist prints a summary to the console before generating the Excel file:

```
============================================================
CHECKLIST RESULTS
============================================================
  [+] CKL-01-001: ICs must not overlap with interposers or connectors...
      Status: PASS - No overlapping components found.
  [X] CKL-03-015: Components must have at least 0.65mm clearance...
      Status: FAIL - 3 component(s) within clearance zone.
      Components: C12, R56, L3

Summary: 1 passed, 1 failed out of 2 rules
```

### Excel Report Structure

The generated `.xlsx` file contains a **Summary** sheet, a **Details** sheet, and one **dedicated tab per rule**, sorted numerically by rule ID.

| Tab | Content |
|-----|---------|
| **Summary** | Title with job name, pass/fail statistics, and a table with columns: Rule ID, Category, Description, Status (color-coded), Message, Affected Components. |
| **Details** | Same columns as Summary plus a Details column with expanded violation information (e.g., exact distances, coordinate pairs). |
| **CKL-01-001**, **CKL-02-001**, ... | One tab per rule. Contains a metadata header (rule ID, category, description, status, message), an affected components list, and detailed findings tables. |

Rule tabs are automatically sorted so that they appear in numerical order (e.g. CKL-01-001, CKL-01-005, ..., CKL-03-015). This ordering is maintained regardless of the naming convention used for rule IDs.

---

## 6. Copper Ratio Batch Calculator (`copper-calculate`)

The copper ratio batch calculator processes all signal layers in an ODB++ file, computes full-layer and sub-section copper ratios, saves PNG visualizations for each layer, and exports the results to a structured Excel file.

Unlike `view` and `check`, this command takes no ODB++ path argument — file selection is done through the GUI.

```bash
python main.py copper-calculate
```

### Calculation Methods

The calculator supports two calculation methods, selectable via the **Use Vector Method** checkbox:

| Method | How it works | Strengths |
|--------|-------------|-----------|
| **Raster** (default) | Renders the layer to a pixel image at 400 DPI, then counts copper vs. background pixels. | Fast for simple layers; visual confirmation via rendered image. |
| **Vector** | Converts every feature (line, pad, arc, surface) directly to mathematical polygons and computes area with boolean geometry operations (Shapely). No image is rendered for measurement. | **Mathematically exact** — immune to resolution limits. Fine traces that appear merged in raster mode are measured with their true geometry. Sub-section ratios come from cheap polygon intersection rather than re-rendering. |

**When to use Vector mode:**  
Use Vector mode when the board has dense, fine-pitch routing where the raster method over-counts copper because adjacent traces merge into a solid block of pixels. Vector mode eliminates this resolution artefact entirely.

### GUI Layout

When launched, a small window appears with the following controls:

| Control | Description |
|---------|-------------|
| **ODB++ File** | Path to the input `.tgz`, `.tar.gz`, or `.zip` archive. Click **Browse…** to select. |
| **Excel Output** | Path for the generated `.xlsx` report. Click **Save As…** to choose the destination. |
| **Sub-section Grid** | Grid size for sub-section ratios (e.g. `5x5`, `4x5`). |
| **Use Vector Method** | Checkbox. When checked, uses vector-based polygon geometry instead of rasterization for copper ratio calculation. |
| **Calculate** | Starts batch processing. The button disables itself while running. |
| **Status area** | Scrollable log showing per-layer progress messages. Displays "Done!" on completion. |

### Processing Steps

When **Calculate** is clicked the tool:

1. Loads ODB++ data from the JSON cache (auto-builds if missing, same cache as `view`/`check`)
2. Iterates over all signal layers in stackup order
3. For each signal layer:
   - **Raster mode:** Renders the layer off-screen at 400 DPI, counts copper pixels vs. PCB-area pixels, and partitions the image into the grid.
   - **Vector mode:** Converts all features to Shapely polygons, applies polarity rules (positive = add copper, negative = remove copper), clips to the PCB outline, and computes areas. Sub-section ratios are calculated by intersecting the copper polygon with each grid cell.
   - Saves a PNG visualization with the colour-coded heatmap overlay to `images/<layer_name>.png` next to the Excel file
4. Generates the Excel report

### Excel Report Structure

| Sheet | Content |
|-------|---------|
| **Summary** | **Table A** — one row per signal layer: Layer Name and Total Copper (%). **Table B** — all layers from the stackup in row order with Name, Type, and Thickness (mm). |
| **\<layer_name\>** | One sheet per signal layer. Contains a header block (layer name, copper ratio, thickness), the sub-section grid with conditional colour fills, and the embedded PNG visualization. |

Sub-section grid colour coding (applied to each cell of the grid table):

| Fill colour | Copper ratio |
|-------------|-------------|
| Green | > 50% |
| Yellow | 30 – 50% |
| Red | < 30% |
| Grey | No PCB area in that cell |

### Cache Behaviour

The calculator uses the same cache directory as other commands (default: `cache/`). If a cache already exists for the selected ODB++ file it is loaded directly — no re-parsing. To override the cache directory, pass `--cache-dir`:

```bash
python main.py copper-calculate --cache-dir my_cache
```

---

## 7. Writing Custom Checklist Rules

New rules are added by creating a Python file under `src/checklist/rules/` and using the `@register_rule` decorator.

### Step 1: Create the Rule File

Create a new file, e.g., `src/checklist/rules/ckl_custom.py`:

```python
from src.checklist.engine import register_rule
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


@register_rule
class MyCustomRule(ChecklistRule):
    rule_id = "CKL-100"
    description = "Decoupling capacitors must be within 0.050in of their IC"
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        # ... your logic here ...

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=True,
            message="All decoupling capacitors properly placed.",
        )
```

### Step 2: Register the Import

Add the import to `main.py` in the `cmd_check()` function alongside the existing rule imports:

```python
import src.checklist.rules.ckl_custom  # noqa: F401
```

### Available Data in `job_data`

The `evaluate()` method receives a dictionary with these keys:

| Key | Type | Description |
|-----|------|-------------|
| `components_top` | `list[Component]` | Top-side component placements. Each has `.comp_name`, `.part_name`, `.x`, `.y`, `.rotation`, `.mirror`, `.properties`, `.toeprints` |
| `components_bot` | `list[Component]` | Bottom-side component placements (same structure) |
| `eda_data` | `EdaData` | Net definitions (`.nets`), package definitions (`.packages`), layer name mapping (`.layer_names`) |
| `profile` | `Profile` | Board outline polygon (`.surface.contours`) |
| `matrix_layers` | `list[MatrixLayer]` | Layer stackup with `.name`, `.type`, `.row`, `.polarity`, `.add_type` |
| `job_info` | `JobInfo` | Job metadata: `.job_name`, `.units`, `.odb_version_major` |

### Component Properties

Each `Component` object provides:

```python
comp.comp_name      # "R56", "C12", "U3"
comp.part_name      # "1000-0243"
comp.x, comp.y      # Board coordinates
comp.rotation        # Degrees (clockwise)
comp.mirror          # True/False
comp.properties      # {"TYPE": "Resistor", "VALUE": "3.3Kohms", ...}
comp.toeprints       # List of pin placements with net connectivity
comp.bom_data        # BOM info: CPN, vendor, MPN
```

### Toeprint (Pin) Properties

Each toeprint on a component provides net connectivity:

```python
for tp in comp.toeprints:
    tp.pin_num       # Pin number in package
    tp.x, tp.y       # Pin board coordinates
    tp.net_num        # Index into eda_data.nets
    tp.subnet_num     # Subnet index within that net
```

### Component Classification

The `classify_component()` utility (in `src/checklist/component_classifier.py`) assigns each component to one of the following categories using a fixed priority order. All built-in checklist rules use this classifier — avoid hardcoding name prefixes in custom rules.

```python
from src.checklist.component_classifier import ComponentCategory, classify_component

category = classify_component(comp)   # returns a ComponentCategory enum value

if category is ComponentCategory.IC:
    ...
```

| Category | Rule | Priority |
|----------|------|----------|
| `Connector` | `comp_name` starts with `"SOC"` | 1 (highest) |
| `SIM_Socket` | `comp_name` starts with `"SIM"` | 2 |
| `Inductor` | `properties["TYPE"]` or `properties["DEVICE_TYPE"]` == `"inductor"` (case-insensitive), **or** `part_name` starts with `"2703-"` | 3 |
| `Capacitor` | `properties["TYPE"]` or `properties["DEVICE_TYPE"]` == `"capacitor"` (case-insensitive), **or** `part_name` starts with `"2203-"` | 4 |
| `IC` | `comp_name` starts with `"U"` and does **not** start with `"USB"` | 5 |
| `INP` | `comp_name` starts with `"INP"` | 6 |
| `Unknown` | Everything else | — |

The first matching rule wins. `properties` values are read from the component's PRP records (parsed from `comp_+_top` / `comp_+_bot` files and available in the JSON cache).

---

## Typical Workflow

1. **Inspect** the ODB++ file to understand its structure:
   ```bash
   python main.py info data/my_design.tgz
   ```

2. **Cache** the parsed data (parse once, normalize units, write JSON):
   ```bash
   python main.py cache data/my_design.tgz
   ```
   This is the recommended first step. All subsequent commands load from this cache, so the slow ODB++ parsing only happens once. If you skip this step, the first `view`/`view-comp`/`check` call will auto-build the cache before proceeding.

3. **Visualize** specific layers to review the design:
   ```bash
   python main.py view data/my_design.tgz --layers signal_1 signal_2 soldermask_top
   ```

4. **Inspect components** on top and/or bottom using the checkbox panel in the viewer:
   ```bash
   python main.py view data/my_design.tgz
   ```

5. **Inspect individual components** with the component viewer for focused pin/outline analysis:
   ```bash
   python main.py view-comp data/my_design.tgz
   ```

6. **Run checklist** to validate design rules:
   ```bash
   python main.py check data/my_design.tgz --output reports/design_review.xlsx
   ```

7. **Calculate copper ratios** for all signal layers and export to Excel:
   ```bash
   python main.py copper-calculate
   ```
   Select the ODB++ file and an Excel output path in the GUI, then click **Calculate**. PNG images and the Excel report are written automatically.
