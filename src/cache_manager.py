"""JSON cache manager for serializing/deserializing parsed ODB++ data."""

from __future__ import annotations

import json
import os
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from src.models import (
    ArcRecord, ArcSegment, BarcodeRecord, BomData, Component, Contour,
    EdaData, FeatureIdRef, FeaturePolarity, JobInfo, LayerFeatures,
    LineRecord, LineSegment, MatrixLayer, MatrixStep, Net, Netlist,
    Package, PadRecord, Pin, PinOutline, Point, Profile, StepHeader,
    StrokeFont, Subnet, Surface, SurfaceRecord, SymbolRef, TextRecord,
    Toeprint, UserSymbol,
)

# Type discriminators added during serialization so features can be
# reconstructed from JSON back into their original dataclass types.
_FEATURE_TYPE_MAP: dict[type, tuple[str, str]] = {
    LineRecord:    ("_type", "line"),
    PadRecord:     ("_type", "pad"),
    ArcRecord:     ("_type", "arc"),
    TextRecord:    ("_type", "text"),
    BarcodeRecord: ("_type", "barcode"),
    SurfaceRecord: ("_type", "surface"),
    LineSegment:   ("_seg_type", "line"),
    ArcSegment:    ("_seg_type", "arc"),
}


def _serialize(obj: Any) -> Any:
    """Recursively serialize dataclasses, adding type discriminators.

    Unlike dataclasses.asdict(), this visits each nested dataclass
    individually so that _type / _seg_type tags are injected at every level.
    """
    if is_dataclass(obj) and not isinstance(obj, type):
        d: dict[str, Any] = {}
        for f in fields(obj):
            d[f.name] = _serialize(getattr(obj, f.name))
        # Inject discriminator if this type needs one
        disc = _FEATURE_TYPE_MAP.get(type(obj))
        if disc:
            d[disc[0]] = disc[1]
        return d
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, FeaturePolarity):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    return obj


class OdbEncoder(json.JSONEncoder):
    """Custom JSON encoder for ODB++ dataclasses."""

    def default(self, obj: Any) -> Any:
        if is_dataclass(obj) and not isinstance(obj, type):
            return _serialize(obj)
        if isinstance(obj, FeaturePolarity):
            return obj.value
        if isinstance(obj, Path):
            return str(obj)
        return super().default(obj)


def cache_job(job_name: str, data: dict[str, Any], cache_dir: str | Path):
    """Write all parsed data to JSON files under cache_dir/<job_name>/.

    Expected data keys:
        - job_info: JobInfo
        - matrix_steps: list[MatrixStep]
        - matrix_layers: list[MatrixLayer]
        - step_header: StepHeader
        - profile: Profile
        - eda_data: EdaData
        - netlist: Netlist
        - components_top: list[Component]
        - components_bot: list[Component]
        - symbols: dict[str, UserSymbol]
        - font: StrokeFont
        - stackup: dict (optional)
    """
    cache_path = Path(cache_dir) / job_name
    cache_path.mkdir(parents=True, exist_ok=True)

    for key, value in data.items():
        if key.startswith("layer_features:"):
            # Layer features are stored separately
            layer_name = key.split(":", 1)[1]
            layers_dir = cache_path / "layers"
            layers_dir.mkdir(exist_ok=True)
            _write_json(layers_dir / f"{layer_name}.json", value)
        else:
            _write_json(cache_path / f"{key}.json", value)


def cache_layer(job_name: str, layer_name: str, features: LayerFeatures,
                cache_dir: str | Path):
    """Cache a single layer's feature data."""
    layers_dir = Path(cache_dir) / job_name / "layers"
    layers_dir.mkdir(parents=True, exist_ok=True)
    _write_json(layers_dir / f"{layer_name}.json", features)


def load_cache(cache_dir: str | Path, job_name: str) -> dict[str, Any]:
    """Load all cached JSON data for a job.

    Returns a dict with the same keys as cache_job() expects,
    but with raw dict/list values (not reconstructed dataclasses).
    """
    cache_path = Path(cache_dir) / job_name
    if not cache_path.exists():
        return {}

    data = {}

    # Load top-level files
    for json_file in cache_path.glob("*.json"):
        key = json_file.stem
        data[key] = _read_json(json_file)

    # Load layer features
    layers_dir = cache_path / "layers"
    if layers_dir.exists():
        for json_file in layers_dir.glob("*.json"):
            layer_name = json_file.stem
            data[f"layer_features:{layer_name}"] = _read_json(json_file)

    return data


def load_layer(cache_dir: str | Path, job_name: str, layer_name: str) -> dict | None:
    """Load a single layer's cached feature data."""
    path = Path(cache_dir) / job_name / "layers" / f"{layer_name}.json"
    if path.exists():
        return _read_json(path)
    return None


def is_cache_valid(cache_dir: str | Path, job_name: str,
                   source_path: str | Path) -> bool:
    """Check if cache exists and is newer than the source file."""
    cache_path = Path(cache_dir) / job_name
    source_path = Path(source_path)

    if not cache_path.exists():
        return False

    # Check if any cache file exists
    cache_files = list(cache_path.glob("*.json"))
    if not cache_files:
        return False

    # Compare modification times
    source_mtime = source_path.stat().st_mtime
    oldest_cache = min(f.stat().st_mtime for f in cache_files)

    return oldest_cache > source_mtime


def _write_json(path: Path, data: Any):
    """Write data to a JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, cls=OdbEncoder, indent=2, ensure_ascii=False)


def _read_json(path: Path) -> Any:
    """Read data from a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_component_units(cache_dir: str | Path, job_name: str,
                        side: str = "top") -> str:
    """Read component layer units from the cached comp_+_top or comp_+_bot layer file.

    Falls back to a dedicated ``components_{side}_units.json`` file when the
    layer cache is not available, and ultimately defaults to ``"INCH"``.
    """
    cache_path = Path(cache_dir) / job_name

    # 1) Try dedicated units file (written by cmd_cache)
    units_file = cache_path / f"components_{side}_units.json"
    if units_file.exists():
        return _read_json(units_file)

    # 2) Fall back to the layer features file which stores units
    layer_name = f"comp_+_{side}"
    layer_file = cache_path / "layers" / f"{layer_name}.json"
    if layer_file.exists():
        data = _read_json(layer_file)
        if isinstance(data, dict):
            return data.get("units", "INCH")

    return "INCH"


def reconstruct_layer_features(data: dict) -> LayerFeatures:
    """Reconstruct a LayerFeatures object from cached JSON data."""
    lf = LayerFeatures(
        units=data.get("units", "INCH"),
        id=data.get("id"),
        feature_count=data.get("feature_count"),
    )

    # Reconstruct symbol refs
    for sym_data in data.get("symbols", []):
        lf.symbols.append(SymbolRef(
            index=sym_data["index"],
            name=sym_data["name"],
            unit_override=sym_data.get("unit_override"),
        ))

    # Reconstruct attr lookups (JSON keys are strings, convert to int)
    for k, v in data.get("attr_names", {}).items():
        lf.attr_names[int(k)] = v
    for k, v in data.get("attr_texts", {}).items():
        lf.attr_texts[int(k)] = v

    # Reconstruct features
    for f_data in data.get("features", []):
        feature = _reconstruct_feature(f_data)
        if feature:
            lf.features.append(feature)

    return lf


def _reconstruct_feature(data: dict):
    """Reconstruct a feature record from cached JSON data."""
    ftype = data.get("_type", "")
    polarity = FeaturePolarity(data.get("polarity", "P"))

    if ftype == "line":
        return LineRecord(
            xs=data["xs"], ys=data["ys"],
            xe=data["xe"], ye=data["ye"],
            symbol_idx=data["symbol_idx"],
            polarity=polarity,
            dcode=data.get("dcode", 0),
            attributes=data.get("attributes", {}),
            id=data.get("id"),
        )
    elif ftype == "pad":
        return PadRecord(
            x=data["x"], y=data["y"],
            symbol_idx=data["symbol_idx"],
            polarity=polarity,
            dcode=data.get("dcode", 0),
            rotation=data.get("rotation", 0.0),
            mirror=data.get("mirror", False),
            resize_factor=data.get("resize_factor"),
            attributes=data.get("attributes", {}),
            id=data.get("id"),
        )
    elif ftype == "arc":
        return ArcRecord(
            xs=data["xs"], ys=data["ys"],
            xe=data["xe"], ye=data["ye"],
            xc=data["xc"], yc=data["yc"],
            symbol_idx=data["symbol_idx"],
            polarity=polarity,
            dcode=data.get("dcode", 0),
            clockwise=data.get("clockwise", True),
            attributes=data.get("attributes", {}),
            id=data.get("id"),
        )
    elif ftype == "text":
        return TextRecord(
            x=data["x"], y=data["y"],
            font=data.get("font", ""),
            polarity=polarity,
            rotation=data.get("rotation", 0.0),
            mirror=data.get("mirror", False),
            xsize=data.get("xsize", 0.0),
            ysize=data.get("ysize", 0.0),
            width_factor=data.get("width_factor", 1.0),
            text=data.get("text", ""),
            version=data.get("version", 0),
            attributes=data.get("attributes", {}),
            id=data.get("id"),
        )
    elif ftype == "barcode":
        return BarcodeRecord(
            x=data["x"], y=data["y"],
            barcode=data.get("barcode", ""),
            font=data.get("font", ""),
            polarity=polarity,
            rotation=data.get("rotation", 0.0),
            mirror=data.get("mirror", False),
            width=data.get("width", 0.0),
            height=data.get("height", 0.0),
            fasc=data.get("fasc", ""),
            cs=data.get("cs", ""),
            bg=data.get("bg", ""),
            astr=data.get("astr", ""),
            astr_pos=data.get("astr_pos", ""),
            text=data.get("text", ""),
            attributes=data.get("attributes", {}),
            id=data.get("id"),
        )
    elif ftype == "surface":
        contours = []
        for c_data in data.get("contours", []):
            contour = _reconstruct_contour(c_data)
            contours.append(contour)
        return SurfaceRecord(
            polarity=polarity,
            dcode=data.get("dcode", 0),
            contours=contours,
            attributes=data.get("attributes", {}),
            id=data.get("id"),
        )
    return None


def _reconstruct_contour(data: dict) -> Contour:
    """Reconstruct a Contour from cached JSON data."""
    start = Point(data["start"]["x"], data["start"]["y"])
    contour = Contour(is_island=data["is_island"], start=start)

    for seg_data in data.get("segments", []):
        if seg_data.get("_seg_type") == "arc" or "center" in seg_data:
            contour.segments.append(ArcSegment(
                end=Point(seg_data["end"]["x"], seg_data["end"]["y"]),
                center=Point(seg_data["center"]["x"], seg_data["center"]["y"]),
                clockwise=seg_data.get("clockwise", True),
            ))
        else:
            contour.segments.append(LineSegment(
                end=Point(seg_data["end"]["x"], seg_data["end"]["y"]),
            ))

    return contour
