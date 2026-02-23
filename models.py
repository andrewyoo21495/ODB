"""
ODB++ Data Model
Core dataclasses for representing parsed ODB++ data.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any


@dataclass
class Layer:
    name: str
    layer_type: str       # SIGNAL, POWER, DRILL, SOLDER_MASK, SILK_SCREEN, COMPONENT, ...
    polarity: str         # POSITIVE, NEGATIVE
    side: str             # TOP, BOTTOM, INNER
    index: int            # Stack order (column number)
    color: Optional[str] = None


@dataclass
class Pad:
    x: float
    y: float
    symbol_name: str      # Symbol name from features symbol table
    polarity: str         # P (positive) / N (negative)
    rotation: float = 0.0
    mirror: bool = False
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    symbol_name: str      # Width symbol name
    polarity: str


@dataclass
class Arc:
    xs: float
    ys: float             # Start point
    xe: float
    ye: float             # End point
    xc: float
    yc: float             # Center point
    symbol_name: str
    polarity: str
    clockwise: bool


@dataclass
class Surface:
    polarity: str
    islands: List[List[Tuple[float, float]]] = field(default_factory=list)
    # First island is outer boundary; subsequent are holes


@dataclass
class TextFeature:
    x: float
    y: float
    font: str
    polarity: str
    rotation: float
    xsize: float
    ysize: float
    width: float
    text: str


@dataclass
class Pin:
    pin_num: str
    x: float
    y: float
    rotation: float
    net_index: int
    subnet_index: int = 0
    net_name: Optional[str] = None


@dataclass
class Component:
    index: int
    refdes: str           # e.g., C400, U1, J10
    x: float
    y: float
    rotation: float
    mirror: bool          # True = bottom side placement
    package_ref: str
    pins: List[Pin] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    part_number: Optional[str] = None
    value: Optional[str] = None


@dataclass
class LayerData:
    layer: Layer
    pads: List[Pad] = field(default_factory=list)
    lines: List[Line] = field(default_factory=list)
    arcs: List[Arc] = field(default_factory=list)
    surfaces: List[Surface] = field(default_factory=list)
    texts: List[TextFeature] = field(default_factory=list)
    components: List[Component] = field(default_factory=list)


@dataclass
class Net:
    index: int
    name: str
    pins: List[Pin] = field(default_factory=list)


@dataclass
class ODBModel:
    product_name: str
    units: str                                        # INCH / MM
    layers: List[Layer] = field(default_factory=list)
    layer_data: Dict[str, LayerData] = field(default_factory=dict)  # {layer_name: LayerData}
    nets: Dict[str, Net] = field(default_factory=dict)              # {net_name: Net}
    step_name: str = 'pcb'
