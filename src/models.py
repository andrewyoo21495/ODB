"""Data models for ODB++ processing system.

All dataclass definitions shared across parsers, cache, visualizer, and checklist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Union


# --- Enumerations ---

class LayerContext(Enum):
    BOARD = "BOARD"
    MISC = "MISC"


class LayerType(Enum):
    SIGNAL = "SIGNAL"
    POWER_GROUND = "POWER_GROUND"
    DIELECTRIC = "DIELECTRIC"
    MIXED = "MIXED"
    SOLDER_MASK = "SOLDER_MASK"
    SOLDER_PASTE = "SOLDER_PASTE"
    SILK_SCREEN = "SILK_SCREEN"
    DRILL = "DRILL"
    ROUT = "ROUT"
    DOCUMENT = "DOCUMENT"
    COMPONENT = "COMPONENT"
    MASK = "MASK"
    CONDUCTIVE_PASTE = "CONDUCTIVE_PASTE"


class Polarity(Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"


class FeaturePolarity(Enum):
    P = "P"  # Positive
    N = "N"  # Negative


class SubnetType(Enum):
    VIA = "VIA"
    TRC = "TRC"  # Trace
    PLN = "PLN"  # Plane
    TOP = "TOP"  # Toeprint


class FeatureIdType(Enum):
    C = "C"  # Copper
    L = "L"  # Laminate
    H = "H"  # Hole


class PinElectricalType(Enum):
    E = "E"  # Electrical
    M = "M"  # Mechanical
    U = "U"  # Undefined


class PinMountType(Enum):
    SMT = "S"     # Surface mount
    TH = "T"      # Through-hole
    PRESS = "P"   # Press-fit
    OTHER = "O"   # Other
    UNDEF = "U"   # Undefined


class DrillType(Enum):
    PLATED = "PLATED"
    NON_PLATED = "NON_PLATED"
    VIA = "VIA"


class LayerForm(Enum):
    RIGID = "RIGID"
    FLEX = "FLEX"


# --- Basic Geometry ---

@dataclass
class Point:
    x: float
    y: float


@dataclass
class BBox:
    xmin: float
    ymin: float
    xmax: float
    ymax: float


@dataclass
class LineSegment:
    """Straight line segment to endpoint."""
    end: Point


@dataclass
class ArcSegment:
    """Arc segment to endpoint with center and direction."""
    end: Point
    center: Point
    clockwise: bool


@dataclass
class Contour:
    """Closed polygon contour (island or hole)."""
    is_island: bool
    start: Point
    segments: list[Union[LineSegment, ArcSegment]] = field(default_factory=list)


@dataclass
class Surface:
    """Polygon area defined by contours."""
    polarity: FeaturePolarity
    contours: list[Contour] = field(default_factory=list)


# --- Job / Product Model ---

@dataclass
class JobInfo:
    job_name: str = ""
    odb_version_major: int = 0
    odb_version_minor: int = 0
    odb_source: str = ""
    creation_date: str = ""
    save_date: str = ""
    save_app: str = ""
    save_user: str = ""
    units: str = "INCH"
    max_uid: int = 0


# --- Matrix ---

@dataclass
class MatrixStep:
    col: int = 0
    name: str = ""
    id: int = 0


@dataclass
class MatrixLayer:
    row: int = 0
    name: str = ""
    context: str = "BOARD"
    type: str = "SIGNAL"
    polarity: str = "POSITIVE"
    add_type: str = ""
    start_name: str = ""
    end_name: str = ""
    old_name: str = ""
    color: str = ""
    id: int = 0
    form: str = ""
    dielectric_type: str = ""
    dielectric_name: str = ""
    cu_top: str = ""
    cu_bottom: str = ""


# --- Step ---

@dataclass
class StepRepeat:
    name: str = ""
    x: float = 0.0
    y: float = 0.0
    dx: float = 0.0
    dy: float = 0.0
    nx: int = 1
    ny: int = 1
    angle: float = 0.0
    flip: bool = False
    mirror: bool = False


@dataclass
class StepHeader:
    units: str = "INCH"
    x_datum: float = 0.0
    y_datum: float = 0.0
    x_origin: float = 0.0
    y_origin: float = 0.0
    top_active: float = 0.0
    bottom_active: float = 0.0
    right_active: float = 0.0
    left_active: float = 0.0
    affecting_bom: str = ""
    affecting_bom_changed: int = 0
    id: int = 0
    step_repeats: list[StepRepeat] = field(default_factory=list)


@dataclass
class Profile:
    """Board or layer outline."""
    units: str = "INCH"
    surface: Optional[Surface] = None


# --- Symbols ---

@dataclass
class SymbolRef:
    """Entry in a feature file's symbol table ($N lines)."""
    index: int
    name: str
    unit_override: Optional[str] = None  # 'I' for imperial, 'M' for metric, None for file default


@dataclass
class StandardSymbol:
    """Parsed standard symbol with computed parameters."""
    name: str
    type: str  # round, square, rect, oval, diamond, octagon, donut_r, etc.
    params: dict = field(default_factory=dict)
    # For rendering: pre-computed geometry
    width: float = 0.0   # symbol width (for line apertures)
    height: float = 0.0  # symbol height


@dataclass
class UserSymbol:
    """User-defined symbol loaded from symbols/ directory."""
    name: str
    units: str = "INCH"
    features: list = field(default_factory=list)  # List of feature records


# --- Font ---

@dataclass
class FontStroke:
    x1: float
    y1: float
    x2: float
    y2: float
    polarity: str = "P"
    shape: str = "R"  # R=round
    width: float = 0.012


@dataclass
class FontChar:
    char: str
    strokes: list[FontStroke] = field(default_factory=list)


@dataclass
class StrokeFont:
    xsize: float = 0.0
    ysize: float = 0.0
    offset: float = 0.0
    characters: dict[str, FontChar] = field(default_factory=dict)


# --- Layer Features ---

@dataclass
class LineRecord:
    xs: float
    ys: float
    xe: float
    ye: float
    symbol_idx: int
    polarity: FeaturePolarity
    dcode: int = 0
    attributes: dict = field(default_factory=dict)
    id: Optional[int] = None


@dataclass
class PadRecord:
    x: float
    y: float
    symbol_idx: int
    polarity: FeaturePolarity
    dcode: int = 0
    rotation: float = 0.0
    mirror: bool = False
    resize_factor: Optional[float] = None
    attributes: dict = field(default_factory=dict)
    id: Optional[int] = None


@dataclass
class ArcRecord:
    xs: float
    ys: float
    xe: float
    ye: float
    xc: float
    yc: float
    symbol_idx: int
    polarity: FeaturePolarity
    dcode: int = 0
    clockwise: bool = True
    attributes: dict = field(default_factory=dict)
    id: Optional[int] = None


@dataclass
class TextRecord:
    x: float
    y: float
    font: str
    polarity: FeaturePolarity
    rotation: float = 0.0
    mirror: bool = False
    xsize: float = 0.0
    ysize: float = 0.0
    width_factor: float = 1.0
    text: str = ""
    version: int = 0
    attributes: dict = field(default_factory=dict)
    id: Optional[int] = None


@dataclass
class BarcodeRecord:
    x: float
    y: float
    barcode: str
    font: str
    polarity: FeaturePolarity
    rotation: float = 0.0
    mirror: bool = False
    width: float = 0.0
    height: float = 0.0
    fasc: str = ""
    cs: str = ""
    bg: str = ""
    astr: str = ""
    astr_pos: str = ""
    text: str = ""
    attributes: dict = field(default_factory=dict)
    id: Optional[int] = None


@dataclass
class SurfaceRecord:
    polarity: FeaturePolarity
    dcode: int = 0
    contours: list[Contour] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    id: Optional[int] = None


# Union type for all feature records
FeatureRecord = Union[LineRecord, PadRecord, ArcRecord, TextRecord, BarcodeRecord, SurfaceRecord]


@dataclass
class LayerFeatures:
    units: str = "INCH"
    id: Optional[int] = None
    feature_count: Optional[int] = None
    symbols: list[SymbolRef] = field(default_factory=list)
    attr_names: dict[int, str] = field(default_factory=dict)   # @index -> name
    attr_texts: dict[int, str] = field(default_factory=dict)   # &index -> text value
    features: list[FeatureRecord] = field(default_factory=list)


# --- EDA Data ---

@dataclass
class FeatureIdRef:
    """Cross-reference to a feature in a layer."""
    type: str  # C=Copper, L=Laminate, H=Hole
    layer_idx: int
    feature_idx: int


@dataclass
class Subnet:
    type: str  # VIA, TRC, PLN, TOP
    feature_ids: list[FeatureIdRef] = field(default_factory=list)
    # TOP subnet specific fields
    side: str = ""       # T or B
    comp_num: int = -1
    toep_num: int = -1
    # PLN subnet specific fields
    fill_type: str = ""
    cutout_type: str = ""
    fill_size: float = 0.0


@dataclass
class Net:
    name: str
    index: int
    subnets: list[Subnet] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    id: Optional[int] = None


@dataclass
class PinOutline:
    """Outline shape for a pin or package."""
    type: str  # RC, CR, SQ, CT, CONTOUR
    params: dict = field(default_factory=dict)
    contour: Optional[Contour] = None


@dataclass
class Pin:
    name: str
    type: str = "TH"  # TH, SMD, etc.
    center: Point = field(default_factory=lambda: Point(0, 0))
    finished_hole_size: float = 0.0
    electrical_type: str = "U"
    mount_type: str = "U"
    id: Optional[int] = None
    outlines: list[PinOutline] = field(default_factory=list)


@dataclass
class Package:
    name: str
    pitch: float = 0.0
    bbox: Optional[BBox] = None
    pins: list[Pin] = field(default_factory=list)
    outlines: list[PinOutline] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    id: Optional[int] = None


@dataclass
class EdaData:
    source: str = ""
    units: str = "INCH"
    layer_names: list[str] = field(default_factory=list)
    nets: list[Net] = field(default_factory=list)
    packages: list[Package] = field(default_factory=list)
    properties: dict = field(default_factory=dict)


# --- Components ---

@dataclass
class Toeprint:
    pin_num: int
    x: float
    y: float
    rotation: float = 0.0
    mirror: bool = False
    net_num: int = -1
    subnet_num: int = -1
    name: str = ""


@dataclass
class BomData:
    cpn: str = ""           # Customer part number
    pkg: str = ""           # Package name
    ipn: str = ""           # Internal part number
    description: str = ""
    vendors: list[dict] = field(default_factory=list)  # VND/MPN entries


@dataclass
class Component:
    pkg_ref: int
    x: float
    y: float
    rotation: float = 0.0
    mirror: bool = False
    comp_name: str = ""
    part_name: str = ""
    attributes: dict = field(default_factory=dict)
    properties: dict = field(default_factory=dict)
    toeprints: list[Toeprint] = field(default_factory=list)
    bom_data: Optional[BomData] = None
    id: Optional[int] = None


# --- Netlist ---

@dataclass
class NetlistHeader:
    optimize: bool = False
    staggered: bool = False


@dataclass
class Netlist:
    header: NetlistHeader = field(default_factory=NetlistHeader)
    net_names: dict[int, str] = field(default_factory=dict)  # index -> name


# --- Drill Tools ---

@dataclass
class DrillTool:
    num: int
    type: str = "PLATED"
    type2: str = "STANDARD"
    min_tol: float = 0.0
    max_tol: float = 0.0
    bit: str = ""
    finish_size: float = 0.0
    drill_size: float = 0.0


@dataclass
class DrillTools:
    units: str = "INCH"
    thickness: float = 0.0
    user_params: str = ""
    tools: list[DrillTool] = field(default_factory=list)


# --- Checklist ---

@dataclass
class RuleResult:
    rule_id: str
    description: str
    category: str
    passed: bool
    message: str = ""
    affected_components: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
