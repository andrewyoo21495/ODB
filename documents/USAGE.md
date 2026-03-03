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
| `cache` | Parse all data and export to JSON cache files |
| `view` | Launch the interactive PCB layer visualizer (outline only by default) |
| `view-top` | Launch visualizer with top-side component overlay pre-selected |
| `view-bot` | Launch visualizer with bottom-side component overlay pre-selected |
| `check` | Run the automated design checklist and export an Excel report |

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

The cache directory will contain:

```
cache/<job_name>/
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

---

## 3. Visualization (`view`, `view-top`, `view-bot`)

The visualizer renders PCB layers in a matplotlib window with interactive controls. Three commands are available depending on what you need to inspect.

### 3a. General Viewer (`view`)

By default (no `--layers`), the viewer loads **all** layers but starts with only the **PCB outline** visible. No layers or component overlays are pre-selected, allowing you to enable exactly what you need via the checkbox panel.

```bash
python main.py view data/designodb_rigidflex.tgz
```

When `--layers` is specified, only those layers are loaded and they are pre-selected in the checkbox panel. Layer names are case-insensitive and match the names shown by the `info` command:

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

### 3b. Top Component Viewer (`view-top`)

Opens the viewer with the **top-side component overlay** pre-selected. Bottom-side components are excluded entirely, making it easy to inspect top placements in isolation. This is useful when reviewing checklist results that reference specific top-side components.

```bash
# Outline + top components only
python main.py view-top data/designodb_rigidflex.tgz

# Top components overlaid on specific copper/mask layers
python main.py view-top data/designodb_rigidflex.tgz --layers signal_1 soldermask_top
```

### 3c. Bottom Component Viewer (`view-bot`)

Same as `view-top` but for the **bottom-side component overlay**. Top-side components are excluded.

```bash
# Outline + bottom components only
python main.py view-bot data/designodb_rigidflex.tgz

# Bottom components overlaid on specific layers
python main.py view-bot data/designodb_rigidflex.tgz --layers signal_10 soldermask_bottom
```

### Interactive Viewer Controls

Once the viewer window opens:

| Control | Action |
|---------|--------|
| **Layer checkboxes** (right panel) | Toggle individual layer visibility on/off. The viewer redraws automatically. The panel also includes "Components Top" and "Components Bot" entries for toggling component overlays. |
| **Zoom** | Use the scroll wheel or the magnifying glass icon in the toolbar to zoom into a region. |
| **Pan** | Click the cross-arrow icon in the toolbar, then click and drag to pan. |
| **Home** | Click the house icon to reset the view to the full board extent. |
| **Save** | Click the floppy disk icon to export the current view as PNG or SVG. |
| **Coordinate display** | The bottom-left of the window shows the cursor position in board units (inches or mm). |

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

Component overlays are drawn with dashed outlines and reference designator labels. Top-side components are cyan; bottom-side components are yellow.

### Performance Note

When no `--layers` flag is given, the viewer loads **all** layers at startup, which may take 15-20 seconds for large designs. Once loaded, toggling layers via checkboxes is instantaneous. If you only need a few specific layers, use `--layers` to skip loading the rest.

---

## 4. Automated Checklist (`check`)

The checklist system evaluates predefined design rules against component placement and geometry data, then exports the results to an Excel file.

### Run All Rules

```bash
python main.py check data/designodb_rigidflex.tgz
```

### Run Specific Rules

```bash
python main.py check data/designodb_rigidflex.tgz --rules CKL-001 CKL-003
```

### Custom Output Path

```bash
python main.py check data/designodb_rigidflex.tgz --output reports/my_report.xlsx
```

Default output path: `output/checklist_report.xlsx`

### Built-in Rules

| Rule ID | Category | Description |
|---------|----------|-------------|
| CKL-001 | Alignment | Capacitors on the Top layer must be horizontally aligned with connectors on the Bottom layer. Checks Y-coordinate difference against a 0.010" tolerance. |
| CKL-002 | Spacing | Minimum spacing between components must be maintained. Uses KDTree spatial indexing to find component pairs closer than 0.008" (~0.2mm). |
| CKL-003 | Placement | All components must be placed within the board outline. Uses the board profile polygon and Shapely point-in-polygon tests. |

### Console Output

The checklist prints a summary to the console before generating the Excel file:

```
============================================================
CHECKLIST RESULTS
============================================================
  [+] CKL-001: Capacitors on Top layer must be horizontally aligned...
      Status: PASS - No applicable capacitor-connector pairs found.
  [X] CKL-002: Minimum spacing between components must be maintained
      Status: FAIL - 1 spacing violation(s) found.
      Components: XD1
  [+] CKL-003: All components must be placed within the board outline
      Status: PASS - All 692 components are within the board outline.

Summary: 2 passed, 1 failed out of 3 rules
```

### Excel Report Structure

The generated `.xlsx` file contains two sheets:

**Summary sheet:**
- Title with job name
- Pass/fail statistics
- Table with columns: Rule ID, Category, Description, Status (color-coded), Message, Affected Components

**Details sheet:**
- Same columns as Summary plus a Details column with expanded violation information (e.g., exact distances, coordinate pairs)

---

## 5. Writing Custom Checklist Rules

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

---

## Typical Workflow

1. **Inspect** the ODB++ file to understand its structure:
   ```bash
   python main.py info data/my_design.tgz
   ```

2. **Cache** the parsed data for fast repeated access:
   ```bash
   python main.py cache data/my_design.tgz
   ```

3. **Visualize** specific layers to review the design:
   ```bash
   python main.py view data/my_design.tgz --layers signal_1 signal_2 soldermask_top
   ```

4. **Inspect components** on a specific side:
   ```bash
   python main.py view-top data/my_design.tgz
   python main.py view-bot data/my_design.tgz --layers signal_10
   ```

5. **Run checklist** to validate design rules:
   ```bash
   python main.py check data/my_design.tgz --output reports/design_review.xlsx
   ```
