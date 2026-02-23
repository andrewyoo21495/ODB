"""
ODB Reader
Main entry point for loading ODB++ files.
Handles .tgz / .zip archives and already-extracted directories.
"""

import os
import tarfile
import zipfile
import tempfile
import shutil
from typing import Optional, List

from models import ODBModel, Layer, LayerData
from parsers.matrix_parser import MatrixParser
from parsers.features_parser import FeaturesParser
from parsers.component_parser import ComponentParser
from parsers.eda_parser import EDAParser
from parsers.symbol_resolver import SymbolResolver
from parsers.stackup_parser import StackupParser


class ODBReader:
    """
    Loads an ODB++ product model from a .tgz file, .zip file, or an
    already-extracted directory.  Returns a fully populated ODBModel.
    """

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._tmp_dir: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, path: str) -> ODBModel:
        """
        Load an ODB++ file or directory.

        Args:
            path: Path to a .tgz archive, .zip archive, or ODB++ root directory.

        Returns:
            Fully populated ODBModel.
        """
        root_dir = self._get_root_dir(path)
        try:
            model = self._build_model(root_dir, os.path.basename(path.rstrip('/\\')))
        finally:
            self._cleanup_tmp()
        return model

    # ------------------------------------------------------------------
    # Archive handling
    # ------------------------------------------------------------------

    def _get_root_dir(self, path: str) -> str:
        """Extract archive if needed and return the ODB++ root directory."""
        if os.path.isdir(path):
            return self._find_odb_root(path)

        ext = path.lower()
        if ext.endswith('.tgz') or ext.endswith('.tar.gz'):
            return self._extract_tar(path)
        elif ext.endswith('.zip'):
            return self._extract_zip(path)
        else:
            raise ValueError(f"Unsupported file type: {path}")

    def _extract_tar(self, path: str) -> str:
        self._tmp_dir = tempfile.mkdtemp(prefix='odb_')
        self._log(f"Extracting {path} → {self._tmp_dir}")
        with tarfile.open(path, 'r:gz') as tf:
            tf.extractall(self._tmp_dir)
        return self._find_odb_root(self._tmp_dir)

    def _extract_zip(self, path: str) -> str:
        self._tmp_dir = tempfile.mkdtemp(prefix='odb_')
        self._log(f"Extracting {path} → {self._tmp_dir}")
        with zipfile.ZipFile(path, 'r') as zf:
            zf.extractall(self._tmp_dir)
        return self._find_odb_root(self._tmp_dir)

    def _cleanup_tmp(self) -> None:
        if self._tmp_dir and os.path.isdir(self._tmp_dir):
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
            self._tmp_dir = None

    @staticmethod
    def _find_odb_root(base: str) -> str:
        """
        Walk up to two levels deep to find the ODB++ root directory
        (identified by the presence of a 'matrix' subdirectory).
        """
        # Check base itself
        if os.path.isdir(os.path.join(base, 'matrix')):
            return base
        # Check one level down
        for name in os.listdir(base):
            candidate = os.path.join(base, name)
            if os.path.isdir(candidate):
                if os.path.isdir(os.path.join(candidate, 'matrix')):
                    return candidate
        # If not found, return base and let parsing fail gracefully
        return base

    # ------------------------------------------------------------------
    # Model building
    # ------------------------------------------------------------------

    def _build_model(self, root: str, product_name: str) -> ODBModel:
        self._log(f"ODB++ root: {root}")

        # 1. Parse misc/info for units and product name
        units, real_name = self._parse_misc(root, product_name)
        self._log(f"Product: {real_name}, Units: {units}")

        # 2. Parse matrix → layer list
        matrix_path = os.path.join(root, 'matrix', 'matrix')
        layers: List[Layer] = []
        if os.path.isfile(matrix_path):
            layers = MatrixParser().parse(matrix_path)
            self._log(f"Layers found: {[l.name for l in layers]}")
        else:
            self._log("WARNING: matrix/matrix not found")

        # 3. Parse optional stackup.xml
        stackup_path = os.path.join(root, 'matrix', 'stackup.xml')
        stackup_data = StackupParser().parse(stackup_path)

        # 4. Find step directory
        step_name, step_dir = self._find_step(root)
        self._log(f"Step: {step_name} → {step_dir}")

        # 5. Build symbol resolver
        symbols_dir = os.path.join(root, 'symbols')
        sym_resolver = SymbolResolver(
            symbols_dir if os.path.isdir(symbols_dir) else None
        )

        # 6. Parse EDA data → nets
        nets_by_name = {}
        net_idx_to_name = {}
        eda_path = os.path.join(step_dir, 'eda', 'data')
        if os.path.isfile(eda_path):
            eda_parser = EDAParser()
            nets_by_name, net_idx_to_name = eda_parser.parse(eda_path)
            self._log(f"Nets found: {len(nets_by_name)}")

        # 7. Build layer data
        layer_data = {}
        layer_map = {l.name: l for l in layers}
        layers_dir = os.path.join(step_dir, 'layers')

        feat_parser = FeaturesParser()
        comp_parser = ComponentParser()
        eda_parser_ref = EDAParser()

        if os.path.isdir(layers_dir):
            for layer_name in os.listdir(layers_dir):
                layer_dir = os.path.join(layers_dir, layer_name)
                if not os.path.isdir(layer_dir):
                    continue

                # Resolve or create the Layer object
                if layer_name in layer_map:
                    layer = layer_map[layer_name]
                else:
                    layer = Layer(
                        name=layer_name,
                        layer_type='SIGNAL',
                        polarity='POSITIVE',
                        side='',
                        index=len(layer_map),
                    )
                    layer_map[layer_name] = layer
                    layers.append(layer)

                ld = LayerData(layer=layer)

                # Parse features
                features_path = os.path.join(layer_dir, 'features')
                if os.path.isfile(features_path):
                    self._log(f"  Parsing features: {layer_name}")
                    ld = feat_parser.parse(features_path, layer)

                # Parse components
                comp_path = os.path.join(layer_dir, 'components')
                if os.path.isfile(comp_path):
                    self._log(f"  Parsing components: {layer_name}")
                    comps = comp_parser.parse(comp_path)
                    # Resolve pin net names
                    eda_parser_ref.resolve_pin_nets(comps, net_idx_to_name)
                    ld.components = comps

                layer_data[layer_name] = ld

        model = ODBModel(
            product_name=real_name,
            units=units,
            layers=layers,
            layer_data=layer_data,
            nets=nets_by_name,
            step_name=step_name,
        )
        self._log(f"Model loaded: {len(layers)} layers, "
                  f"{sum(len(ld.pads) for ld in layer_data.values())} total pads")
        return model

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_misc(self, root: str, fallback_name: str):
        """Parse misc/info for units and product name."""
        units = 'INCH'
        name = fallback_name
        info_path = os.path.join(root, 'misc', 'info')
        if os.path.isfile(info_path):
            with open(info_path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.upper().startswith('UNITS='):
                        units = stripped.split('=', 1)[1].strip().upper()
                    elif stripped.upper().startswith('PRODUCT_MODEL_NAME='):
                        name = stripped.split('=', 1)[1].strip()
        return units, name

    @staticmethod
    def _find_step(root: str):
        """Find the primary step directory. Prefers 'pcb', then first found."""
        steps_dir = os.path.join(root, 'steps')
        if not os.path.isdir(steps_dir):
            return 'pcb', os.path.join(root, 'steps', 'pcb')

        candidates = [
            d for d in os.listdir(steps_dir)
            if os.path.isdir(os.path.join(steps_dir, d))
        ]
        preferred = [c for c in candidates if c.lower() == 'pcb']
        chosen = preferred[0] if preferred else (candidates[0] if candidates else 'pcb')
        return chosen, os.path.join(steps_dir, chosen)

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[ODBReader] {msg}")
