"""JSON cache manager for serializing/deserializing parsed ODB++ data."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from src.models import (
    ArcRecord, ArcSegment, BarcodeRecord, BBox, BomData, Component, Contour,
    EdaData, FeatureIdRef, FeaturePolarity, FontChar, FontStroke, JobInfo,
    LayerFeatures, LineRecord, LineSegment, MatrixLayer, MatrixStep, Net,
    Netlist, NetlistHeader, Package, PadRecord, Pin, PinOutline, Point,
    Profile, StepHeader, StepRepeat, StrokeFont, Subnet, Surface,
    SurfaceRecord, SymbolRef, TextRecord, Toeprint, UserSymbol,
)


class OdbEncoder(json.JSONEncoder):
    """Custom JSON encoder for ODB++ dataclasses."""

    def default(self, obj: Any) -> Any:
        if is_dataclass(obj) and not isinstance(obj, type):
            d = asdict(obj)
            # Add type discriminator for feature records
            if isinstance(obj, LineRecord):
                d["_type"] = "line"
            elif isinstance(obj, PadRecord):
                d["_type"] = "pad"
            elif isinstance(obj, ArcRecord):
                d["_type"] = "arc"
            elif isinstance(obj, TextRecord):
                d["_type"] = "text"
            elif isinstance(obj, BarcodeRecord):
                d["_type"] = "barcode"
            elif isinstance(obj, SurfaceRecord):
                d["_type"] = "surface"
            elif isinstance(obj, LineSegment):
                d["_seg_type"] = "line"
            elif isinstance(obj, ArcSegment):
                d["_seg_type"] = "arc"
            return d
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


def _reconstruct_pin_outline(data: dict) -> PinOutline:
    """Reconstruct a PinOutline from cached JSON data."""
    contour = None
    if data.get("contour"):
        contour = _reconstruct_contour(data["contour"])
    return PinOutline(
        type=data.get("type", ""),
        params=data.get("params", {}),
        contour=contour,
    )


def reconstruct_job_info(data: dict) -> JobInfo:
    """Reconstruct a JobInfo object from cached JSON data."""
    return JobInfo(
        job_name=data.get("job_name", ""),
        odb_version_major=data.get("odb_version_major", 0),
        odb_version_minor=data.get("odb_version_minor", 0),
        odb_source=data.get("odb_source", ""),
        creation_date=data.get("creation_date", ""),
        save_date=data.get("save_date", ""),
        save_app=data.get("save_app", ""),
        save_user=data.get("save_user", ""),
        units=data.get("units", "INCH"),
        max_uid=data.get("max_uid", 0),
    )


def reconstruct_step_header(data: dict) -> StepHeader:
    """Reconstruct a StepHeader object from cached JSON data."""
    header = StepHeader(
        units=data.get("units", "INCH"),
        x_datum=data.get("x_datum", 0.0),
        y_datum=data.get("y_datum", 0.0),
        x_origin=data.get("x_origin", 0.0),
        y_origin=data.get("y_origin", 0.0),
        top_active=data.get("top_active", 0.0),
        bottom_active=data.get("bottom_active", 0.0),
        right_active=data.get("right_active", 0.0),
        left_active=data.get("left_active", 0.0),
        affecting_bom=data.get("affecting_bom", ""),
        affecting_bom_changed=data.get("affecting_bom_changed", 0),
        id=data.get("id", 0),
    )
    for sr in data.get("step_repeats", []):
        header.step_repeats.append(StepRepeat(
            name=sr.get("name", ""),
            x=sr.get("x", 0.0),
            y=sr.get("y", 0.0),
            dx=sr.get("dx", 0.0),
            dy=sr.get("dy", 0.0),
            nx=sr.get("nx", 1),
            ny=sr.get("ny", 1),
            angle=sr.get("angle", 0.0),
            flip=sr.get("flip", False),
            mirror=sr.get("mirror", False),
        ))
    return header


def reconstruct_profile(data: dict) -> Profile:
    """Reconstruct a Profile object from cached JSON data."""
    surface = None
    s = data.get("surface")
    if s:
        polarity = FeaturePolarity(s.get("polarity", "P"))
        surface = Surface(polarity=polarity)
        for c_data in s.get("contours", []):
            surface.contours.append(_reconstruct_contour(c_data))
    return Profile(units=data.get("units", "INCH"), surface=surface)


def reconstruct_component(data: dict) -> Component:
    """Reconstruct a Component object from cached JSON data."""
    toeprints = [
        Toeprint(
            pin_num=t["pin_num"],
            x=t["x"],
            y=t["y"],
            rotation=t.get("rotation", 0.0),
            mirror=t.get("mirror", False),
            net_num=t.get("net_num", -1),
            subnet_num=t.get("subnet_num", -1),
            name=t.get("name", ""),
        )
        for t in data.get("toeprints", [])
    ]
    bom = data.get("bom_data")
    bom_data = None
    if bom:
        bom_data = BomData(
            cpn=bom.get("cpn", ""),
            pkg=bom.get("pkg", ""),
            ipn=bom.get("ipn", ""),
            description=bom.get("description", ""),
            vendors=bom.get("vendors", []),
        )
    return Component(
        pkg_ref=data["pkg_ref"],
        x=data["x"],
        y=data["y"],
        rotation=data.get("rotation", 0.0),
        mirror=data.get("mirror", False),
        comp_name=data.get("comp_name", ""),
        part_name=data.get("part_name", ""),
        attributes=data.get("attributes", {}),
        properties=data.get("properties", {}),
        toeprints=toeprints,
        bom_data=bom_data,
        id=data.get("id"),
    )


def reconstruct_eda_data(data: dict) -> EdaData:
    """Reconstruct an EdaData object from cached JSON data."""
    eda = EdaData(
        source=data.get("source", ""),
        units=data.get("units", "INCH"),
        layer_names=data.get("layer_names", []),
        properties=data.get("properties", {}),
    )
    for n in data.get("nets", []):
        net = Net(
            name=n["name"],
            index=n["index"],
            attributes=n.get("attributes", {}),
            id=n.get("id"),
        )
        for sn in n.get("subnets", []):
            subnet = Subnet(
                type=sn["type"],
                side=sn.get("side", ""),
                comp_num=sn.get("comp_num", -1),
                toep_num=sn.get("toep_num", -1),
                fill_type=sn.get("fill_type", ""),
                cutout_type=sn.get("cutout_type", ""),
                fill_size=sn.get("fill_size", 0.0),
            )
            for fid in sn.get("feature_ids", []):
                subnet.feature_ids.append(FeatureIdRef(
                    type=fid["type"],
                    layer_idx=fid["layer_idx"],
                    feature_idx=fid["feature_idx"],
                ))
            net.subnets.append(subnet)
        eda.nets.append(net)

    for pkg_data in data.get("packages", []):
        bbox = None
        if pkg_data.get("bbox"):
            b = pkg_data["bbox"]
            bbox = BBox(b["xmin"], b["ymin"], b["xmax"], b["ymax"])
        pkg = Package(
            name=pkg_data["name"],
            pitch=pkg_data.get("pitch", 0.0),
            bbox=bbox,
            attributes=pkg_data.get("attributes", {}),
            id=pkg_data.get("id"),
        )
        for pin_data in pkg_data.get("pins", []):
            c = pin_data.get("center") or {}
            pin = Pin(
                name=pin_data["name"],
                type=pin_data.get("type", "TH"),
                center=Point(c.get("x", 0.0), c.get("y", 0.0)),
                finished_hole_size=pin_data.get("finished_hole_size", 0.0),
                electrical_type=pin_data.get("electrical_type", "U"),
                mount_type=pin_data.get("mount_type", "U"),
                id=pin_data.get("id"),
            )
            for ol in pin_data.get("outlines", []):
                pin.outlines.append(_reconstruct_pin_outline(ol))
            pkg.pins.append(pin)
        for ol in pkg_data.get("outlines", []):
            pkg.outlines.append(_reconstruct_pin_outline(ol))
        eda.packages.append(pkg)
    return eda


def reconstruct_matrix_layer(data: dict) -> MatrixLayer:
    """Reconstruct a MatrixLayer object from cached JSON data."""
    return MatrixLayer(
        row=data.get("row", 0),
        name=data.get("name", ""),
        context=data.get("context", "BOARD"),
        type=data.get("type", "SIGNAL"),
        polarity=data.get("polarity", "POSITIVE"),
        add_type=data.get("add_type", ""),
        start_name=data.get("start_name", ""),
        end_name=data.get("end_name", ""),
        old_name=data.get("old_name", ""),
        color=data.get("color", ""),
        id=data.get("id", 0),
        form=data.get("form", ""),
        dielectric_type=data.get("dielectric_type", ""),
        dielectric_name=data.get("dielectric_name", ""),
        cu_top=data.get("cu_top", ""),
        cu_bottom=data.get("cu_bottom", ""),
    )


def reconstruct_netlist(data: dict) -> Netlist:
    """Reconstruct a Netlist object from cached JSON data."""
    header = NetlistHeader(
        optimize=data.get("header", {}).get("optimize", False),
        staggered=data.get("header", {}).get("staggered", False),
    )
    netlist = Netlist(header=header)
    for k, v in data.get("net_names", {}).items():
        netlist.net_names[int(k)] = v
    return netlist


def reconstruct_user_symbol(data: dict) -> UserSymbol:
    """Reconstruct a UserSymbol object from cached JSON data."""
    sym = UserSymbol(
        name=data.get("name", ""),
        units=data.get("units", "INCH"),
    )
    for f_data in data.get("features", []):
        feature = _reconstruct_feature(f_data)
        if feature:
            sym.features.append(feature)
    return sym


def reconstruct_font(data: dict) -> StrokeFont:
    """Reconstruct a StrokeFont object from cached JSON data."""
    font = StrokeFont(
        xsize=data.get("xsize", 0.0),
        ysize=data.get("ysize", 0.0),
        offset=data.get("offset", 0.0),
    )
    for char, char_data in data.get("characters", {}).items():
        fc = FontChar(char=char_data.get("char", char))
        for s in char_data.get("strokes", []):
            fc.strokes.append(FontStroke(
                x1=s["x1"], y1=s["y1"],
                x2=s["x2"], y2=s["y2"],
                polarity=s.get("polarity", "P"),
                shape=s.get("shape", "R"),
                width=s.get("width", 0.012),
            ))
        font.characters[char] = fc
    return font
