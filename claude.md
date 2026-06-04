# ODB++ Processing System

## Project Overview

PCB (Printed Circuit Board) design analysis tool that parses ODB++ archives, visualizes PCB layers, validates design rules via an automated checklist, and calculates copper ratios. Pure Python 3.10+ project with no build system — run directly via `python main.py`.

## Architecture

Three subsystems share a common data layer (`src/models.py` dataclasses):

```
ODB++ .tgz archive
  → odb_loader (extract + discover)
  → 14 parsers → dataclass models → JSON cache
  → 3 consumers: visualizer, checklist engine, copper analysis
```

### Key Subsystems

- **Parsing** (`src/parsers/`): 14 specialized parsers read ODB++ file types into dataclasses. All inherit patterns from `base_parser.py`. Coordinates are normalized to millimeters via `unit_converter.py`.
- **Cache** (`src/cache_manager.py`): Serializes parsed dataclasses to/from JSON. Cache lives in `cache/<job_name>/`.
- **Visualization** (`src/visualizer/`): Interactive matplotlib + Tkinter viewer for PCB layers, components, and copper ratios.
- **Checklist** (`src/checklist/`): Plugin-based design rule engine. Rules self-register via `@register_rule` decorator. 37 rules in `rules/` directory (CKL-01-xxx through CKL-03-xxx).
- **Comparator** (`src/comparator/`): Revision-to-revision diff engine with type-specific comparators.

## Directory Structure

```
ODB/
├── main.py                    # CLI entry point (argparse subcommands)
├── main_gui.py                # GUI wrapper for checklist
├── requirements.txt           # pip dependencies
├── ODB_System_Design.md       # Detailed architecture doc
├── src/
│   ├── models.py              # All dataclass + enum definitions
│   ├── odb_loader.py          # Archive extraction & discovery
│   ├── cache_manager.py       # JSON serialization
│   ├── unit_converter.py      # INCH→MM normalization
│   ├── parsers/               # 14 ODB++ file parsers
│   │   ├── base_parser.py     # Shared parsing utilities
│   │   ├── matrix_parser.py
│   │   ├── feature_parser.py  # Core layer features
│   │   ├── component_parser.py
│   │   ├── eda_parser.py
│   │   ├── symbol_parser.py / symbol_resolver.py
│   │   └── ... (font, profile, netlist, stackup, misc, stephdr)
│   ├── visualizer/            # Rendering & interactive viewer
│   │   ├── viewer.py          # Main interactive matplotlib viewer
│   │   ├── renderer.py        # Rendering orchestrator
│   │   ├── layer_renderer.py  # Feature→graphics conversion
│   │   ├── symbol_renderer.py # Symbol geometry generation
│   │   ├── copper_utils.py / copper_vector.py  # Copper ratio
│   │   └── ...
│   ├── checklist/             # Design rule engine
│   │   ├── engine.py          # Rule registry & execution
│   │   ├── rule_base.py       # Abstract ChecklistRule base class
│   │   ├── reporter.py        # Excel report generation
│   │   ├── html_reporter.py   # HTML report generation
│   │   ├── component_classifier.py  # Component type categorization
│   │   ├── geometry_utils/    # 11 geometry helper modules
│   │   ├── visualizers/       # Rule-specific visualizations
│   │   └── rules/             # 37 rule implementations (ckl_XX_YYY.py)
│   └── comparator/            # Revision comparison
├── data/                      # Input ODB++ archives (gitignored)
├── cache/                     # Generated JSON cache (gitignored)
├── output/                    # Generated reports (gitignored)
├── tests/                     # Test files (gitignored)
├── references/                # Reference docs (gitignored)
└── documents/                 # User-facing documentation
```

## CLI Commands

```
python main.py cache           <odb_path>                     Parse & cache to JSON
python main.py view            <odb_path> [--layers L1 L2]    Interactive layer viewer
python main.py view-comp       <odb_path>                     Component viewer
python main.py view-net        <odb_path>                     Net filter viewer
python main.py check           <odb_path> [--rules R1 R2]     Run design checklist
python main.py copper          <odb_path>                     Layer thickness info
python main.py copper-ratio    <odb_path>                     Copper ratio viewer
python main.py copper-calculate                                Batch copper calculator GUI
python main.py compare         <odb_old> <odb_new>            Compare revisions
python main.py info            <odb_path>                     Print job summary
```

## Dependencies

- `matplotlib>=3.7.0` — visualization & interactive viewer
- `shapely>=2.0.0` — polygon operations (overlap, distance, area)
- `numpy>=1.24.0` — coordinate transforms, array ops
- `scipy>=1.10.0` — spatial indexing (KDTree for spacing checks)
- `openpyxl>=3.1.0` — Excel report generation
- stdlib: `tarfile`, `json`, `xml.etree.ElementTree`, `dataclasses`, `pathlib`, `argparse`, `tkinter`

Virtual environment lives in `.odb/` (gitignored).

## Coding Conventions

### Style

- **Python 3.10+** — uses modern type syntax (`list[str]`, `dict[str, str]`, `X | None`)
- **`from __future__ import annotations`** at the top of every module
- **Type hints** on all function signatures
- **snake_case** for functions, variables, modules; **PascalCase** for classes; **UPPER_SNAKE** for constants
- **Docstrings**: module-level docstring on every file, Google-style docstrings on public functions/classes
- **Imports**: organized as stdlib → third-party → local (`from src.xxx import ...`)
- **Line length**: ~100 chars (no strict formatter configured)

### Patterns

- **Dataclasses everywhere**: all models in `src/models.py`, no ORM
- **Enums for categorical values**: `LayerType`, `FeaturePolarity`, `SubnetType`, etc.
- **Factory functions**: parsers expose `parse_*()` functions that return dataclass instances
- **Decorator-based plugin registration**: `@register_rule` on checklist rule classes
- **Explicit data passing**: parsed data flows through function arguments, not globals
- **Lazy loading**: individual layers and components parsed/loaded on demand
- **JSON cache**: human-readable, debuggable serialization (not pickle)

### Checklist Rules

Each rule is a class in `src/checklist/rules/ckl_XX_YYY.py`:

```python
@register_rule
class CklXXYYY(ChecklistRule):
    rule_id = "CKL-XX-YYY"
    description = "..."
    category = "..."

    def evaluate(self, job_data: dict) -> RuleResult:
        # job_data keys: 'components_top', 'components_bot', 'eda_data',
        #   'profile', 'matrix_layers', 'layer_features', 'job_info'
        ...
```

Rule categories:
- **CKL-01-xxx**: IC, Filter, Oscillator placement rules
- **CKL-02-xxx**: Capacitor, Inductor, Connector spacing rules
- **CKL-03-xxx**: PCB outline clearance, bending area, board-level rules

Geometry helpers live in `src/checklist/geometry_utils/` (overlap, distance, clearance, orientation, polygon, bending, via, etc.). Use `shapely` for polygon operations and `scipy.spatial.KDTree` for spatial queries.

### Coordinate System

- All coordinates are normalized to **millimeters** before use
- Board coordinates from profile (ground truth) vs EDA coordinates (package-local space)
- Automatic scale detection/correction when EDA and board units mismatch (`_calibrate_eda_to_components` in `main.py`)

## Testing

Tests live in `tests/` (gitignored from repo). Framework: **pytest** with parametric test generation. Tests use mock components and dataclass fixtures. Some tests produce visual output for manual verification.

## Key Files for Common Tasks

| Task | Start here |
|---|---|
| Add a new checklist rule | `src/checklist/rules/` — copy an existing `ckl_*.py`, use `@register_rule` |
| Add a geometry utility | `src/checklist/geometry_utils/` |
| Modify parsing logic | `src/parsers/` — find the relevant parser |
| Change data models | `src/models.py` — update dataclass, then update `cache_manager.py` serialization |
| Modify the viewer | `src/visualizer/viewer.py` |
| Add a CLI command | `main.py` — add argparse subcommand and `cmd_*()` function |
| Generate reports | `src/checklist/reporter.py` (Excel), `src/checklist/html_reporter.py` (HTML) |
