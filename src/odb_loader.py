"""ODB++ archive extraction and directory structure discovery."""

from __future__ import annotations

import tarfile
import tempfile
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class LayerPaths:
    """Paths to files within a layer directory."""
    name: str
    root: Path
    features: Optional[Path] = None
    components: Optional[Path] = None
    attrlist: Optional[Path] = None
    profile: Optional[Path] = None
    tools: Optional[Path] = None


@dataclass
class StepPaths:
    """Paths to files within a step directory."""
    name: str
    root: Path
    stephdr: Optional[Path] = None
    profile: Optional[Path] = None
    eda_data: Optional[Path] = None
    eda_shortf: Optional[Path] = None
    netlist_cadnet: Optional[Path] = None
    netlist_refnet: Optional[Path] = None
    attrlist: Optional[Path] = None
    layers: dict[str, LayerPaths] = field(default_factory=dict)


@dataclass
class OdbJob:
    """Handle to a discovered ODB++ product model."""
    root_dir: Path
    job_name: str = ""

    # Top-level entity paths
    matrix_path: Optional[Path] = None
    stackup_path: Optional[Path] = None
    misc_info_path: Optional[Path] = None
    misc_attrlist_path: Optional[Path] = None
    font_path: Optional[Path] = None

    # Steps
    steps: dict[str, StepPaths] = field(default_factory=dict)

    # User-defined symbols: name -> features file path
    symbols: dict[str, Path] = field(default_factory=dict)

    # Wheels: name -> directory path
    wheels: dict[str, Path] = field(default_factory=dict)

    # Temporary directory to clean up (if extracted from archive)
    _temp_dir: Optional[str] = None

    def cleanup(self):
        """Remove temporary extracted files if any."""
        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None


def load(path: str | Path) -> OdbJob:
    """Load an ODB++ product model from a .tgz archive or extracted directory.

    Args:
        path: Path to .tgz file or extracted ODB++ directory

    Returns:
        OdbJob with all discovered file paths
    """
    path = Path(path)

    if path.is_file() and (path.suffix == ".tgz" or path.name.endswith(".tar.gz")):
        return _load_from_archive(path)
    elif path.is_dir():
        return _discover_structure(path)
    else:
        raise ValueError(f"Invalid ODB++ path: {path}")


def _load_from_archive(archive_path: Path) -> OdbJob:
    """Extract a .tgz archive and discover its structure."""
    temp_dir = tempfile.mkdtemp(prefix="odb_")

    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(temp_dir)

    # Find the product model root (first directory in the archive)
    extracted = list(Path(temp_dir).iterdir())
    if len(extracted) == 1 and extracted[0].is_dir():
        root = extracted[0]
    else:
        root = Path(temp_dir)

    job = _discover_structure(root)
    job._temp_dir = temp_dir
    return job


def _discover_structure(root: Path) -> OdbJob:
    """Walk the directory tree and identify all ODB++ entities."""
    job = OdbJob(root_dir=root)

    # Job name from directory
    job.job_name = root.name

    # Matrix
    matrix_path = root / "matrix" / "matrix"
    if matrix_path.exists():
        job.matrix_path = matrix_path

    # Stackup XML
    stackup_path = root / "matrix" / "stackup.xml"
    if stackup_path.exists():
        job.stackup_path = stackup_path

    # Misc
    misc_dir = root / "misc"
    if misc_dir.is_dir():
        info_path = misc_dir / "info"
        if info_path.exists():
            job.misc_info_path = info_path
        attrlist_path = misc_dir / "attrlist"
        if attrlist_path.exists():
            job.misc_attrlist_path = attrlist_path

    # Fonts
    font_path = root / "fonts" / "standard"
    if font_path.exists():
        job.font_path = font_path

    # Steps
    steps_dir = root / "steps"
    if steps_dir.is_dir():
        for step_dir in steps_dir.iterdir():
            if step_dir.is_dir():
                step = _discover_step(step_dir)
                job.steps[step.name] = step

    # User-defined symbols
    symbols_dir = root / "symbols"
    if symbols_dir.is_dir():
        for sym_dir in symbols_dir.iterdir():
            if sym_dir.is_dir():
                features = _find_file(sym_dir, "features")
                if features:
                    job.symbols[sym_dir.name] = features

    # Wheels
    wheels_dir = root / "wheels"
    if wheels_dir.is_dir():
        for wheel_dir in wheels_dir.iterdir():
            if wheel_dir.is_dir():
                job.wheels[wheel_dir.name] = wheel_dir

    return job


def _discover_step(step_dir: Path) -> StepPaths:
    """Discover all entities within a step directory."""
    step = StepPaths(name=step_dir.name, root=step_dir)

    step.stephdr = _find_file(step_dir, "stephdr")
    step.profile = _find_file(step_dir, "profile")
    step.attrlist = _find_file(step_dir, "attrlist")

    # EDA
    eda_dir = step_dir / "eda"
    if eda_dir.is_dir():
        step.eda_data = _find_file(eda_dir, "data")
        step.eda_shortf = _find_file(eda_dir, "shortf")

    # Netlists
    netlists_dir = step_dir / "netlists"
    if netlists_dir.is_dir():
        cadnet_dir = netlists_dir / "cadnet"
        if cadnet_dir.is_dir():
            step.netlist_cadnet = _find_file(cadnet_dir, "netlist")
        refnet_dir = netlists_dir / "refnet"
        if refnet_dir.is_dir():
            step.netlist_refnet = _find_file(refnet_dir, "netlist")

    # Layers
    layers_dir = step_dir / "layers"
    if layers_dir.is_dir():
        for layer_dir in layers_dir.iterdir():
            if layer_dir.is_dir():
                layer = _discover_layer(layer_dir)
                step.layers[layer.name] = layer

    return step


def _discover_layer(layer_dir: Path) -> LayerPaths:
    """Discover all entities within a layer directory."""
    layer = LayerPaths(name=layer_dir.name, root=layer_dir)
    layer.features = _find_file(layer_dir, "features")
    layer.components = _find_file(layer_dir, "components")
    layer.attrlist = _find_file(layer_dir, "attrlist")
    layer.profile = _find_file(layer_dir, "profile")
    layer.tools = _find_file(layer_dir, "tools")
    return layer


def _find_file(directory: Path, name: str) -> Optional[Path]:
    """Find a file, checking for .Z compressed variant too."""
    plain = directory / name
    if plain.exists():
        return plain
    compressed = directory / (name + ".Z")
    if compressed.exists():
        return compressed
    return None
